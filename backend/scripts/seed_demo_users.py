"""Create one DEMONSTRATION account per role (synthetic data, for presentations only).

    python -m scripts.seed_demo_users

Accounts are created only if missing. All share the password in DEMO_PASSWORD
(default shown below). Never run this on a real store's database.
"""

import os
import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.permissions import RoleName
from app.core.security import hash_password
from app.models import User
from app.services import audit_service
from app.services.rbac_service import get_role, sync_roles_and_permissions

DEMO_USERS = [
    ("admin", "Amina Wanjiru (Demo Admin)", "admin@example.com", RoleName.SUPER_ADMIN),
    ("manager", "Brian Otieno (Demo Manager)", "manager@example.com", RoleName.STORE_MANAGER),
    (
        "inventory",
        "Cynthia Mutua (Demo Inventory Officer)",
        "inventory@example.com",
        RoleName.INVENTORY_OFFICER,
    ),
    ("cashier", "David Kiprop (Demo Cashier)", "cashier@example.com", RoleName.CASHIER),
]


def main() -> int:
    if get_settings().is_production:
        print("Refusing to seed demo users in production.", file=sys.stderr)
        return 1
    password = os.environ.get("DEMO_PASSWORD", "Demo@2026!")
    with SessionLocal() as db:
        sync_roles_and_permissions(db)
        for username, name, email, role_name in DEMO_USERS:
            if db.scalar(select(User).where(User.username == username)):
                print(f"  exists   {username}")
                continue
            user = User(
                username=username,
                full_name=name,
                email=email,
                role=get_role(db, role_name.value),
                password_hash=hash_password(password),
                is_active=True,
                must_change_password=False,
            )
            db.add(user)
            db.flush()
            audit_service.record(
                db,
                action="user.create",
                actor=None,
                entity_type="user",
                entity_id=user.id,
                details="demo seed",
            )
            print(f"  created  {username:<10} ({role_name.value})")
        db.commit()
    print(f"Demo password for all accounts: {password}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
