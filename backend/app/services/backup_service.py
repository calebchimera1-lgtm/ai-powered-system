"""Backups: a PostgreSQL dump plus an archive of uploaded files, checked and rotated.

Each backup is a folder under <storage>/backups/<name>/ with:
* database.dump   pg_dump custom format (compressed; restore with pg_restore)
* files.tar.gz    uploaded files (product photos, invoices), without the backups themselves
* manifest.json   when, what, sizes, SHA-256 checksums and the database schema version

Rotation keeps the 7 most recent daily backups, one per ISO week for the last 4 weeks,
and the 5 most recent manual ones. Restoring is deliberately a command-line step
(scripts/restore_backup.py), never a button: it replaces the live data.
"""

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, ValidationFailed

KEEP_DAILY = 7
KEEP_WEEKLY = 4
KEEP_MANUAL = 5
FILES = ("database.dump", "files.tar.gz", "manifest.json")


class BackupError(RuntimeError):
    pass


def backup_root() -> Path:
    root = Path(get_settings().storage_dir) / "backups"
    root.mkdir(parents=True, exist_ok=True)
    return root


def libpq(url: str) -> tuple[list[str], dict[str, str]]:
    """Connection arguments for pg_dump/pg_restore, with the password in the environment
    (not on the command line, where other processes could see it)."""
    parts = urlsplit(url.replace("+psycopg", "").replace("+psycopg2", ""))
    args = [
        "--host",
        parts.hostname or "localhost",
        "--port",
        str(parts.port or 5432),
        "--username",
        unquote(parts.username or "postgres"),
    ]
    env = {**os.environ, "PGPASSWORD": unquote(parts.password or "")}
    return args, env | {"PGDATABASE": parts.path.lstrip("/")}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _run(cmd: list[str], env: dict[str, str]) -> None:
    try:
        subprocess.run(cmd, env=env, check=True, capture_output=True, timeout=1800)  # noqa: S603
    except FileNotFoundError as exc:
        raise BackupError(f"{cmd[0]} is not installed in this container") from exc
    except subprocess.CalledProcessError as exc:
        raise BackupError(exc.stderr.decode(errors="replace")[-2000:]) from exc


def create(db: Session, kind: str = "daily") -> dict[str, Any]:
    if kind not in ("daily", "manual"):
        raise ValidationFailed("Unknown backup kind")
    settings = get_settings()
    now = datetime.now(UTC)
    name = f"{now:%Y%m%d-%H%M%S}-{kind}"
    folder = backup_root() / name
    tmp = backup_root() / f".{name}.partial"
    tmp.mkdir(parents=True)
    try:
        args, env = libpq(settings.database_url)
        dump = tmp / "database.dump"
        _run(
            [
                "pg_dump",
                *args,
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--file",
                str(dump),
                env["PGDATABASE"],
            ],
            env,
        )
        _run(["pg_restore", "--list", str(dump)], env)  # proves the dump is readable

        storage = Path(settings.storage_dir).resolve()
        archive = tmp / "files.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            for entry in sorted(storage.iterdir()) if storage.exists() else []:
                if entry.name == "backups":
                    continue
                tar.add(entry, arcname=entry.name)

        revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
        counts = {
            t: db.execute(text(f"SELECT count(*) FROM {t}")).scalar()  # noqa: S608 - fixed names
            for t in ("products", "sales", "stock_movements", "purchases", "users")
        }
        manifest = {
            "name": name,
            "kind": kind,
            "created_at": now.isoformat(),
            "schema_revision": revision,
            "store": settings.store_name,
            "row_counts": counts,
            "files": {
                p.name: {"bytes": p.stat().st_size, "sha256": _sha256(p)} for p in (dump, archive)
            },
            "verified": True,
        }
        (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2))
        tmp.rename(folder)  # appears only when complete
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    removed = rotate()
    return {**manifest, "removed": removed}


def list_backups() -> list[dict[str, Any]]:
    out = []
    for folder in sorted(backup_root().iterdir(), reverse=True):
        manifest = folder / "manifest.json"
        if folder.name.startswith(".") or not manifest.exists():
            continue
        m = json.loads(manifest.read_text())
        m["total_bytes"] = sum(f["bytes"] for f in m["files"].values())
        out.append(m)
    return out


def rotate(now: datetime | None = None) -> list[str]:
    """Delete backups outside the retention policy; returns the removed names."""
    backups = list_backups()  # newest first
    keep: set[str] = set()
    daily = [b for b in backups if b["kind"] == "daily"]
    keep |= {b["name"] for b in daily[:KEEP_DAILY]}
    weeks: dict[tuple[int, int], str] = {}
    for b in daily:  # newest first: the first seen in each week is that week's newest
        week = datetime.fromisoformat(b["created_at"]).isocalendar()[:2]
        weeks.setdefault(week, b["name"])
    keep |= set(list(weeks.values())[:KEEP_WEEKLY])
    keep |= {b["name"] for b in [b for b in backups if b["kind"] == "manual"][:KEEP_MANUAL]}
    removed = []
    for b in backups:
        if b["name"] not in keep:
            shutil.rmtree(backup_root() / b["name"], ignore_errors=True)
            removed.append(b["name"])
    return removed


def path_of(name: str, file: str) -> Path:
    if file not in FILES or "/" in name or name.startswith("."):
        raise NotFoundError("Backup file not found")
    path = backup_root() / name / file
    if not path.is_file():
        raise NotFoundError("Backup file not found")
    return path


def restore(name: str, database_url: str | None = None, *, files: bool = True) -> dict[str, Any]:
    """Replace the database (and optionally the uploaded files) with a backup.

    Used by scripts/restore_backup.py. Stop the api and worker first so nothing writes
    while the data is replaced."""
    settings = get_settings()
    folder = backup_root() / name
    manifest = json.loads((folder / "manifest.json").read_text())
    for fname, info in manifest["files"].items():
        if _sha256(folder / fname) != info["sha256"]:
            raise BackupError(f"{fname} does not match its checksum: the backup is damaged")
    args, env = libpq(database_url or settings.database_url)
    _run(
        [
            "pg_restore",
            *args,
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
            "--single-transaction",
            "--dbname",
            env["PGDATABASE"],
            str(folder / "database.dump"),
        ],
        env,
    )
    if files:
        storage = Path(settings.storage_dir).resolve()
        with tarfile.open(folder / "files.tar.gz", "r:gz") as tar:
            tar.extractall(storage, filter="data")  # "data" filter blocks path tricks
    return manifest
