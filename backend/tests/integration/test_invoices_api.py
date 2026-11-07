"""Invoice digitization end to end: upload -> OCR worker -> human review -> approve -> stock.

Uses synthetic invoices from scripts/generate_synthetic_invoices.py, so the expected
values are known exactly.
"""

import io
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.models import SupplierProductAlias
from app.workers.runner import Worker
from scripts.generate_synthetic_invoices import PRODUCTS, SUPPLIERS, generate

D = Decimal


@pytest.fixture(scope="module")
def docs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[bytes, dict]]:
    """Seed 7: #1 is a clean classic invoice (dairy), #5 a text PDF (dairy)."""
    out = tmp_path_factory.mktemp("invoices")
    files = generate(out, 5, seed=7, today=date.today())
    result = {}
    for f in files:
        truth = json.loads(f.with_name(f.stem + ".truth.json").read_text())
        result[truth["layout"]] = (f.read_bytes(), truth)
    return result


@pytest.fixture
def env(client: TestClient, auth_headers):  # type: ignore[no-untyped-def]
    admin = auth_headers("super_admin", username="boss")[1]
    officer = auth_headers("inventory_officer", username="officer")[1]
    cashier = auth_headers("cashier", username="till")[1]
    suppliers = {}
    for name, pin, _ in SUPPLIERS:
        r = client.post("/api/v1/suppliers", headers=admin, json={"name": name, "kra_pin": pin})
        assert r.status_code == 201, r.text
        suppliers[name] = r.json()
    products = {}
    for name, (_, cost, vat, _) in PRODUCTS.items():
        r = client.post(
            "/api/v1/products",
            headers=admin,
            json={
                "name": name,
                "selling_price": str(cost * 2),
                "vat_rate": str(vat),
                "purchase_price": str(cost),
            },
        )
        assert r.status_code == 201, r.text
        products[name] = r.json()
    return {
        "admin": admin,
        "officer": officer,
        "cashier": cashier,
        "suppliers": suppliers,
        "products": products,
    }


def upload(client: TestClient, h: dict, data: bytes, name: str):  # type: ignore[no-untyped-def]
    mime = {"pdf": "application/pdf", "png": "image/png"}.get(name.rsplit(".", 1)[-1], "image/jpeg")
    return client.post("/api/v1/invoices", headers=h, files={"file": (name, data, mime)})


def process_all() -> None:
    worker = Worker()
    while worker.run_once():
        pass


def stock(client: TestClient, h: dict, product: dict) -> D:
    return D(client.get(f"/api/v1/products/{product['id']}", headers=h).json()["quantity_on_hand"])


def test_upload_read_review_approve_updates_stock(client: TestClient, env, docs) -> None:  # type: ignore[no-untyped-def]
    h = env["officer"]
    data, truth = docs["classic"]
    r = upload(client, h, data, "delivery.jpg")
    assert r.status_code == 202, r.text
    inv = r.json()
    assert inv["status"] == "QUEUED"

    process_all()
    inv = client.get(f"/api/v1/invoices/{inv['id']}", headers=h).json()
    assert inv["status"] == "NEEDS_REVIEW", inv["error_message"]
    assert inv["ocr_engine"] == "tesseract"
    assert inv["supplier"]["name"] == truth["supplier_name"]
    assert inv["invoice_number"] == truth["invoice_number"]
    assert inv["invoice_date"] == truth["invoice_date"]
    assert D(inv["grand_total"]) == D(truth["grand_total"])
    got = [(i["product"]["name"], D(i["quantity"]), D(i["unit_price"])) for i in inv["items"]]
    want = [(i["product"], D(i["quantity"]), D(i["unit_price"])) for i in truth["items"]]
    assert got == want
    assert all(not i["suggested"] for i in inv["items"])

    # The page image is served only to signed-in staff with invoice rights.
    page = client.get(f"/api/v1/invoices/{inv['id']}/pages/1", headers=h)
    assert page.status_code == 200 and page.headers["content-type"] == "image/png"
    assert client.get(f"/api/v1/invoices/{inv['id']}/pages/1").status_code == 401
    assert (
        client.get(f"/api/v1/invoices/{inv['id']}/pages/1", headers=env["cashier"]).status_code
        == 403
    )

    # Reviewer corrects the first line's quantity (e.g. short delivery).
    first, second = inv["items"]
    before = {
        i["product"]["name"]: stock(client, h, env["products"][i["product"]["name"]])
        for i in inv["items"]
    }
    review = {
        "supplier_id": inv["supplier"]["id"],
        "invoice_number": inv["invoice_number"],
        "invoice_date": inv["invoice_date"],
        "subtotal": inv["subtotal"],
        "tax_total": inv["tax_total"],
        "grand_total": inv["grand_total"],
        "prices_include_vat": inv["prices_include_vat"],
        "items": [
            {
                "id": first["id"],
                "description": first["description"],
                "product_id": first["product"]["id"],
                "quantity": "8",
                "unit_price": first["unit_price"],
                "line_total": str(D(first["unit_price"]) * 8),
            },
            {
                "id": second["id"],
                "description": second["description"],
                "product_id": second["product"]["id"],
                "quantity": second["quantity"],
                "unit_price": second["unit_price"],
                "line_total": second["line_total"],
            },
        ],
    }
    r = client.put(f"/api/v1/invoices/{inv['id']}", headers=h, json=review)
    assert r.status_code == 200, r.text
    assert [i["was_corrected"] for i in r.json()["items"]] == [True, False]

    r = client.post(f"/api/v1/invoices/{inv['id']}/approve", headers=h, json={})
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "APPROVED" and done["purchase_id"]

    grn = client.get(f"/api/v1/purchases/{done['purchase_id']}", headers=h).json()
    assert grn["source"] == "INVOICE"
    assert grn["supplier_invoice_number"] == truth["invoice_number"]
    names = [first["product"]["name"], second["product"]["name"]]
    assert stock(client, h, env["products"][names[0]]) == before[names[0]] + 8
    assert stock(client, h, env["products"][names[1]]) == before[names[1]] + D(second["quantity"])

    # Approved invoices are closed for editing and counted in the stats.
    assert (
        client.post(f"/api/v1/invoices/{inv['id']}/approve", headers=h, json={}).status_code == 422
    )
    stats = client.get("/api/v1/invoices/stats", headers=h).json()
    assert stats["approved"] == 1 and stats["by_status"]["APPROVED"] == 1


def test_approval_learns_aliases_for_next_time(client: TestClient, env, docs, db) -> None:  # type: ignore[no-untyped-def]
    h = env["officer"]
    data, truth = docs["classic"]
    inv = upload(client, h, data, "a.jpg").json()
    process_all()
    inv = client.get(f"/api/v1/invoices/{inv['id']}", headers=h).json()
    assert (
        client.post(f"/api/v1/invoices/{inv['id']}/approve", headers=h, json={}).status_code == 200
    )
    aliases = db.scalars(select(SupplierProductAlias)).all()
    assert {a.product_id for a in aliases} == {i["product"]["id"] for i in inv["items"]}


def test_pdf_with_text_layer_skips_ocr(client: TestClient, env, docs) -> None:  # type: ignore[no-untyped-def]
    h = env["officer"]
    data, truth = docs["pdf"]
    inv = upload(client, h, data, "invoice.pdf").json()
    process_all()
    inv = client.get(f"/api/v1/invoices/{inv['id']}", headers=h).json()
    assert inv["status"] == "NEEDS_REVIEW"
    assert inv["ocr_engine"] == "pdf-text"
    assert inv["invoice_number"] == truth["invoice_number"]
    assert len(inv["items"]) == len(truth["items"])
    assert D(inv["tax_total"]) == D(truth["tax_total"])


def test_duplicate_file_and_duplicate_invoice(client: TestClient, env, docs) -> None:  # type: ignore[no-untyped-def]
    h = env["officer"]
    data, _ = docs["classic"]
    first = upload(client, h, data, "a.jpg").json()
    r = upload(client, h, data, "again.jpg")
    assert r.status_code == 409 and r.json()["error"]["code"] == "DUPLICATE_FILE"

    process_all()
    assert (
        client.post(f"/api/v1/invoices/{first['id']}/approve", headers=h, json={}).status_code
        == 200
    )

    # The same invoice photographed again (different bytes): flagged, and approval refused.
    buf = io.BytesIO()
    Image.open(io.BytesIO(data)).save(buf, "PNG")  # same pixels, new file
    second = upload(client, h, buf.getvalue(), "photo-again.png").json()
    process_all()
    second = client.get(f"/api/v1/invoices/{second['id']}", headers=h).json()
    assert "DUPLICATE_INVOICE" in {f["code"] for f in second["flags"]}
    r = client.post(f"/api/v1/invoices/{second['id']}/approve", headers=h, json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "DUPLICATE_INVOICE"

    r = client.post(
        f"/api/v1/invoices/{second['id']}/reject", headers=h, json={"note": "Duplicate"}
    )
    assert r.status_code == 200 and r.json()["status"] == "REJECTED"


def test_approve_requires_confirmed_products(client: TestClient, env, docs) -> None:  # type: ignore[no-untyped-def]
    h = env["officer"]
    data, _ = docs["classic"]
    inv = upload(client, h, data, "a.jpg").json()
    process_all()
    inv = client.get(f"/api/v1/invoices/{inv['id']}", headers=h).json()
    lines = [
        {
            "id": i["id"],
            "description": i["description"],
            "product_id": None,
            "quantity": i["quantity"],
            "unit_price": i["unit_price"],
        }
        for i in inv["items"]
    ]
    r = client.put(
        f"/api/v1/invoices/{inv['id']}",
        headers=h,
        json={
            "supplier_id": inv["supplier"]["id"],
            "invoice_number": inv["invoice_number"],
            "items": lines,
        },
    )
    assert r.status_code == 200
    r = client.post(f"/api/v1/invoices/{inv['id']}/approve", headers=h, json={})
    assert r.status_code == 422 and r.json()["error"]["code"] == "REVIEW_INCOMPLETE"
    assert "confirm the product" in r.json()["error"]["message"]


@pytest.mark.parametrize(
    ("name", "data", "code"),
    [
        ("notes.txt", b"hello there, not an invoice", "UNSUPPORTED_FILE"),
        ("fake.jpg", b"\xff\xd8\xff\xe0" + b"garbage" * 20, "UNSUPPORTED_FILE"),
        ("empty.png", b"", "UNSUPPORTED_FILE"),
        ("big.jpg", b"\xff\xd8\xff\xe0" + b"0" * (10 * 1024 * 1024 + 1), "FILE_TOO_LARGE"),
    ],
)
def test_upload_rejects_bad_files(
    client: TestClient, env, name: str, data: bytes, code: str
) -> None:  # type: ignore[no-untyped-def]
    r = upload(client, env["officer"], data, name)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == code


def test_permissions(client: TestClient, env, docs) -> None:  # type: ignore[no-untyped-def]
    data, _ = docs["classic"]
    assert upload(client, env["cashier"], data, "a.jpg").status_code == 403
    assert client.get("/api/v1/invoices", headers=env["cashier"]).status_code == 403
    assert client.get("/api/v1/invoices").status_code == 401


def test_reject_needs_a_reason_and_listing_filters(client: TestClient, env, docs) -> None:  # type: ignore[no-untyped-def]
    h = env["officer"]
    data, _ = docs["classic"]
    inv = upload(client, h, data, "a.jpg").json()
    process_all()
    assert (
        client.post(f"/api/v1/invoices/{inv['id']}/reject", headers=h, json={}).status_code == 422
    )
    assert client.get("/api/v1/invoices?status=OPEN", headers=h).json()["total"] == 1
    client.post(f"/api/v1/invoices/{inv['id']}/reject", headers=h, json={"note": "Wrong store"})
    assert client.get("/api/v1/invoices?status=OPEN", headers=h).json()["total"] == 0
    assert client.get("/api/v1/invoices?status=REJECTED", headers=h).json()["total"] == 1


def test_unreadable_image_goes_to_manual_entry(client: TestClient, env, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    h = env["officer"]
    buf = io.BytesIO()
    Image.new("RGB", (900, 1200), "white").save(buf, "PNG")
    inv = upload(client, h, buf.getvalue(), "blank.png").json()
    process_all()
    inv = client.get(f"/api/v1/invoices/{inv['id']}", headers=h).json()
    assert inv["status"] == "NEEDS_REVIEW"
    assert inv["items"] == []
    assert "NO_ITEMS" in {f["code"] for f in inv["flags"]}
    # A reviewer can type the lines in by hand and approve.
    sup = env["suppliers"][SUPPLIERS[0][0]]
    sugar = env["products"]["White Sugar 2kg"]
    r = client.put(
        f"/api/v1/invoices/{inv['id']}",
        headers=h,
        json={
            "supplier_id": sup["id"],
            "invoice_number": "HAND-1",
            "invoice_date": str(date.today()),
            "items": [
                {
                    "description": "Sugar",
                    "product_id": sugar["id"],
                    "quantity": "5",
                    "unit_price": "200",
                    "line_total": "1000",
                }
            ],
        },
    )
    assert r.status_code == 200, r.text
    before = stock(client, h, sugar)
    assert (
        client.post(f"/api/v1/invoices/{inv['id']}/approve", headers=h, json={}).status_code == 200
    )
    assert stock(client, h, sugar) == before + 5
