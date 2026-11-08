"""The brief's demonstration scenario, end to end through the HTTP API and the worker.

Section 11 (demonstration):
 1. An administrator logs in.                    7. A cashier records customer sales.
 2. The administrator registers suppliers.       8. Stock quantities decrease.
 3. An inventory officer uploads an invoice.     9. The financial dashboard updates.
 4. The AI extracts the invoice information.    10. The forecasting engine predicts demand.
 5. The officer reviews and approves it.        11. Anomaly detection finds unusual movements.
 6. Inventory quantities update automatically.

Section 9's test scenarios (upload -> extract -> confirm -> stock up -> sale -> stock down ->
profit -> dashboard -> unusual movements) are the same steps and are asserted along the way.
All data is synthetic (scripts/generate_synthetic_invoices.py).
"""

import json
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User
from app.schemas.sales import CartLine, CheckoutRequest
from app.schemas.stock import AdjustmentCreate
from app.services import sales_service, stock_service
from app.services.audit_service import RequestContext
from app.services.forecast_service import today
from app.workers.runner import Worker
from scripts.generate_synthetic_invoices import PRODUCTS, SUPPLIERS, generate
from tests.conftest import login

D = Decimal
CTX = RequestContext(ip_address="127.0.0.1", user_agent="scenario")


def run_jobs() -> None:
    w = Worker()
    while w.run_once():
        pass


def test_demonstration_scenario(client: TestClient, make_user, db: Session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    # 1. An administrator logs in.
    admin_user = make_user("super_admin", username="admin")
    admin = login(client, "admin")
    assert client.get("/api/v1/auth/me", headers=admin).json()["role"]["name"] == "super_admin"
    officer_user = make_user("inventory_officer", username="officer")
    cashier_user = make_user("cashier", username="cashier")
    make_user("store_manager", username="manager")
    officer, cashier, manager = (
        login(client, "officer"),
        login(client, "cashier"),
        login(client, "manager"),
    )

    # 2. The administrator registers suppliers (and the catalogue they supply).
    for name, pin, _ in SUPPLIERS:
        r = client.post("/api/v1/suppliers", headers=admin, json={"name": name, "kra_pin": pin})
        assert r.status_code == 201
    products = {}
    for name, (_, cost, vat, _) in PRODUCTS.items():
        r = client.post(
            "/api/v1/products",
            headers=admin,
            json={
                "name": name,
                "selling_price": str(round(cost * 1.3 * (1 + vat / 100))),
                "vat_rate": str(vat),
                "min_stock_level": "10",
                "opening_stock": {"quantity": "800", "unit_cost": str(cost)},
            },
        )
        assert r.status_code == 201, r.text
        products[name] = r.json()

    # Some trading history so the forecast has something to learn from (10 weeks).
    till = db.get(User, cashier_user.id)
    tz = ZoneInfo("Africa/Nairobi")
    for k in range(70, 0, -1):
        d = today() - timedelta(days=k)
        busy = d.weekday() >= 5 or d.day >= 28 or d.day <= 2
        for name, base in (("White Bread 400g", 4), ("Fresh Milk 500ml", 5)):
            qty = base + (2 if busy else 0) + (k % 3) - 1
            sales_service.checkout(
                db,
                CheckoutRequest(
                    client_request_id=uuid.uuid4(),
                    payment_method="CASH",
                    amount_tendered=D("100000"),
                    items=[CartLine(product_id=products[name]["id"], quantity=D(qty))],
                ),
                till,
                CTX,
                sold_at=datetime.combine(d, time(12), tz),
            )

    # 3. An inventory officer uploads a supplier invoice (a synthetic one, seed 7 #1).
    [path] = [p for p in generate(tmp_path, 1, seed=7, today=today()) if p.suffix == ".jpg"]
    truth = json.loads(path.with_name(path.stem + ".truth.json").read_text())
    up = client.post(
        "/api/v1/invoices",
        headers=officer,
        files={"file": (path.name, path.read_bytes(), "image/jpeg")},
    )
    assert up.status_code == 202

    # 4. The AI extracts the invoice information (worker: OpenCV + Tesseract + matching).
    run_jobs()
    inv = client.get(f"/api/v1/invoices/{up.json()['id']}", headers=officer).json()
    assert inv["status"] == "NEEDS_REVIEW"
    assert inv["supplier"]["name"] == truth["supplier_name"]
    assert inv["invoice_number"] == truth["invoice_number"]
    lines = {i["product"]["name"]: D(i["quantity"]) for i in inv["items"]}
    assert lines == {i["product"]: D(i["quantity"]) for i in truth["items"]}

    # 5. The officer reviews and approves it.  6. Stock updates automatically.
    before = {
        n: D(
            client.get(f"/api/v1/products/{products[n]['id']}", headers=officer).json()[
                "quantity_on_hand"
            ]
        )
        for n in lines
    }
    r = client.post(f"/api/v1/invoices/{inv['id']}/approve", headers=officer, json={})
    assert r.status_code == 200, r.text
    for n, q in lines.items():
        after = D(
            client.get(f"/api/v1/products/{products[n]['id']}", headers=officer).json()[
                "quantity_on_hand"
            ]
        )
        assert after == before[n] + q

    # 7. A cashier records customer sales.  8. Stock quantities decrease.
    dash0 = client.get("/api/v1/dashboard", headers=manager).json()
    sold = next(iter(lines))  # a product that was just received
    stock0 = D(
        client.get(f"/api/v1/products/{products[sold]['id']}", headers=cashier).json()[
            "quantity_on_hand"
        ]
    )
    sale = client.post(
        "/api/v1/sales",
        headers=cashier,
        json={
            "client_request_id": str(uuid.uuid4()),
            "payment_method": "MPESA",
            "payment_reference": "SKD4H2L9QX",
            "items": [{"product_id": products[sold]["id"], "quantity": "5"}],
        },
    )
    assert sale.status_code == 201, sale.text
    stock1 = D(
        client.get(f"/api/v1/products/{products[sold]['id']}", headers=cashier).json()[
            "quantity_on_hand"
        ]
    )
    assert stock1 == stock0 - 5

    # 9. The financial dashboard updates (and profit is computed from the recorded cost).
    s = sale.json()
    net = D(s["grand_total"]) - D(s["tax_total"])
    dash1 = client.get("/api/v1/dashboard", headers=manager).json()
    assert D(dash1["sales"]["today_revenue"]) == D(dash0["sales"]["today_revenue"]) + net
    assert dash1["sales"]["today_transactions"] == dash0["sales"]["today_transactions"] + 1
    assert D(dash1["sales"]["period_gross_profit"]) > D(dash0["sales"]["period_gross_profit"])
    fin = client.get(
        f"/api/v1/analytics/summary?date_from={today()}&date_to={today()}", headers=manager
    ).json()
    assert D(fin["revenue"]) == net

    # 10. The forecasting engine predicts future demand.
    client.post("/api/v1/forecasts/run", headers=officer)
    run_jobs()
    fc = client.get("/api/v1/forecasts", headers=officer).json()
    assert fc["run"]["status"] == "SUCCEEDED"
    bread = next(p for p in fc["products"] if p["product"]["name"] == "White Bread 400g")
    assert 20 < bread["next_7_days"] < 60  # about 4-6 a day

    # 11. Anomaly detection identifies unusual inventory movements.
    officer_db = db.get(User, officer_user.id)
    rice = products["Pishori Rice 2kg"]
    for k in (40, 25, 10):  # a normal: an occasional one-unit correction
        stock_service.create_adjustment(
            db,
            AdjustmentCreate(
                product_id=rice["id"], quantity_change=D(-1), reason_code="COUNT_CORRECTION"
            ),
            officer_db,
            CTX,
            at=datetime.combine(today() - timedelta(days=k), time(18), tz),
        )
    stock_service.create_adjustment(
        db,
        AdjustmentCreate(
            product_id=rice["id"], quantity_change=D(-12), reason_code="COUNT_CORRECTION"
        ),
        officer_db,
        CTX,
    )
    client.post("/api/v1/anomalies/scan", headers=manager)
    run_jobs()
    alerts = client.get("/api/v1/anomalies?status=OPEN_ALL", headers=manager).json()["items"]
    loss = next(
        a
        for a in alerts
        if a["entity_type"] == "product" and a["product"]["name"] == "Pishori Rice 2kg"
    )
    assert loss["kind"] == "UNEXPLAINED_STOCK_LOSS" and "12 units" in loss["explanation"]
    assert date.fromisoformat(loss["period_start"]) == today()
    # ...and the people responsible for it are told.
    assert any(
        n["type"] == "ANOMALY"
        for n in client.get("/api/v1/notifications", headers=manager).json()["items"]
    )
    assert admin_user.id
