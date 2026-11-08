"""Management dashboard and downloadable reports: content, permissions and formats."""

import csv
import io
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, Category

D = Decimal


@pytest.fixture
def shop(client: TestClient, auth_headers, db: Session):  # type: ignore[no-untyped-def]
    admin = auth_headers("super_admin", username="boss")[1]
    manager = auth_headers("store_manager", username="mgr")[1]
    officer = auth_headers("inventory_officer", username="officer")[1]
    till_a = auth_headers("cashier", username="till_a")[1]
    till_b = auth_headers("cashier", username="till_b")[1]
    dry = Category(name="Dry goods")
    dairy = Category(name="Dairy")
    db.add_all([dry, dairy])
    db.commit()
    sup = client.post("/api/v1/suppliers", headers=admin, json={"name": "Demo Wholesalers"}).json()

    def product(name: str, cat: Category, price: str, cost: str, qty: str, vat: str = "16") -> dict:
        r = client.post(
            "/api/v1/products",
            headers=admin,
            json={
                "name": name,
                "category_id": cat.id,
                "selling_price": price,
                "vat_rate": vat,
                "min_stock_level": "5",
                "opening_stock": {"quantity": qty, "unit_cost": cost},
            },
        )
        assert r.status_code == 201, r.text
        return r.json()

    sugar = product("White Sugar 2kg", dry, "232", "180", "40")
    milk = product("Fresh Milk 500ml", dairy, "60", "45", "6", vat="0")

    def sell(h: dict, p: dict, q: str) -> None:
        body = {
            "client_request_id": str(uuid.uuid4()),
            "payment_method": "CASH",
            "amount_tendered": "10000",
            "items": [{"product_id": p["id"], "quantity": q}],
        }
        r = client.post("/api/v1/sales", headers=h, json=body)
        assert r.status_code == 201, r.text

    sell(till_a, sugar, "3")  # 696 incl. VAT = 600 + 96 VAT; cost 540
    sell(till_b, milk, "2")  # 120, zero-rated; cost 90
    client.post(
        "/api/v1/purchases",
        headers=officer,
        json={
            "supplier_id": sup["id"],
            "supplier_invoice_number": "INV-1",
            "items": [{"product_id": sugar["id"], "quantity": "10", "unit_cost": "180"}],
        },
    )
    return {
        "admin": admin,
        "manager": manager,
        "officer": officer,
        "till_a": till_a,
        "till_b": till_b,
        "sugar": sugar,
        "milk": milk,
        "dry": dry.id,
        "dairy": dairy.id,
    }


# --- Dashboard -----------------------------------------------------------------------------


def test_dashboard_for_manager(client: TestClient, shop) -> None:  # type: ignore[no-untyped-def]
    d = client.get("/api/v1/dashboard", headers=shop["manager"]).json()
    inv, s = d["inventory"], d["sales"]
    assert inv["total_products"] == 2
    # Stock: sugar 40 - 3 + 10 = 47 at 180; milk 6 - 2 = 4 at 45 (below its minimum of 5).
    assert D(inv["inventory_value"]) == D(47 * 180 + 4 * 45)
    assert inv["low_stock"] == 1 and inv["low_stock_items"][0]["name"] == "Fresh Milk 500ml"
    assert D(s["today_revenue"]) == D("720.00")  # 600 + 120, excl. VAT
    assert s["today_transactions"] == 2
    assert D(s["period_gross_profit"]) == D("720.00") - D(540 + 90)
    assert [m["name"] for m in d["movers"]["fast"]][0] == "White Sugar 2kg"
    assert {c["category"] for c in d["categories"]} == {"Dry goods", "Dairy"}
    assert d["open_irregularities"] == 0

    # Category filter: only Dairy.
    d2 = client.get(
        f"/api/v1/dashboard?category_id={shop['dairy']}", headers=shop["manager"]
    ).json()
    assert d2["inventory"]["total_products"] == 1
    assert D(d2["sales"]["period_revenue"]) == D("120.00")
    assert d2["categories"] is None


def test_dashboard_permissions(client: TestClient, shop) -> None:  # type: ignore[no-untyped-def]
    d = client.get("/api/v1/dashboard", headers=shop["officer"]).json()
    assert d["sales"] is None and d["inventory"]["inventory_value"] is None  # no finance rights
    assert d["open_irregularities"] is None
    assert d["inventory"]["total_products"] == 2
    assert client.get("/api/v1/dashboard", headers=shop["till_a"]).status_code == 403
    r = client.get(
        "/api/v1/dashboard?date_from=2026-11-05&date_to=2026-11-01", headers=shop["manager"]
    )
    assert r.status_code == 422


# --- Reports --------------------------------------------------------------------------------


def test_report_lists_follow_roles(client: TestClient, shop) -> None:  # type: ignore[no-untyped-def]
    keys = lambda h: {r["key"] for r in client.get("/api/v1/reports", headers=h).json()}  # noqa: E731
    assert len(keys(shop["manager"])) == 10
    assert keys(shop["officer"]) == {
        "inventory-valuation",
        "purchase-history",
        "supplier-performance",
        "stock-movements",
        "expired-products",
        "demand-forecast",
    }
    assert keys(shop["till_a"]) == {"daily-sales"}
    assert client.get("/api/v1/reports/profitability", headers=shop["officer"]).status_code == 403
    assert client.get("/api/v1/reports/profitability", headers=shop["till_a"]).status_code == 403
    assert client.get("/api/v1/reports/nope", headers=shop["manager"]).status_code == 404


@pytest.mark.parametrize("fmt", ["pdf", "xlsx", "csv"])
def test_every_report_downloads(client: TestClient, shop, fmt: str) -> None:  # type: ignore[no-untyped-def]
    for r in client.get("/api/v1/reports", headers=shop["manager"]).json():
        if r["key"] == "demand-forecast":
            continue  # needs a forecast run; covered below
        res = client.get(f"/api/v1/reports/{r['key']}?format={fmt}", headers=shop["manager"])
        assert res.status_code == 200, (r["key"], res.text)
        assert f'.{fmt}"' in res.headers["content-disposition"]
        body = res.content
        if fmt == "pdf":
            assert body.startswith(b"%PDF")
        elif fmt == "xlsx":
            assert body.startswith(b"PK")  # zip container
        else:
            assert body.startswith(b"\xef\xbb\xbf")  # BOM so Excel reads UTF-8


def test_report_figures(client: TestClient, shop, db: Session) -> None:  # type: ignore[no-untyped-def]
    h = shop["manager"]
    res = client.get("/api/v1/reports/inventory-valuation?format=csv", headers=h)
    rows = list(csv.reader(io.StringIO(res.content.decode("utf-8-sig"))))
    assert rows[0][:4] == ["Product", "SKU", "Category", "On hand"]
    by_name = {r[0]: r for r in rows[1:]}
    assert by_name["White Sugar 2kg"][6] == "8460.00"  # 47 x 180
    assert by_name["Total"][6] == "8640.00"  # + 4 x 45

    wb = load_workbook(
        io.BytesIO(client.get("/api/v1/reports/profitability?format=xlsx", headers=h).content)
    )
    ws = wb.active
    header = next(
        i for i, row in enumerate(ws.iter_rows(values_only=True), 1) if row[0] == "Product"
    )
    first = [c.value for c in ws[header + 1]]
    assert first[0] == "White Sugar 2kg" and first[3] == 600 and first[5] == 60  # revenue, profit
    assert ws.cell(row=header + 1, column=4).number_format == "#,##0.00"

    # Category filter applies.
    res = client.get(
        f"/api/v1/reports/profitability?format=csv&category_id={shop['dairy']}", headers=h
    )
    names = [r[0] for r in csv.reader(io.StringIO(res.content.decode("utf-8-sig")))][1:]
    assert names == ["Fresh Milk 500ml", "Total"]

    # Exports are audited.
    assert db.scalar(select(AuditLog).where(AuditLog.action == "report.exported")) is not None


def test_cashier_sees_only_own_sales_without_costs(client: TestClient, shop) -> None:  # type: ignore[no-untyped-def]
    res = client.get("/api/v1/reports/daily-sales?format=csv", headers=shop["till_a"])
    rows = list(csv.reader(io.StringIO(res.content.decode("utf-8-sig"))))
    assert "Gross profit" not in rows[0]
    day = rows[1]
    assert day[1] == "1" and day[3] == "696.00"  # only till_a's sugar sale
    manager = list(
        csv.reader(
            io.StringIO(
                client.get(
                    "/api/v1/reports/daily-sales?format=csv", headers=shop["manager"]
                ).content.decode("utf-8-sig")
            )
        )
    )
    assert manager[1][1] == "2" and "Gross profit" in manager[0]


def test_report_rate_limit_and_validation(client: TestClient, shop) -> None:  # type: ignore[no-untyped-def]
    from app.api.v1.reports import report_limiter

    r = client.get(
        "/api/v1/reports/daily-sales?date_from=2026-11-05&date_to=2026-01-01",
        headers=shop["manager"],
    )
    assert r.status_code == 422
    report_limiter.reset()
    for _ in range(30):
        client.get("/api/v1/reports/stock-movements?format=csv", headers=shop["officer"])
    assert (
        client.get(
            "/api/v1/reports/stock-movements?format=csv", headers=shop["officer"]
        ).status_code
        == 429
    )
    report_limiter.reset()


def test_forecast_report_after_a_run(client: TestClient, shop) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/api/v1/reports/demand-forecast?format=pdf", headers=shop["officer"])
    assert r.status_code == 422  # nothing forecast yet
    from app.workers.runner import Worker

    client.post("/api/v1/forecasts/run", headers=shop["officer"])
    while Worker().run_once():
        pass
    r = client.get("/api/v1/reports/demand-forecast?format=csv", headers=shop["officer"])
    assert r.status_code == 200
    # Today's sales are not history yet, so there is nothing to forecast: header only.
    header = next(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert header[:4] == ["Product", "Model", "Next 7 days", "Next 28 days"]
