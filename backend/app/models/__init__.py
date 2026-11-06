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
from app.models.catalog import Category, Product, ProductBatch
from app.models.stock import StockAdjustment, StockMovement
from app.models.supplier import Supplier, SupplierProduct
from app.models.system import AuditLog, BackgroundJob

__all__ = [
    "AuditLog",
    "BackgroundJob",
    "Base",
    "Category",
    "PasswordResetToken",
    "Permission",
    "Product",
    "ProductBatch",
    "Role",
    "StockAdjustment",
    "StockMovement",
    "Supplier",
    "SupplierProduct",
    "User",
    "UserSession",
    "role_permissions",
]
