"""Point of sale and returns through the API: totals, stock, permissions, idempotency."""

import threading
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import Product, StockMovement
from app.services.inventory_service import ledger_balance

D = Decimal


@pytest.fixture
def shop(client: TestClient, auth_headers):  # type: ignore[no-untyped-def]
    admin = auth_headers("super_admin", username="boss")[1]
    manager = auth_headers("store_manager", username="mgr")[1]
    cashier = auth_headers("cashier", username="till1")[1]
    cashier2 = auth_headers("cashier", username="till2")[1]

    def product(name, price, qty, cost, **kw):  # type: ignore[no-untyped-def]
        body = {"name": name, "selling_price": price, **kw}
        if qty:
            body["opening_stock"] = {"quantity": qty, "unit_cost": cost, **kw.pop("batch", {})}
        r = client.post("/api/v1/products", headers=admin, json=body)
        assert r.status_code == 201, r.text
        return r.json()

    sugar = product("White Sugar 2kg", "245", "50", "198")
    bread = product("White Bread 400g", "70", "20", "52")
    rice = product("Pishori Rice 2kg", "390", "3", "305")
    loose = product("Loose Sugar", "125", "10", "98", unit_of_measure="kg")
    return {
        "admin": admin,
        "manager": manager,
        "cashier": cashier,
        "cashier2": cashier2,
        "sugar": sugar,
        "bread": bread,
        "rice": rice,
        "loose": loose,
    }


def sale_body(items, **kw):  # type: ignore[no-untyped-def]
    body = {
        "client_request_id": str(uuid.uuid4()),
        "items": items,
        "payment_method": "CASH",
        "amount_tendered": "1000",
    }
    body.update(kw)
    return body


def qty(client, h, product):  # type: ignore[no-untyped-def]
    return client.get(f"/api/v1/products/{product['id']}", headers=h).json()["quantity_on_hand"]


def test_cash_sale_totals_change_stock_and_cogs(client: TestClient, shop) -> None:
    s = shop
    r = client.post(
        "/api/v1/sales",
        headers=s["cashier"],
        json=sale_body(
            [
                {"product_id": s["sugar"]["id"], "quantity": "2"},
                {"product_id": s["bread"]["id"], "quantity": "1"},
            ]
        ),
    )
    assert r.status_code == 201, r.text
    sale = r.json()
    assert sale["receipt_number"].startswith("RCPT-")
    assert sale["subtotal"] == "560.00" and sale["grand_total"] == "560.00"
    assert sale["tax_total"] == "77.25"  # 67.59 + 9.66 (hand-computed, see unit tests)
    assert sale["amount_tendered"] == "1000.00" and sale["change_given"] == "440.00"
    assert [i["product_name"] for i in sale["items"]] == ["White Sugar 2kg", "White Bread 400g"]
    assert sale["cost_total"] is None  # cashier cannot see cost
    assert all(i["unit_cost"] is None for i in sale["items"])

    assert qty(client, s["admin"], s["sugar"]) == "48.000"
    assert qty(client, s["admin"], s["bread"]) == "19.000"

    full = client.get(f"/api/v1/sales/{sale['id']}", headers=s["manager"]).json()
    assert full["cost_total"] == "448.00"  # 2 x 198 + 1 x 52
    # (560 - 77.25) - 448 = 34.75
    assert full["gross_profit"] == "34.75"


def test_mpesa_requires_valid_code_and_card_works(client: TestClient, shop) -> None:
    s = shop
    item = [{"product_id": s["bread"]["id"], "quantity": "1"}]
    bad = client.post(
        "/api/v1/sales",
        headers=s["cashier"],
        json=sale_body(item, payment_method="MPESA", amount_tendered=None),
    )
    assert bad.status_code == 422 and "M-Pesa" in bad.text
    ok = client.post(
        "/api/v1/sales",
        headers=s["cashier"],
        json=sale_body(
            item, payment_method="MPESA", amount_tendered=None, payment_reference="skd4h2l9qx"
        ),
    )
    assert ok.status_code == 201 and ok.json()["payment_reference"] == "SKD4H2L9QX"
    card = client.post(
        "/api/v1/sales",
        headers=s["cashier"],
        json=sale_body(item, payment_method="CARD", amount_tendered=None),
    )
    assert card.status_code == 201 and card.json()["change_given"] is None


def test_insufficient_cash_and_stock_rejected_atomically(client: TestClient, shop, db) -> None:
    s = shop
    r = client.post(
        "/api/v1/sales",
        headers=s["cashier"],
        json=sale_body([{"product_id": s["sugar"]["id"], "quantity": "2"}], amount_tendered="400"),
    )
    assert r.status_code == 422 and "at least KES 490.00" in r.json()["error"]["message"]

    # Sugar line is fine, rice line asks for 5 of 3: nothing at all may be recorded.
    r = client.post(
        "/api/v1/sales",
        headers=s["cashier"],
        json=sale_body(
            [
                {"product_id": s["sugar"]["id"], "quantity": "2"},
                {"product_id": s["rice"]["id"], "quantity": "5"},
            ],
            amount_tendered="5000",
        ),
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "INSUFFICIENT_STOCK"
    assert qty(client, s["admin"], s["sugar"]) == "50.000"
    assert db.scalar(select(StockMovement).where(StockMovement.movement_type == "SALE_OUT")) is None
    assert client.get("/api/v1/sales", headers=s["manager"]).json()["total"] == 0


def test_weighed_goods_and_unit_rules(client: TestClient, shop) -> None:
    s = shop
    r = client.post(
        "/api/v1/sales",
        headers=s["cashier"],
        json=sale_body([{"product_id": s["loose"]["id"], "quantity": "1.25"}]),
    )
    assert r.status_code == 201 and r.json()["grand_total"] == "156.25"
    assert qty(client, s["admin"], s["loose"]) == "8.750"
    r = client.post(
        "/api/v1/sales",
        headers=s["cashier"],
        json=sale_body([{"product_id": s["bread"]["id"], "quantity": "1.5"}]),
    )
    assert r.status_code == 422 and "whole" in r.json()["error"]["message"]


def test_discount_limit_for_cashiers(client: TestClient, shop) -> None:
    s = shop
    item = [{"product_id": s["sugar"]["id"], "quantity": "2"}]  # 490
    ok = client.post(
        "/api/v1/sales", headers=s["cashier"], json=sale_body(item, cart_discount="49")
    )
    assert ok.status_code == 201 and ok.json()["grand_total"] == "441.00"  # exactly 10%
    too_much = client.post(
        "/api/v1/sales", headers=s["cashier"], json=sale_body(item, cart_discount="60")
    )
    assert too_much.status_code == 403 and too_much.json()["error"]["code"] == "DISCOUNT_LIMIT"
    manager = client.post(
        "/api/v1/sales", headers=s["manager"], json=sale_body(item, cart_discount="60")
    )
    assert manager.status_code == 201
    logs = client.get(
        "/api/v1/audit-logs", headers=s["admin"], params={"action": "sale.discount_override"}
    ).json()
    assert logs["total"] == 1


def test_retried_request_does_not_double_sell(client: TestClient, shop) -> None:
    s = shop
    body = sale_body([{"product_id": s["sugar"]["id"], "quantity": "1"}])
    first = client.post("/api/v1/sales", headers=s["cashier"], json=body)
    again = client.post("/api/v1/sales", headers=s["cashier"], json=body)
    assert first.status_code == 201 and again.status_code == 200
    assert first.json()["receipt_number"] == again.json()["receipt_number"]
    assert qty(client, s["admin"], s["sugar"]) == "49.000"


def test_cashiers_only_see_their_own_sales(client: TestClient, shop) -> None:
    s = shop
    mine = client.post(
        "/api/v1/sales",
        headers=s["cashier"],
        json=sale_body([{"product_id": s["bread"]["id"], "quantity": "1"}]),
    ).json()
    client.post(
        "/api/v1/sales",
        headers=s["cashier2"],
        json=sale_body([{"product_id": s["bread"]["id"], "quantity": "2"}]),
    )
    own = client.get("/api/v1/sales", headers=s["cashier"]).json()
    assert [x["receipt_number"] for x in own["items"]] == [mine["receipt_number"]]
    assert client.get("/api/v1/sales", headers=s["manager"]).json()["total"] == 2
    other = client.get("/api/v1/sales", headers=s["cashier2"]).json()["items"][0]
    assert client.get(f"/api/v1/sales/{other['id']}", headers=s["cashier"]).status_code == 404

    summary = client.get("/api/v1/sales/summary", headers=s["cashier"]).json()
    assert summary["count"] == 1 and summary["gross_total"] == "70.00"
    assert (
        client.get("/api/v1/sales/summary", headers=s["manager"]).json()["gross_total"] == "210.00"
    )


def test_inventory_officer_cannot_sell(client: TestClient, shop, auth_headers) -> None:
    _, officer = auth_headers("inventory_officer")
    r = client.post(
        "/api/v1/sales",
        headers=officer,
        json=sale_body([{"product_id": shop["bread"]["id"], "quantity": "1"}]),
    )
    assert r.status_code == 403


def test_concurrent_tills_cannot_oversell(client: TestClient, shop, db) -> None:
    """Rice has 3 in stock; two tills each try to sell 2 at the same moment."""
    s = shop
    barrier = threading.Barrier(2)
    codes: list[int] = []

    def sell(headers) -> None:  # type: ignore[no-untyped-def]
        barrier.wait()
        r = client.post(
            "/api/v1/sales",
            headers=headers,
            json=sale_body([{"product_id": s["rice"]["id"], "quantity": "2"}]),
        )
        codes.append(r.status_code)

    threads = [threading.Thread(target=sell, args=(h,)) for h in (s["cashier"], s["cashier2"])]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(codes) == [201, 409]
    rice = db.get(Product, s["rice"]["id"])
    db.refresh(rice)
    assert rice.quantity_on_hand == D("1.000") == ledger_balance(db, rice.id)


# --- Returns ---------------------------------------------------------------------


def make_sale(client, shop, headers=None, **kw):  # type: ignore[no-untyped-def]
    r = client.post(
        "/api/v1/sales",
        headers=headers or shop["cashier"],
        json=sale_body(
            [
                {"product_id": shop["sugar"]["id"], "quantity": "3"},
                {"product_id": shop["bread"]["id"], "quantity": "2"},
            ],
            cart_discount="20",
            **kw,
        ),
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_cashier_return_waits_for_manager_then_restocks(client: TestClient, shop) -> None:
    s = shop
    sale = make_sale(client, s)
    sugar_line = sale["items"][0]
    r = client.post(
        f"/api/v1/sales/{sale['id']}/returns",
        headers=s["cashier"],
        json={
            "items": [{"sale_item_id": sugar_line["id"], "quantity": "1"}],
            "reason": "Customer bought the wrong size",
            "refund_method": "CASH",
        },
    )
    assert r.status_code == 201, r.text
    ret = r.json()
    assert ret["status"] == "PENDING" and ret["return_number"].startswith("RTN-")
    # Refund is the discounted line price: line total / 3
    expected = (D(sugar_line["line_total"]) / 3).quantize(D("0.01"))
    assert D(ret["refund_total"]) == expected
    assert qty(client, s["admin"], s["sugar"]) == "47.000"  # not restocked yet

    assert (
        client.post(
            f"/api/v1/returns/{ret['id']}/approve", headers=s["cashier"], json={}
        ).status_code
        == 403
    )
    r = client.post(f"/api/v1/returns/{ret['id']}/approve", headers=s["manager"], json={})
    assert r.status_code == 200 and r.json()["status"] == "APPROVED"
    assert qty(client, s["admin"], s["sugar"]) == "48.000"
    sale_now = client.get(f"/api/v1/sales/{sale['id']}", headers=s["manager"]).json()
    assert sale_now["status"] == "PARTIALLY_RETURNED"
    assert sale_now["items"][0]["returned_quantity"] == "1.000"


def test_cannot_return_more_than_sold_including_pending(client: TestClient, shop) -> None:
    s = shop
    sale = make_sale(client, s)
    line = sale["items"][1]  # 2 loaves
    first = client.post(
        f"/api/v1/sales/{sale['id']}/returns",
        headers=s["cashier"],
        json={"items": [{"sale_item_id": line["id"], "quantity": "2"}], "reason": "Stale bread"},
    )
    assert first.status_code == 201
    again = client.post(
        f"/api/v1/sales/{sale['id']}/returns",
        headers=s["cashier"],
        json={"items": [{"sale_item_id": line["id"], "quantity": "1"}], "reason": "Stale bread"},
    )
    assert again.status_code == 422 and "can still be returned" in again.json()["error"]["message"]


def test_damaged_return_refunds_but_does_not_restock(client: TestClient, shop) -> None:
    s = shop
    sale = make_sale(client, s)
    r = client.post(
        f"/api/v1/sales/{sale['id']}/returns",
        headers=s["manager"],
        json={
            "items": [
                {"sale_item_id": sale["items"][1]["id"], "quantity": "2", "condition": "DAMAGED"}
            ],
            "reason": "Mouldy",
            "refund_method": "MPESA",
        },
    )
    assert r.status_code == 201 and r.json()["status"] == "APPROVED"  # manager: immediate
    assert r.json()["refund_total"] == sale["items"][1]["line_total"]  # whole line back
    assert qty(client, s["admin"], s["bread"]) == "18.000"
    sale_now = client.get(f"/api/v1/sales/{sale['id']}", headers=s["manager"]).json()
    assert sale_now["status"] == "PARTIALLY_RETURNED"


def test_return_into_original_expiry_batch(client: TestClient, shop) -> None:
    s = shop
    milk = client.post(
        "/api/v1/products",
        headers=s["admin"],
        json={
            "name": "Fresh Milk 500ml",
            "selling_price": "65",
            "tracks_expiry": True,
            "opening_stock": {
                "quantity": "10",
                "unit_cost": "48",
                "expiry_date": "2099-01-10",
                "batch_number": "M1",
            },
        },
    ).json()
    sale = client.post(
        "/api/v1/sales",
        headers=s["cashier"],
        json=sale_body([{"product_id": milk["id"], "quantity": "2"}]),
    ).json()
    r = client.post(
        f"/api/v1/sales/{sale['id']}/returns",
        headers=s["manager"],
        json={
            "items": [{"sale_item_id": sale["items"][0]["id"], "quantity": "1"}],
            "reason": "Changed mind",
        },
    )
    assert r.status_code == 201, r.text
    [batch] = client.get(f"/api/v1/products/{milk['id']}/batches", headers=s["admin"]).json()
    assert batch["batch_number"] == "M1" and batch["quantity_remaining"] == "9.000"


def test_reject_return_needs_reason(client: TestClient, shop) -> None:
    s = shop
    sale = make_sale(client, s)
    ret = client.post(
        f"/api/v1/sales/{sale['id']}/returns",
        headers=s["cashier"],
        json={
            "items": [{"sale_item_id": sale["items"][0]["id"], "quantity": "1"}],
            "reason": "Not wanted",
        },
    ).json()
    assert (
        client.post(
            f"/api/v1/returns/{ret['id']}/reject", headers=s["manager"], json={}
        ).status_code
        == 422
    )
    r = client.post(
        f"/api/v1/returns/{ret['id']}/reject", headers=s["manager"], json={"note": "Opened packet"}
    )
    assert r.json()["status"] == "REJECTED"
    assert qty(client, s["admin"], s["sugar"]) == "47.000"


def test_find_sale_by_receipt_number(client: TestClient, shop) -> None:
    s = shop
    sale = make_sale(client, s)
    r = client.get(
        f"/api/v1/sales/by-receipt/{sale['receipt_number'].lower()}", headers=s["cashier"]
    )
    assert r.status_code == 200 and r.json()["id"] == sale["id"]
    other = make_sale(client, s, headers=s["cashier2"])
    assert (
        client.get(
            f"/api/v1/sales/by-receipt/{other['receipt_number']}", headers=s["cashier"]
        ).status_code
        == 404
    )


def test_store_info_for_receipts(client: TestClient, shop) -> None:
    info = client.get("/api/v1/store", headers=shop["cashier"]).json()
    assert info["currency"] == "KES" and info["max_cashier_discount_percent"] == "10"
