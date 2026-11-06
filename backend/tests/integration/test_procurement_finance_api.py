"""Purchase orders, goods received, expenses and profit analytics, plus the brief's
end-to-end scenario (receive -> sell -> stock and profit update)."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

D = Decimal


@pytest.fixture
def env(client: TestClient, auth_headers):  # type: ignore[no-untyped-def]
    admin = auth_headers("super_admin", username="boss")[1]
    officer = auth_headers("inventory_officer", username="officer")[1]
    manager = auth_headers("store_manager", username="mgr")[1]
    cashier = auth_headers("cashier", username="till")[1]
    sup = client.post(
        "/api/v1/suppliers",
        headers=admin,
        json={"name": "Demo Wholesalers Ltd", "kra_pin": "P051111111A"},
    ).json()
    other = client.post("/api/v1/suppliers", headers=admin, json={"name": "Other Ltd"}).json()
    sugar = client.post(
        "/api/v1/products",
        headers=admin,
        json={
            "name": "White Sugar 2kg",
            "selling_price": "245",
            "opening_stock": {"quantity": "10", "unit_cost": "200"},
        },
    ).json()
    milk = client.post(
        "/api/v1/products",
        headers=admin,
        json={
            "name": "Fresh Milk 500ml",
            "selling_price": "65",
            "tracks_expiry": True,
            "vat_rate": "0",
        },
    ).json()
    return {
        "admin": admin,
        "officer": officer,
        "manager": manager,
        "cashier": cashier,
        "sup": sup,
        "other": other,
        "sugar": sugar,
        "milk": milk,
    }


def get_product(client, h, p):  # type: ignore[no-untyped-def]
    return client.get(f"/api/v1/products/{p['id']}", headers=h).json()


# --- Purchase orders -------------------------------------------------------------


def test_purchase_order_lifecycle_with_partial_delivery(client: TestClient, env) -> None:
    e = env
    po = client.post(
        "/api/v1/purchase-orders",
        headers=e["officer"],
        json={
            "supplier_id": e["sup"]["id"],
            "expected_date": str(date.today() + timedelta(days=3)),
            "items": [
                {"product_id": e["sugar"]["id"], "quantity": "30", "unit_cost": "205"},
                {"product_id": e["milk"]["id"], "quantity": "24", "unit_cost": "48"},
            ],
        },
    )
    assert po.status_code == 201, po.text
    po = po.json()
    assert po["po_number"].startswith("PO-") and po["status"] == "DRAFT"
    assert po["total"] == "7302.00"  # 30 x 205 + 24 x 48

    sent = client.post(f"/api/v1/purchase-orders/{po['id']}/send", headers=e["officer"]).json()
    assert sent["status"] == "SENT"
    assert (
        client.put(
            f"/api/v1/purchase-orders/{po['id']}",
            headers=e["officer"],
            json={
                "supplier_id": e["sup"]["id"],
                "items": [{"product_id": e["sugar"]["id"], "quantity": "1", "unit_cost": "1"}],
            },
        ).status_code
        == 422
    )  # only drafts are editable

    # First delivery: sugar only.
    r = client.post(
        "/api/v1/purchases",
        headers=e["officer"],
        json={
            "supplier_id": e["sup"]["id"],
            "purchase_order_id": po["id"],
            "supplier_invoice_number": "inv-1001",
            "items": [{"product_id": e["sugar"]["id"], "quantity": "30", "unit_cost": "205"}],
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["supplier_invoice_number"] == "INV-1001"
    po_now = client.get(f"/api/v1/purchase-orders/{po['id']}", headers=e["officer"]).json()
    assert po_now["status"] == "PARTIAL"

    # Second delivery: the milk, with expiry.
    r = client.post(
        "/api/v1/purchases",
        headers=e["officer"],
        json={
            "supplier_id": e["sup"]["id"],
            "purchase_order_id": po["id"],
            "supplier_invoice_number": "INV-1002",
            "items": [
                {
                    "product_id": e["milk"]["id"],
                    "quantity": "24",
                    "unit_cost": "48",
                    "expiry_date": str(date.today() + timedelta(days=7)),
                    "batch_number": "L9",
                }
            ],
        },
    )
    assert r.status_code == 201, r.text
    assert (
        client.get(f"/api/v1/purchase-orders/{po['id']}", headers=e["officer"]).json()["status"]
        == "RECEIVED"
    )
    open_orders = client.get(
        "/api/v1/purchase-orders", headers=e["officer"], params={"status": "OPEN"}
    ).json()
    assert open_orders["total"] == 0


def test_goods_received_updates_stock_wac_vat_and_supplier_price(client: TestClient, env) -> None:
    e = env
    r = client.post(
        "/api/v1/purchases",
        headers=e["officer"],
        json={
            "supplier_id": e["sup"]["id"],
            "supplier_invoice_number": "INV-77",
            "items": [{"product_id": e["sugar"]["id"], "quantity": "30", "unit_cost": "220"}],
        },
    )
    assert r.status_code == 201, r.text
    grn = r.json()
    assert grn["grn_number"].startswith("GRN-")
    assert grn["subtotal"] == "6600.00" and grn["tax_total"] == "1056.00"
    assert grn["grand_total"] == "7656.00"
    # 220 vs previous 200 = +10% -> flagged
    assert grn["price_changes"] == [
        {
            "product_id": e["sugar"]["id"],
            "product_name": "White Sugar 2kg",
            "previous_unit_cost": "200.0000",
            "new_unit_cost": "220.0000",
            "change_percent": "10.00",
        }
    ]
    sugar = get_product(client, e["admin"], e["sugar"])
    assert sugar["quantity_on_hand"] == "40.000"
    assert sugar["avg_cost"] == "215.0000"  # (10 x 200 + 30 x 220) / 40
    assert sugar["purchase_price"] == "220.00"
    prices = client.get(f"/api/v1/products/{e['sugar']['id']}/suppliers", headers=e["admin"]).json()
    assert prices[0]["last_unit_price"] == "220.00"


def test_duplicate_supplier_invoice_is_blocked(client: TestClient, env) -> None:
    e = env
    body = {
        "supplier_id": e["sup"]["id"],
        "supplier_invoice_number": "INV-5",
        "items": [{"product_id": e["sugar"]["id"], "quantity": "1", "unit_cost": "200"}],
    }
    assert client.post("/api/v1/purchases", headers=e["officer"], json=body).status_code == 201
    dup = client.post(
        "/api/v1/purchases", headers=e["officer"], json={**body, "supplier_invoice_number": "inv-5"}
    )
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "DUPLICATE_INVOICE"
    # Same number from a different supplier is a different invoice.
    assert (
        client.post(
            "/api/v1/purchases",
            headers=e["officer"],
            json={**body, "supplier_id": e["other"]["id"]},
        ).status_code
        == 201
    )
    assert get_product(client, e["admin"], e["sugar"])["quantity_on_hand"] == "12.000"


def test_receipt_validation(client: TestClient, env) -> None:
    e = env
    no_expiry = client.post(
        "/api/v1/purchases",
        headers=e["officer"],
        json={
            "supplier_id": e["sup"]["id"],
            "items": [{"product_id": e["milk"]["id"], "quantity": "5", "unit_cost": "48"}],
        },
    )
    assert no_expiry.status_code == 422 and "expiry" in no_expiry.json()["error"]["message"]
    po = client.post(
        "/api/v1/purchase-orders",
        headers=e["officer"],
        json={
            "supplier_id": e["sup"]["id"],
            "items": [{"product_id": e["sugar"]["id"], "quantity": "5", "unit_cost": "200"}],
        },
    ).json()
    wrong = client.post(
        "/api/v1/purchases",
        headers=e["officer"],
        json={
            "supplier_id": e["other"]["id"],
            "purchase_order_id": po["id"],
            "items": [{"product_id": e["sugar"]["id"], "quantity": "5", "unit_cost": "200"}],
        },
    )
    assert wrong.status_code == 422 and "different supplier" in wrong.json()["error"]["message"]


def test_purchasing_permissions(client: TestClient, env) -> None:
    e = env
    assert client.get("/api/v1/purchases", headers=e["cashier"]).status_code == 403
    assert client.get("/api/v1/purchase-orders", headers=e["cashier"]).status_code == 403


# --- Expenses ----------------------------------------------------------------------


def test_expenses_crud_and_permissions(client: TestClient, env) -> None:
    e = env
    cats = client.get("/api/v1/expense-categories", headers=e["manager"]).json()
    rent = next(c for c in cats if c["name"] == "Rent")
    body = {
        "category_id": rent["id"],
        "expense_date": str(date.today()),
        "amount": "45000",
        "description": "November shop rent",
        "payment_method": "BANK",
        "reference": "TRX-1",
    }
    r = client.post("/api/v1/expenses", headers=e["manager"], json=body)
    assert r.status_code == 201, r.text
    exp = r.json()
    page = client.get("/api/v1/expenses", headers=e["manager"]).json()
    assert page["total"] == 1 and page["total_amount"] == "45000.00"
    r = client.put(
        f"/api/v1/expenses/{exp['id']}", headers=e["manager"], json={**body, "amount": "46000"}
    )
    assert r.json()["amount"] == "46000.00"
    assert client.post("/api/v1/expenses", headers=e["officer"], json=body).status_code == 403
    assert (
        client.post(
            "/api/v1/expenses", headers=e["manager"], json={**body, "amount": "0"}
        ).status_code
        == 422
    )
    assert client.delete(f"/api/v1/expenses/{exp['id']}", headers=e["manager"]).status_code == 200


# --- The brief's scenario and profit analytics ------------------------------------


def test_receive_sell_return_and_profit_add_up(client: TestClient, env) -> None:
    """Steps 3-8 of the demonstration scenario, with every figure checked by hand."""
    e = env
    # 3-6: officer records a supplier delivery; stock and WAC update.
    client.post(
        "/api/v1/purchases",
        headers=e["officer"],
        json={
            "supplier_id": e["sup"]["id"],
            "supplier_invoice_number": "INV-900",
            "items": [{"product_id": e["sugar"]["id"], "quantity": "30", "unit_cost": "220"}],
        },
    )
    assert get_product(client, e["admin"], e["sugar"])["avg_cost"] == "215.0000"

    # 7-8: cashier sells 4 bags (4 x 245 = 980, VAT 135.17) -> stock 36.
    sale = client.post(
        "/api/v1/sales",
        headers=e["cashier"],
        json={
            "client_request_id": str(uuid.uuid4()),
            "payment_method": "CASH",
            "amount_tendered": "1000",
            "items": [{"product_id": e["sugar"]["id"], "quantity": "4"}],
        },
    ).json()
    assert sale["tax_total"] == "135.17"
    assert get_product(client, e["admin"], e["sugar"])["quantity_on_hand"] == "36.000"

    # A manager accepts 1 resaleable bag back (refund 245, VAT 33.79).
    client.post(
        f"/api/v1/sales/{sale['id']}/returns",
        headers=e["manager"],
        json={
            "items": [{"sale_item_id": sale["items"][0]["id"], "quantity": "1"}],
            "reason": "Duplicate purchase",
        },
    )
    # 1 bag torn on the shelf: written off at WAC 215.
    client.post(
        "/api/v1/stock/write-offs",
        headers=e["officer"],
        json={"product_id": e["sugar"]["id"], "quantity": "1", "kind": "DAMAGED"},
    )
    cats = client.get("/api/v1/expense-categories", headers=e["manager"]).json()
    client.post(
        "/api/v1/expenses",
        headers=e["manager"],
        json={
            "category_id": cats[0]["id"],
            "expense_date": str(date.today()),
            "amount": "100",
            "description": "Bags",
        },
    )

    today = str(date.today())
    s = client.get(
        "/api/v1/analytics/summary",
        headers=e["manager"],
        params={"date_from": today, "date_to": today},
    ).json()
    # Revenue = (980 - 135.17) - (245 - 33.79) = 844.83 - 211.21 = 633.62
    assert s["sales_gross"] == "980.00" and s["refunds_gross"] == "245.00"
    assert s["revenue"] == "633.62"
    # COGS = 4 x 215 - 1 x 215 = 645.00
    assert s["cost_of_goods_sold"] == "645.00"
    assert s["gross_profit"] == "-11.38"  # sugar sold close to cost after a price rise
    assert s["gross_margin_percent"] == "-1.80"
    assert s["stock_losses"] == "215.00"
    assert s["operating_expenses"] == "100.00"
    # Net = -11.38 - 215 + 0 - 100 = -326.38
    assert s["net_profit_estimate"] == "-326.38"
    assert s["transactions"] == 1 and s["purchases_total"] == "7656.00"

    overview = client.get(
        "/api/v1/analytics/overview",
        headers=e["manager"],
        params={"date_from": today, "date_to": today},
    ).json()
    assert overview["daily"] == [
        {
            "day": today,
            "revenue": "633.62",
            "cost_of_goods_sold": "645.00",
            "gross_profit": "-11.38",
            "transactions": 1,
        }
    ]
    [top] = overview["top_products"]
    assert top["name"] == "White Sugar 2kg" and top["quantity"] == "3.000"
    assert overview["payment_methods"] == [
        {"payment_method": "CASH", "transactions": 1, "total": "980.00"}
    ]

    assert client.get("/api/v1/analytics/summary", headers=e["officer"]).status_code == 403
    assert client.get("/api/v1/analytics/summary", headers=e["cashier"]).status_code == 403


def test_analytics_period_validation(client: TestClient, env) -> None:
    r = client.get(
        "/api/v1/analytics/summary",
        headers=env["manager"],
        params={"date_from": "2026-05-01", "date_to": "2026-04-01"},
    )
    assert r.status_code == 422


def test_price_changes_still_shown_when_delivery_reopened(client: TestClient, env) -> None:
    e = env
    grn = client.post(
        "/api/v1/purchases",
        headers=e["officer"],
        json={
            "supplier_id": e["sup"]["id"],
            "items": [{"product_id": e["sugar"]["id"], "quantity": "5", "unit_cost": "180"}],
        },
    ).json()
    again = client.get(f"/api/v1/purchases/{grn['id']}", headers=e["officer"]).json()
    assert [c["change_percent"] for c in again["price_changes"]] == ["-10.00"]
    listed = client.get("/api/v1/purchases", headers=e["officer"]).json()["items"][0]
    assert listed["price_changes"][0]["product_name"] == "White Sugar 2kg"
