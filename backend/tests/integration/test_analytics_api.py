"""Forecasts, reorder suggestions, anomaly alerts and notifications through the API."""

import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Notification, User
from app.schemas.sales import CartLine, CheckoutRequest
from app.schemas.stock import AdjustmentCreate
from app.services import sales_service, stock_service
from app.services.audit_service import RequestContext
from app.services.forecast_service import today
from app.workers.runner import Worker

D = Decimal
CTX = RequestContext(ip_address="127.0.0.1", user_agent="test")
TZ = ZoneInfo("Africa/Nairobi")


def at(d: date, hour: int = 12) -> datetime:
    return datetime.combine(d, time(hour), TZ)


def run_jobs() -> None:
    worker = Worker()
    while worker.run_once():
        pass


@pytest.fixture
def shop(client: TestClient, auth_headers, catalog, db: Session):  # type: ignore[no-untyped-def]
    """Two products with 10 weeks of sales: sugar busy at weekends, rice steady."""
    admin = auth_headers("super_admin", username="boss")[1]
    manager_user, manager = auth_headers("store_manager", username="mgr")
    officer_user, officer = auth_headers("inventory_officer", username="officer")
    cashier_user, cashier = auth_headers("cashier", username="till")
    sup = client.post(
        "/api/v1/suppliers",
        headers=admin,
        json={"name": "Demo Wholesalers", "kra_pin": "P051111111A"},
    ).json()
    sugar = catalog.product(
        "White Sugar 2kg",
        min_stock_level=D(20),
        max_stock_level=D(200),
        default_supplier_id=sup["id"],
        purchase_price=D(200),
        avg_cost=D(200),
    )
    rice = catalog.product(
        "Pishori Rice 2kg",
        min_stock_level=D(5),
        max_stock_level=D(80),
        default_supplier_id=sup["id"],
        purchase_price=D(300),
        avg_cost=D(300),
    )
    catalog.receive(sugar, 2000, 200)
    catalog.receive(rice, 1000, 300)
    till = db.get(User, cashier_user.id)
    end = today()
    for k in range(70, 0, -1):
        d = end - timedelta(days=k)
        weekend = d.weekday() >= 5
        wobble = (k * 7) % 5 - 2  # deterministic day-to-day variation of -2..+2
        for product, qty in ((sugar, (18 if weekend else 9) + wobble), (rice, 4 + wobble // 2)):
            sales_service.checkout(
                db,
                CheckoutRequest(
                    client_request_id=uuid.uuid4(),
                    items=[CartLine(product_id=product.id, quantity=D(qty))],
                    payment_method="CASH",
                    amount_tendered=D("100000"),
                ),
                till,
                CTX,
                sold_at=at(d),
            )
    return {
        "admin": admin,
        "manager": manager,
        "officer": officer,
        "cashier": cashier,
        "sugar": sugar,
        "rice": rice,
        "sup": sup,
        "till": till,
        "officer_user": officer_user,
        "manager_user": manager_user,
    }


def _uid(u: User) -> int:
    return u.id


def test_forecast_run_and_reorder(client: TestClient, shop, db: Session) -> None:  # type: ignore[no-untyped-def]
    h = shop["officer"]
    assert client.get("/api/v1/forecasts", headers=h).json() == {
        "run": None,
        "running": False,
        "products": [],
    }
    # Sugar: leave only a few days of stock.
    sugar = shop["sugar"]
    db.refresh(sugar)
    stock_service.create_adjustment(
        db,
        AdjustmentCreate(
            product_id=sugar.id, counted_quantity=D(30), reason_code="COUNT_CORRECTION"
        ),
        db.get(User, _uid(shop["manager_user"])),
        CTX,
    )
    r = client.post("/api/v1/forecasts/run", headers=h)
    assert r.status_code == 202
    assert client.get("/api/v1/forecasts", headers=h).json()["running"] is True
    run_jobs()

    data = client.get("/api/v1/forecasts", headers=h).json()
    assert data["run"]["status"] == "SUCCEEDED" and not data["running"]
    rows = {p["product"]["name"]: p for p in data["products"]}
    s, rice = rows["White Sugar 2kg"], rows["Pishori Rice 2kg"]
    # About 9 a weekday and 18 at weekends -> about 11.6 a day, 81 a week.
    assert 60 < s["next_7_days"] < 100
    assert 20 < rice["next_7_days"] < 36
    assert s["model_label"] and s["chosen_mase"] is not None
    assert s["stockout_date"] is not None and s["should_order"]
    assert D(s["suggested_quantity"]) > 0
    assert not rice["should_order"]  # 1000 - 280 sold: plenty left
    assert data["run"]["summary"]["products"] == 2

    detail = client.get(f"/api/v1/forecasts/products/{sugar.id}", headers=h).json()
    actual = [p for p in detail["series"] if p["actual"] is not None and p["forecast"] is None]
    future = [p for p in detail["series"] if p["forecast"] is not None]
    assert detail["forecast"]["next_7_days"] == pytest.approx(
        sum(p["forecast"] for p in future[:7]), abs=0.1
    )
    assert len(actual) == 91 and len(future) == 28
    assert all(p["lower"] <= p["forecast"] <= p["upper"] for p in future)
    # The weekly shape is learnt: weekend days forecast higher than weekdays.
    by_day = {date.fromisoformat(p["date"]).weekday(): p["forecast"] for p in future[:7]}
    assert min(by_day[5], by_day[6]) > max(by_day[d] for d in range(5))
    assert {sc["model"] for sc in detail["scores"]} >= {"seasonal_naive", "holt_winters"}

    groups = client.get("/api/v1/forecasts/reorder", headers=h).json()
    assert len(groups) == 1 and groups[0]["supplier_name"] == "Demo Wholesalers"
    assert [line["product"]["name"] for line in groups[0]["lines"]] == ["White Sugar 2kg"]
    assert D(groups[0]["total_value"]) == D(groups[0]["lines"][0]["suggested_quantity"]) * 200

    # A predicted shortage reaches those who order stock.
    titles = [n["title"] for n in client.get("/api/v1/notifications", headers=h).json()["items"]]
    assert any("White Sugar 2kg is likely to run out" in t for t in titles)


def test_forecast_permissions(client: TestClient, shop) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/api/v1/forecasts", headers=shop["cashier"]).status_code == 403
    assert client.post("/api/v1/forecasts/run", headers=shop["cashier"]).status_code == 403
    assert client.get("/api/v1/forecasts/reorder", headers=shop["cashier"]).status_code == 403
    r = client.get(f"/api/v1/forecasts/products/{shop['rice'].id}", headers=shop["officer"])
    assert r.status_code == 404  # nothing run yet


def test_anomaly_scan_review_and_privacy(client: TestClient, shop, db: Session) -> None:  # type: ignore[no-untyped-def]
    officer = db.get(User, _uid(shop["officer_user"]))
    rice = shop["rice"]
    end = today()
    # Normal: an occasional one-unit correction. Then 9 one-unit corrections in one day.
    for k in (60, 45, 30, 15):
        stock_service.create_adjustment(
            db,
            AdjustmentCreate(
                product_id=rice.id, quantity_change=D(-1), reason_code="COUNT_CORRECTION"
            ),
            officer,
            CTX,
            at=at(end - timedelta(days=k), 18),
        )
    burst_day = end - timedelta(days=2)
    for i in range(9):
        stock_service.create_adjustment(
            db,
            AdjustmentCreate(
                product_id=rice.id, quantity_change=D(-1), reason_code="COUNT_CORRECTION"
            ),
            officer,
            CTX,
            at=at(burst_day, 18) + timedelta(minutes=i),
        )
    mh = shop["manager"]
    assert client.post("/api/v1/anomalies/scan", headers=shop["officer"]).status_code == 403
    assert client.post("/api/v1/anomalies/scan", headers=mh).status_code == 202
    run_jobs()

    alerts = client.get("/api/v1/anomalies?status=OPEN_ALL", headers=mh).json()["items"]
    product_alert = next(a for a in alerts if a["entity_type"] == "product")
    assert product_alert["product"]["name"] == "Pishori Rice 2kg"
    assert product_alert["period_start"] == burst_day.isoformat()
    assert "9" in product_alert["explanation"] and product_alert["recommended_action"]
    user_alert = next(a for a in alerts if a["entity_type"] == "user")
    assert user_alert["subject_user"]["username"] == "officer"
    assert user_alert["kind"] == "FREQUENT_ADJUSTMENTS"
    assert "theft" not in (user_alert["explanation"] + user_alert["recommended_action"]).lower()

    # Scanning again does not duplicate.
    client.post("/api/v1/anomalies/scan", headers=mh)
    run_jobs()
    assert client.get("/api/v1/anomalies", headers=mh).json()["total"] == len(alerts)

    # Officers and cashiers cannot see alerts (no anomalies permission).
    assert client.get("/api/v1/anomalies", headers=shop["officer"]).status_code == 403
    assert client.get("/api/v1/anomalies", headers=shop["cashier"]).status_code == 403

    # Review: resolving needs a note; the outcome feeds the real-world precision.
    url = f"/api/v1/anomalies/{product_alert['id']}/review"
    r = client.post(url, headers=mh, json={"status": "RESOLVED_ISSUE_FOUND"})
    assert r.status_code == 422
    r = client.post(
        url,
        headers=mh,
        json={"status": "RESOLVED_ISSUE_FOUND", "notes": "Count confirmed 9 bags missing"},
    )
    assert r.status_code == 200 and r.json()["reviewed_by"]["username"] == "mgr"
    client.post(
        f"/api/v1/anomalies/{user_alert['id']}/review",
        headers=mh,
        json={"status": "RESOLVED_NO_ISSUE", "notes": "Shelf reorganisation"},
    )
    stats = client.get("/api/v1/anomalies/stats", headers=mh).json()
    assert stats["reviewed"] == 2 and stats["precision"] == 0.5

    # Managers are notified of medium/high alerts; alerts about people only to reviewers.
    mine = client.get("/api/v1/notifications", headers=mh).json()["items"]
    assert any(n["type"] == "ANOMALY" for n in mine)


def test_nobody_reviews_their_own_alert(client: TestClient, shop, db: Session) -> None:  # type: ignore[no-untyped-def]
    manager = db.get(User, _uid(shop["manager_user"]))
    rice = shop["rice"]
    end = today()
    for i in range(8):
        stock_service.create_adjustment(
            db,
            AdjustmentCreate(
                product_id=rice.id, quantity_change=D(-1), reason_code="COUNT_CORRECTION"
            ),
            manager,
            CTX,
            at=at(end - timedelta(days=1), 18) + timedelta(minutes=i),
        )
    client.post("/api/v1/anomalies/scan", headers=shop["admin"])
    run_jobs()
    alerts = client.get("/api/v1/anomalies", headers=shop["manager"]).json()["items"]
    own = next(a for a in alerts if a["entity_type"] == "user")
    assert own["subject_user"]["username"] == "mgr"
    r = client.post(
        f"/api/v1/anomalies/{own['id']}/review",
        headers=shop["manager"],
        json={"status": "RESOLVED_NO_ISSUE", "notes": "fine"},
    )
    assert r.status_code == 403
    r = client.post(
        f"/api/v1/anomalies/{own['id']}/review",
        headers=shop["admin"],
        json={"status": "INVESTIGATING"},
    )
    assert r.status_code == 200


def test_low_stock_notification_in_real_time(client: TestClient, shop, db: Session) -> None:  # type: ignore[no-untyped-def]
    h = shop["officer"]
    rice = shop["rice"]
    db.refresh(rice)
    stock_service.create_adjustment(
        db,
        AdjustmentCreate(product_id=rice.id, counted_quantity=D(7), reason_code="COUNT_CORRECTION"),
        db.get(User, _uid(shop["manager_user"])),
        CTX,
    )
    assert client.get("/api/v1/notifications/unread-count", headers=h).json()["unread"] == 0
    sell = {
        "client_request_id": str(uuid.uuid4()),
        "payment_method": "CASH",
        "amount_tendered": "5000",
        "items": [{"product_id": rice.id, "quantity": "3"}],
    }
    assert client.post("/api/v1/sales", headers=shop["cashier"], json=sell).status_code == 201
    page = client.get("/api/v1/notifications", headers=h).json()
    assert page["unread"] == 1
    n = page["items"][0]
    assert n["type"] == "LOW_STOCK" and "Pishori Rice 2kg" in n["title"]
    assert n["link"] == f"/products/{rice.id}"
    # Selling again below the line does not repeat it; running out is a separate alert.
    sell["client_request_id"] = str(uuid.uuid4())
    sell["items"][0]["quantity"] = "4"
    client.post("/api/v1/sales", headers=shop["cashier"], json=sell)
    types = [x["type"] for x in client.get("/api/v1/notifications", headers=h).json()["items"]]
    assert types.count("LOW_STOCK") == 1 and types.count("OUT_OF_STOCK") == 1
    # The cashier (cannot order stock) gets nothing.
    assert client.get("/api/v1/notifications", headers=shop["cashier"]).json()["total"] == 0

    assert client.post("/api/v1/notifications/read", headers=h, json={"ids": [n["id"]]}).json() == {
        "updated": 1
    }
    assert client.get("/api/v1/notifications/unread-count", headers=h).json()["unread"] == 1
    client.post("/api/v1/notifications/read", headers=h, json={})
    assert client.get("/api/v1/notifications?unread=true", headers=h).json()["total"] == 0
    # Marking someone else's notification ids does nothing.
    other = db.scalars(
        select(Notification).where(Notification.user_id != _uid(shop["officer_user"]))
    ).first()
    if other is not None:
        r = client.post("/api/v1/notifications/read", headers=h, json={"ids": [other.id]})
        assert r.json() == {"updated": 0}


def test_sweep_expiry_and_pending_approvals(client: TestClient, shop, catalog, db: Session) -> None:  # type: ignore[no-untyped-def]
    milk = catalog.product(
        "Fresh Milk 500ml", tracks_expiry=True, purchase_price=D(50), avg_cost=D(50)
    )
    catalog.receive(milk, 24, 50, expiry=today() + timedelta(days=2), batch="L1")
    from app.services import job_service

    job_service.enqueue(db, "notifications.sweep")
    db.commit()
    run_jobs()
    items = client.get("/api/v1/notifications", headers=shop["officer"]).json()["items"]
    exp = next(n for n in items if n["type"] == "EXPIRY")
    assert "Fresh Milk 500ml" in exp["title"] and exp["severity"] == "critical"
    # Running the sweep again the same day does not repeat it.
    job_service.enqueue(db, "notifications.sweep")
    db.commit()
    run_jobs()
    again = client.get("/api/v1/notifications", headers=shop["officer"]).json()["items"]
    assert sum(n["type"] == "EXPIRY" for n in again) == 1
