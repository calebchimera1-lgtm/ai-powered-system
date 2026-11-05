"""Import every model so Alembic autogenerate and relationship resolution see them."""

from app.models.auth import (
    PasswordResetToken,
    Permission,
    Role,
    User,
    UserSession,
    role_permissions,
)
from app.models.base import Base
from app.models.system import AuditLog, BackgroundJob

__all__ = [
    "AuditLog",
    "BackgroundJob",
    "Base",
    "PasswordResetToken",
    "Permission",
    "Role",
    "User",
    "UserSession",
    "role_permissions",
]
