"""Create (or reset) the first Super Administrator account.

Interactive:
    python -m scripts.create_superadmin

Non-interactive (e.g. Docker); the password is read from the environment, never argv:
    SUPERADMIN_PASSWORD='...' python -m scripts.create_superadmin \
        --username admin --email admin@example.com --full-name "System Administrator"
"""

import argparse
import getpass
import os
import sys

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.core.permissions import RoleName
from app.core.security import hash_password, password_problems
from app.models import User
from app.services import audit_service
from app.services.rbac_service import get_role, sync_roles_and_permissions


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--username", default=None)
    parser.add_argument("--email", default=None)
    parser.add_argument("--full-name", default=None)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="If the user exists, reset their password and make them an active super admin",
    )
    args = parser.parse_args()

    username = (args.username or input("Username [admin]: ").strip() or "admin").lower()
    email = (args.email or input("Email: ").strip()).lower()
    full_name = (
        args.full_name
        or input("Full name [System Administrator]: ").strip()
        or "System Administrator"
    )
    try:
        # Same rules as the API, so the account can later be edited in the UI.
        email = validate_email(email, check_deliverability=False).normalized.lower()
    except EmailNotValidError as exc:
        print(f"Invalid email address: {exc}", file=sys.stderr)
        return 2

    password = os.environ.get("SUPERADMIN_PASSWORD")
    if not password:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Confirm password: "):
            print("Passwords do not match.", file=sys.stderr)
            return 2
    problems = password_problems(password, username=username)
    if problems:
        print("Password " + "; ".join(problems), file=sys.stderr)
        return 2

    with SessionLocal() as db:
        sync_roles_and_permissions(db)
        role = get_role(db, RoleName.SUPER_ADMIN.value)
        assert role is not None
        user = db.scalar(select(User).where(func.lower(User.username) == username))
        if user and not args.reset:
            print(f"User '{username}' already exists. Use --reset to reset it.", file=sys.stderr)
            return 1
        if user is None:
            user = User(
                username=username,
                email=email,
                full_name=full_name,
                role=role,
                password_hash=hash_password(password),
                is_active=True,
            )
            db.add(user)
            action = "user.create_superadmin"
        else:
            user.password_hash = hash_password(password)
            user.role = role
            user.is_active = True
            user.locked_until = None
            user.failed_login_count = 0
            action = "user.reset_superadmin"
        user.must_change_password = False
        db.flush()
        audit_service.record(
            db,
            action=action,
            actor=None,
            entity_type="user",
            entity_id=user.id,
            details="via create_superadmin script",
        )
        db.commit()
        print(f"Super Administrator '{username}' is ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
