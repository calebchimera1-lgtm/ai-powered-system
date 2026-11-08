"""Restore a backup made by the system (database, and uploaded files unless --no-files).

THIS REPLACES THE CURRENT DATA. Stop the app first so nothing writes while it runs:

    docker compose stop api worker
    docker compose run --rm api python -m scripts.restore_backup --list
    docker compose run --rm api python -m scripts.restore_backup 20261108-020000-daily --yes
    docker compose start api worker

The backup's checksums are verified before anything is touched, and the database is
restored in a single transaction: if it fails part-way, nothing changes.
"""

import argparse
import sys

from app.services import backup_service


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore a backup (replaces current data)")
    parser.add_argument("name", nargs="?", help="backup name, e.g. 20261108-020000-daily")
    parser.add_argument("--list", action="store_true", help="list the available backups")
    parser.add_argument("--no-files", action="store_true", help="restore the database only")
    parser.add_argument("--yes", action="store_true", help="confirm: replace the current data")
    args = parser.parse_args()

    backups = backup_service.list_backups()
    if args.list or not args.name:
        if not backups:
            print("No backups found in", backup_service.backup_root())
        for b in backups:
            print(
                f"{b['name']:30} {b['created_at'][:19]}  {b['total_bytes'] / 1e6:7.1f} MB  "
                f"schema {b['schema_revision']}  products {b['row_counts']['products']}, "
                f"sales {b['row_counts']['sales']}"
            )
        return 0
    if args.name not in {b["name"] for b in backups}:
        print(f"No backup called {args.name}. Use --list.", file=sys.stderr)
        return 2
    if not args.yes:
        print(
            "This replaces the current database"
            + ("" if args.no_files else " and uploaded files")
            + f" with backup {args.name}. Re-run with --yes to continue.",
            file=sys.stderr,
        )
        return 1
    m = backup_service.restore(args.name, files=not args.no_files)
    print(f"Restored {m['name']} (created {m['created_at'][:19]}, schema {m['schema_revision']}).")
    print("If the app is newer than the backup, run: alembic upgrade head")
    return 0


if __name__ == "__main__":
    sys.exit(main())
