"""Stock adjustments (approval workflow), write-offs, ledger listing and summary."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

ADJ = "/api/v1/stock/adjustments"


@pytest.fixture
def setup(client: TestClient, auth_headers):  # type: ignore[no-untyped-def]
    admin = auth_headers("super_admin", username="boss")[1]
    manager = auth_headers("store_manager", username="mgr")[1]
    officer = auth_headers("inventory_officer", username="officer")[1]
    cashier = auth_headers("cashier", username="till")[1]
    oil = client.post(
        "/api/v1/products",
        headers=admin,
        json={
            "name": "Vegetable Cooking Oil 1L",
            "selling_price": "350",
            "min_stock_level": "5",
            "opening_stock": {"quantity": "40", "unit_cost": "280"},
        },
    ).json()
    return {"admin": admin, "manager": manager, "officer": officer, "cashier": cashier, "oil": oil}


def qty(client: TestClient, h, product_id: int) -> str:  # type: ignore[no-untyped-def]
    return client.get(f"/api/v1/products/{product_id}", headers=h).json()["quantity_on_hand"]


def test_small_count_correction_applies_immediately(client: TestClient, setup) -> None:
    s = setup
    r = client.post(
        ADJ,
        headers=s["officer"],
        json={
            "product_id": s["oil"]["id"],
            "counted_quantity": "38",
            "reason_code": "COUNT_CORRECTION",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["applied"] is True and body["adjustment"]["quantity_change"] == "-2.000"
    assert body["adjustment"]["value_impact"] == "560.00"
    assert "reduced by 2 pcs" in body["message"]
    assert qty(client, s["admin"], s["oil"]["id"]) == "38.000"
    [m] = client.get(
        "/api/v1/stock/movements", headers=s["admin"], params={"movement_type": "ADJUSTMENT_OUT"}
    ).json()["items"]
    assert m["reference_type"] == "stock_adjustment" and m["user"]["username"] == "officer"


def test_large_adjustment_waits_for_manager(client: TestClient, setup) -> None:
    s = setup
    # 20 x 280 = KES 5,600 > 5,000 threshold
    r = client.post(
        ADJ,
        headers=s["officer"],
        json={
            "product_id": s["oil"]["id"],
            "quantity_change": "-20",
            "reason_code": "THEFT_SUSPECTED",
            "notes": "Carton missing after delivery",
        },
    )
    body = r.json()
    assert body["applied"] is False and body["adjustment"]["status"] == "PENDING"
    assert qty(client, s["admin"], s["oil"]["id"]) == "40.000"
    assert (
        client.get("/api/v1/stock/summary", headers=s["manager"]).json()["pending_adjustments"] == 1
    )

    adj_id = body["adjustment"]["id"]
    assert client.post(f"{ADJ}/{adj_id}/approve", headers=s["officer"], json={}).status_code == 403
    r = client.post(f"{ADJ}/{adj_id}/approve", headers=s["manager"], json={"note": "CCTV checked"})
    assert r.status_code == 200 and r.json()["status"] == "APPROVED"
    assert r.json()["decided_by"]["username"] == "mgr"
    assert qty(client, s["admin"], s["oil"]["id"]) == "20.000"
    again = client.post(f"{ADJ}/{adj_id}/approve", headers=s["manager"], json={})
    assert again.status_code == 422


def test_manager_large_adjustment_applies_without_waiting(client: TestClient, setup) -> None:
    s = setup
    r = client.post(
        ADJ,
        headers=s["manager"],
        json={
            "product_id": s["oil"]["id"],
            "quantity_change": "30",
            "reason_code": "FOUND_STOCK",
        },
    )
    assert r.json()["applied"] is True
    assert qty(client, s["admin"], s["oil"]["id"]) == "70.000"


def test_reject_needs_reason_and_leaves_stock(client: TestClient, setup) -> None:
    s = setup
    adj = client.post(
        ADJ,
        headers=s["officer"],
        json={
            "product_id": s["oil"]["id"],
            "quantity_change": "-25",
            "reason_code": "DATA_ENTRY_ERROR",
        },
    ).json()["adjustment"]
    assert (
        client.post(f"{ADJ}/{adj['id']}/reject", headers=s["manager"], json={}).status_code == 422
    )
    r = client.post(
        f"{ADJ}/{adj['id']}/reject", headers=s["manager"], json={"note": "Recount first"}
    )
    assert r.json()["status"] == "REJECTED"
    assert qty(client, s["admin"], s["oil"]["id"]) == "40.000"


def test_self_approval_is_refused(client: TestClient, setup, auth_headers, db) -> None:
    """A user who could approve but whose request is pending cannot approve it themselves."""
    from app.models import StockAdjustment, User

    s = setup
    adj = client.post(
        ADJ,
        headers=s["officer"],
        json={
            "product_id": s["oil"]["id"],
            "quantity_change": "-25",
            "reason_code": "OTHER",
            "notes": "test",
        },
    ).json()["adjustment"]
    # Pretend the manager made the request.
    row = db.get(StockAdjustment, adj["id"])
    row.requested_by_id = db.query(User).filter_by(username="mgr").one().id
    db.commit()
    r = client.post(f"{ADJ}/{adj['id']}/approve", headers=s["manager"], json={})
    assert r.status_code == 403 and "Someone else" in r.json()["error"]["message"]


def test_negative_stock_needs_super_admin(client: TestClient, setup) -> None:
    s = setup
    body = {
        "product_id": s["oil"]["id"],
        "quantity_change": "-45",
        "reason_code": "OTHER",
        "notes": "Sold before goods were recorded",
    }
    r = client.post(ADJ, headers=s["manager"], json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "NEGATIVE_STOCK"
    r = client.post(ADJ, headers=s["manager"], json={**body, "allow_negative": True})
    assert r.status_code == 403
    r = client.post(ADJ, headers=s["admin"], json={**body, "allow_negative": True})
    assert r.status_code == 201 and qty(client, s["admin"], s["oil"]["id"]) == "-5.000"


def test_adjustment_validation(client: TestClient, setup) -> None:
    s = setup
    pid = s["oil"]["id"]
    for bad in (
        {"product_id": pid, "reason_code": "OTHER", "notes": "x"},  # neither mode
        {
            "product_id": pid,
            "counted_quantity": "3",
            "quantity_change": "1",
            "reason_code": "COUNT_CORRECTION",
        },
        {"product_id": pid, "quantity_change": "-1", "reason_code": "OTHER"},  # needs note
        {"product_id": pid, "quantity_change": "1.5", "reason_code": "FOUND_STOCK"},  # whole pcs
    ):
        assert client.post(ADJ, headers=s["officer"], json=bad).status_code == 422, bad
    same = client.post(
        ADJ,
        headers=s["officer"],
        json={"product_id": pid, "counted_quantity": "40", "reason_code": "COUNT_CORRECTION"},
    )
    assert same.status_code == 422 and "nothing to adjust" in same.json()["error"]["message"]
    assert (
        client.post(
            ADJ,
            headers=s["cashier"],
            json={"product_id": pid, "quantity_change": "1", "reason_code": "FOUND_STOCK"},
        ).status_code
        == 403
    )


def test_write_offs_fefo_and_expiry_rule(client: TestClient, setup) -> None:
    s = setup
    today = date.today()
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
                "expiry_date": str(today + timedelta(days=5)),
                "batch_number": "M-NEW",
            },
        },
    ).json()
    # Older stock that has already expired.
    client.post(
        ADJ,
        headers=s["admin"],
        json={
            "product_id": milk["id"],
            "quantity_change": "4",
            "reason_code": "FOUND_STOCK",
            "expiry_date": str(today - timedelta(days=1)),
        },
    )
    batches = client.get(f"/api/v1/products/{milk['id']}/batches", headers=s["officer"]).json()
    expired = next(b for b in batches if b["days_to_expiry"] < 0)
    fresh = next(b for b in batches if b["batch_number"] == "M-NEW")

    r = client.post(
        "/api/v1/stock/write-offs",
        headers=s["officer"],
        json={
            "product_id": milk["id"],
            "quantity": "2",
            "kind": "EXPIRED",
            "batch_id": fresh["id"],
        },
    )
    assert r.status_code == 422 and "damaged" in r.json()["error"]["message"]

    r = client.post(
        "/api/v1/stock/write-offs",
        headers=s["officer"],
        json={
            "product_id": milk["id"],
            "quantity": "4",
            "kind": "EXPIRED",
            "batch_id": expired["id"],
        },
    )
    assert r.status_code == 201 and r.json()["value_lost"] == "192.00"

    # Damaged without a batch: FEFO picks the remaining batch.
    r = client.post(
        "/api/v1/stock/write-offs",
        headers=s["officer"],
        json={"product_id": milk["id"], "quantity": "1", "kind": "DAMAGED", "notes": "Torn packet"},
    )
    body = r.json()
    assert body["quantity_on_hand"] == "9.000"
    assert body["movements"][0]["batch_number"] == "M-NEW"
    assert body["movements"][0]["reason"] == "Damaged goods: Torn packet"

    assert (
        client.post(
            "/api/v1/stock/write-offs",
            headers=s["cashier"],
            json={"product_id": milk["id"], "quantity": "1", "kind": "DAMAGED"},
        ).status_code
        == 403
    )


def test_movement_history_filters_and_hides_cost(client: TestClient, setup) -> None:
    s = setup
    client.post(
        "/api/v1/stock/write-offs",
        headers=s["admin"],
        json={"product_id": s["oil"]["id"], "quantity": "1", "kind": "DAMAGED"},
    )
    page = client.get(
        "/api/v1/stock/movements", headers=s["manager"], params={"movement_type": "OPENING,DAMAGED"}
    ).json()
    assert [m["movement_type"] for m in page["items"]] == ["DAMAGED", "OPENING"]
    assert page["items"][0]["value"] == "-280.00"
    today = str(date.today())
    assert (
        client.get(
            "/api/v1/stock/movements",
            headers=s["manager"],
            params={"date_from": today, "date_to": today},
        ).json()["total"]
        == 2
    )
    assert client.get("/api/v1/stock/movements", headers=s["cashier"]).status_code == 403


def test_summary(client: TestClient, setup) -> None:
    s = setup
    client.post(
        "/api/v1/products",
        headers=s["admin"],
        json={"name": "Bar Soap 800g", "selling_price": "180"},
    )
    summary = client.get("/api/v1/stock/summary", headers=s["manager"]).json()
    assert summary["active_products"] == 2
    assert summary["out_of_stock"] == 1
    assert summary["inventory_value"] == "11200.00"  # 40 x 280
    officer_view = client.get("/api/v1/stock/summary", headers=s["officer"]).json()
    assert officer_view["inventory_value"] == "11200.00"  # officers may view cost
