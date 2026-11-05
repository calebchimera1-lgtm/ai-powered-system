"""The role → permission matrix must match the design plan (section 1.6)."""

import pytest

from app.core.permissions import PERMISSION_DESCRIPTIONS, ROLE_PERMISSIONS, P, RoleName


def perms(role: RoleName) -> frozenset[P]:
    return ROLE_PERMISSIONS[role]


def test_every_permission_has_a_description() -> None:
    assert set(PERMISSION_DESCRIPTIONS) == set(P)


def test_super_admin_has_everything() -> None:
    assert perms(RoleName.SUPER_ADMIN) == frozenset(P)


@pytest.mark.parametrize(
    "permission",
    [P.USERS_MANAGE, P.AUDIT_READ, P.SETTINGS_MANAGE, P.BACKUPS_MANAGE, P.STOCK_ADJUST_NEGATIVE],
)
def test_store_manager_lacks_admin_only(permission: P) -> None:
    assert permission not in perms(RoleName.STORE_MANAGER)


def test_store_manager_core_rights() -> None:
    needed = {
        P.USERS_READ,
        P.FINANCE_READ,
        P.INVOICES_APPROVE,
        P.RETURNS_APPROVE,
        P.ANOMALIES_REVIEW,
        P.PRODUCTS_DELETE,
        P.SALES_CREATE,
        P.REPORTS_ALL,
    }
    assert needed <= perms(RoleName.STORE_MANAGER)


def test_inventory_officer_scope() -> None:
    p = perms(RoleName.INVENTORY_OFFICER)
    assert {P.PRODUCTS_WRITE, P.INVOICES_UPLOAD, P.INVOICES_APPROVE, P.STOCK_WRITE_OFF} <= p
    assert (
        not {P.SALES_CREATE, P.FINANCE_READ, P.ANOMALIES_READ, P.PRODUCTS_DELETE, P.USERS_READ} & p
    )


def test_cashier_is_minimal() -> None:
    assert perms(RoleName.CASHIER) == {
        P.PRODUCTS_READ,
        P.SALES_CREATE,
        P.SALES_READ_OWN,
        P.RETURNS_REQUEST,
        P.REPORTS_OWN_SALES,
    }
    assert P.PRODUCTS_VIEW_COST not in perms(RoleName.CASHIER)
