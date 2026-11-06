"""Permission catalogue and default role → permission mapping.

Permissions are defined in code (so endpoints can reference them safely) and mirrored
into the `permissions`, `roles` and `role_permissions` tables by `sync_roles_and_permissions`.
The catalogue covers every planned module so the matrix in the design plan is enforced
from day one; endpoints for later phases reuse these codes.
"""

from enum import StrEnum


class P(StrEnum):
    # Users & administration
    USERS_READ = "users:read"
    USERS_MANAGE = "users:manage"
    ROLES_READ = "roles:read"
    AUDIT_READ = "audit:read"
    SETTINGS_MANAGE = "settings:manage"
    BACKUPS_MANAGE = "backups:manage"

    # Catalogue
    PRODUCTS_READ = "products:read"
    PRODUCTS_WRITE = "products:write"
    PRODUCTS_DELETE = "products:delete"
    PRODUCTS_VIEW_COST = "products:view_cost"

    # Stock
    STOCK_READ = "stock:read"
    STOCK_ADJUST = "stock:adjust"
    STOCK_ADJUST_APPROVE = "stock:adjust_approve"
    STOCK_ADJUST_NEGATIVE = "stock:adjust_negative"
    STOCK_WRITE_OFF = "stock:write_off"

    # Suppliers & procurement
    SUPPLIERS_READ = "suppliers:read"
    SUPPLIERS_WRITE = "suppliers:write"
    PURCHASES_READ = "purchases:read"
    PURCHASES_WRITE = "purchases:write"

    # Invoice digitization
    INVOICES_UPLOAD = "invoices:upload"
    INVOICES_APPROVE = "invoices:approve"

    # Sales
    SALES_CREATE = "sales:create"
    SALES_READ_OWN = "sales:read_own"
    SALES_READ_ALL = "sales:read_all"
    SALES_DISCOUNT_ANY = "sales:discount_any"
    RETURNS_REQUEST = "returns:request"
    RETURNS_APPROVE = "returns:approve"

    # Finance & analytics
    FINANCE_READ = "finance:read"
    EXPENSES_WRITE = "expenses:write"
    DASHBOARD_READ = "dashboard:read"
    FORECASTS_READ = "forecasts:read"
    ANOMALIES_READ = "anomalies:read"
    ANOMALIES_REVIEW = "anomalies:review"

    # Reports
    REPORTS_ALL = "reports:all"
    REPORTS_INVENTORY = "reports:inventory"
    REPORTS_OWN_SALES = "reports:own_sales"


PERMISSION_DESCRIPTIONS: dict[P, str] = {
    P.USERS_READ: "View user accounts",
    P.USERS_MANAGE: "Create, edit, deactivate users and issue password resets",
    P.ROLES_READ: "View roles and their permissions",
    P.AUDIT_READ: "View the audit log",
    P.SETTINGS_MANAGE: "Change system settings",
    P.BACKUPS_MANAGE: "Run and restore backups",
    P.PRODUCTS_READ: "Search and view products",
    P.PRODUCTS_WRITE: "Create and edit products and categories",
    P.PRODUCTS_DELETE: "Deactivate or delete products",
    P.PRODUCTS_VIEW_COST: "View purchase costs and margins",
    P.STOCK_READ: "View stock levels and movements",
    P.STOCK_ADJUST: "Request manual stock adjustments",
    P.STOCK_ADJUST_APPROVE: "Approve large stock adjustments",
    P.STOCK_ADJUST_NEGATIVE: "Authorise adjustments that make stock negative",
    P.STOCK_WRITE_OFF: "Record damaged or expired goods",
    P.SUPPLIERS_READ: "View suppliers",
    P.SUPPLIERS_WRITE: "Create and edit suppliers",
    P.PURCHASES_READ: "View purchase orders and goods received",
    P.PURCHASES_WRITE: "Create purchase orders and receive goods",
    P.INVOICES_UPLOAD: "Upload supplier invoices and receipts",
    P.INVOICES_APPROVE: "Review and approve digitized invoices",
    P.SALES_CREATE: "Record sales at the point of sale",
    P.SALES_READ_OWN: "View own sales",
    P.SALES_READ_ALL: "View all sales",
    P.SALES_DISCOUNT_ANY: "Give discounts above the cashier limit",
    P.RETURNS_REQUEST: "Request customer returns",
    P.RETURNS_APPROVE: "Approve returns and refunds",
    P.FINANCE_READ: "View revenue, cost and profit analytics",
    P.EXPENSES_WRITE: "Record operating expenses",
    P.DASHBOARD_READ: "View the management dashboard",
    P.FORECASTS_READ: "View demand forecasts and reorder recommendations",
    P.ANOMALIES_READ: "View inventory anomaly alerts",
    P.ANOMALIES_REVIEW: "Investigate and close anomaly alerts",
    P.REPORTS_ALL: "Export all reports",
    P.REPORTS_INVENTORY: "Export inventory reports",
    P.REPORTS_OWN_SALES: "Export own daily sales report",
}


class RoleName(StrEnum):
    SUPER_ADMIN = "super_admin"
    STORE_MANAGER = "store_manager"
    INVENTORY_OFFICER = "inventory_officer"
    CASHIER = "cashier"


ROLE_DISPLAY: dict[RoleName, tuple[str, str]] = {
    RoleName.SUPER_ADMIN: (
        "Super Administrator",
        "Full access including users, settings and audit",
    ),
    RoleName.STORE_MANAGER: ("Store Manager", "Runs the store: stock, sales, finance, approvals"),
    RoleName.INVENTORY_OFFICER: ("Inventory Officer", "Products, suppliers, invoices and stock"),
    RoleName.CASHIER: ("Cashier", "Point of sale and own sales history"),
}

_ALL = frozenset(P)

ROLE_PERMISSIONS: dict[RoleName, frozenset[P]] = {
    RoleName.SUPER_ADMIN: _ALL,
    RoleName.STORE_MANAGER: _ALL
    - {
        P.USERS_MANAGE,
        P.AUDIT_READ,
        P.SETTINGS_MANAGE,
        P.BACKUPS_MANAGE,
        P.STOCK_ADJUST_NEGATIVE,
        P.REPORTS_INVENTORY,  # covered by REPORTS_ALL
        P.REPORTS_OWN_SALES,
        P.SALES_READ_OWN,
        P.RETURNS_REQUEST,
    },
    RoleName.INVENTORY_OFFICER: frozenset(
        {
            P.PRODUCTS_READ,
            P.PRODUCTS_WRITE,
            P.PRODUCTS_VIEW_COST,
            P.STOCK_READ,
            P.STOCK_ADJUST,
            P.STOCK_WRITE_OFF,
            P.SUPPLIERS_READ,
            P.SUPPLIERS_WRITE,
            P.PURCHASES_READ,
            P.PURCHASES_WRITE,
            P.INVOICES_UPLOAD,
            P.INVOICES_APPROVE,
            P.FORECASTS_READ,
            P.REPORTS_INVENTORY,
        }
    ),
    RoleName.CASHIER: frozenset(
        {
            P.PRODUCTS_READ,
            P.SALES_CREATE,
            P.SALES_READ_OWN,
            P.RETURNS_REQUEST,
            P.REPORTS_OWN_SALES,
        }
    ),
}
