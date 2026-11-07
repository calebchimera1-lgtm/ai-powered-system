"""Import every model so Alembic autogenerate and relationship resolution see them."""

from app.models.analytics import (
    AnomalyAlert,
    Forecast,
    ForecastRun,
    Notification,
    ProductForecast,
)
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
from app.models.finance import Expense, ExpenseCategory
from app.models.invoice import Invoice, InvoiceItem, SupplierProductAlias
from app.models.procurement import Purchase, PurchaseItem, PurchaseOrder, PurchaseOrderItem
from app.models.sales import Customer, Sale, SaleItem, SaleReturn, SaleReturnItem
from app.models.stock import StockAdjustment, StockMovement
from app.models.supplier import Supplier, SupplierProduct
from app.models.system import AuditLog, BackgroundJob

__all__ = [
    "AnomalyAlert",
    "Forecast",
    "ForecastRun",
    "Notification",
    "ProductForecast",
    "AuditLog",
    "BackgroundJob",
    "Base",
    "Category",
    "Customer",
    "Expense",
    "ExpenseCategory",
    "Invoice",
    "InvoiceItem",
    "PasswordResetToken",
    "Permission",
    "Product",
    "ProductBatch",
    "Purchase",
    "PurchaseItem",
    "PurchaseOrder",
    "PurchaseOrderItem",
    "Role",
    "Sale",
    "SaleItem",
    "SaleReturn",
    "SaleReturnItem",
    "StockAdjustment",
    "StockMovement",
    "Supplier",
    "SupplierProduct",
    "SupplierProductAlias",
    "User",
    "UserSession",
    "role_permissions",
]
