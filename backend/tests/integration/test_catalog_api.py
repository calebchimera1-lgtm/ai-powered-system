"""Categories, suppliers and products through the HTTP API, including role rules."""

import io
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image

PRODUCTS = "/api/v1/products"


def sugar(**kw):  # type: ignore[no-untyped-def]
    body = {
        "name": "White Sugar 2kg",
        "selling_price": "245.00",
        "unit_of_measure": "pcs",
        "min_stock_level": "10",
        "max_stock_level": "120",
    }
    body.update(kw)
    return body


@pytest.fixture
def admin(auth_headers):  # type: ignore[no-untyped-def]
    return auth_headers("super_admin", username="boss")[1]


# --- Categories -----------------------------------------------------------------


def test_category_tree_and_rules(client: TestClient, admin) -> None:
    food = client.post("/api/v1/categories", headers=admin, json={"name": "Food"}).json()
    dry = client.post(
        "/api/v1/categories", headers=admin, json={"name": "Dry goods", "parent_id": food["id"]}
    ).json()
    assert dry["path"] == "Food › Dry goods"

    dup = client.post("/api/v1/categories", headers=admin, json={"name": "FOOD"})
    assert dup.status_code == 409

    loop = client.patch(
        f"/api/v1/categories/{food['id']}", headers=admin, json={"parent_id": dry["id"]}
    )
    assert loop.status_code == 422 and "inside itself" in loop.json()["error"]["message"]

    client.post(PRODUCTS, headers=admin, json=sugar(category_id=dry["id"]))
    r = client.delete(f"/api/v1/categories/{dry['id']}", headers=admin)
    assert r.status_code == 409 and "still has products" in r.json()["error"]["message"]
    r = client.delete(f"/api/v1/categories/{food['id']}", headers=admin)
    assert r.status_code == 409  # has a sub-category

    listed = client.get("/api/v1/categories", headers=admin).json()
    assert {c["name"]: c["product_count"] for c in listed} == {"Food": 0, "Dry goods": 1}


def test_cashier_can_read_but_not_write_categories(client: TestClient, auth_headers) -> None:
    _, h = auth_headers("cashier")
    assert client.get("/api/v1/categories", headers=h).status_code == 200
    assert client.post("/api/v1/categories", headers=h, json={"name": "X1"}).status_code == 403


# --- Suppliers ------------------------------------------------------------------


def test_supplier_crud_and_validation(client: TestClient, admin) -> None:
    body = {
        "name": "Demo Wholesalers Ltd",
        "kra_pin": "p051234567x",
        "phone": "+254 722 000 111",
        "email": "orders@demo-wholesale.example.com",
        "payment_terms_days": 14,
    }
    r = client.post("/api/v1/suppliers", headers=admin, json=body)
    assert r.status_code == 201, r.text
    sup = r.json()
    assert sup["kra_pin"] == "P051234567X"

    assert client.post("/api/v1/suppliers", headers=admin, json=body).status_code == 409
    bad = client.post("/api/v1/suppliers", headers=admin, json={"name": "X Ltd", "kra_pin": "123"})
    assert bad.status_code == 422 and "KRA PIN" in bad.text

    r = client.patch(f"/api/v1/suppliers/{sup['id']}", headers=admin, json={"is_active": False})
    assert r.json()["is_active"] is False
    page = client.get("/api/v1/suppliers", headers=admin, params={"is_active": True}).json()
    assert page["total"] == 0


def test_supplier_products_and_price_comparison(client: TestClient, admin, auth_headers) -> None:
    p = client.post(PRODUCTS, headers=admin, json=sugar()).json()
    a = client.post("/api/v1/suppliers", headers=admin, json={"name": "Alpha Distributors"}).json()
    b = client.post("/api/v1/suppliers", headers=admin, json={"name": "Beta Traders"}).json()
    client.put(
        f"/api/v1/suppliers/{a['id']}/products/{p['id']}",
        headers=admin,
        json={"supplier_sku": "A-SUG2", "last_unit_price": "205.00"},
    )
    client.put(
        f"/api/v1/suppliers/{b['id']}/products/{p['id']}",
        headers=admin,
        json={"last_unit_price": "198.50", "lead_time_days": 2},
    )

    cmp = client.get(f"{PRODUCTS}/{p['id']}/suppliers", headers=admin).json()
    assert [(c["supplier_name"], c["last_unit_price"]) for c in cmp] == [
        ("Beta Traders", "198.50"),
        ("Alpha Distributors", "205.00"),
    ]
    assert client.get(f"/api/v1/suppliers/{a['id']}", headers=admin).json()["product_count"] == 1

    _, officer = auth_headers("inventory_officer")
    assert client.get(f"{PRODUCTS}/{p['id']}/suppliers", headers=officer).status_code == 200
    _, cashier = auth_headers("cashier")
    assert client.get(f"{PRODUCTS}/{p['id']}/suppliers", headers=cashier).status_code == 403


# --- Products ---------------------------------------------------------------------


def test_create_product_with_generated_sku_and_opening_stock(client: TestClient, admin) -> None:
    r = client.post(
        PRODUCTS,
        headers=admin,
        json=sugar(
            barcode="5000159407236",
            opening_stock={"quantity": "40", "unit_cost": "200.00"},
        ),
    )
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["sku"] == f"SKU-{p['id']:06d}"
    assert p["quantity_on_hand"] == "40.000" and p["avg_cost"] == "200.0000"
    assert p["stock_value"] == "8000.00"
    # 245 incl. VAT = 211.21 net; (211.21 - 200) / 211.21 = 5.31%
    assert p["margin_percent"] == "5.31"
    assert p["stock_status"] == "ok"

    moves = client.get("/api/v1/stock/movements", headers=admin, params={"product_id": p["id"]})
    [m] = moves.json()["items"]
    assert m["movement_type"] == "OPENING" and m["reason"] == "Opening stock"


def test_product_validation(client: TestClient, admin) -> None:
    r = client.post(PRODUCTS, headers=admin, json=sugar(barcode="5000159407237"))
    assert r.status_code == 422 and "check digit" in r.text
    r = client.post(PRODUCTS, headers=admin, json=sugar(min_stock_level="50", max_stock_level="5"))
    assert r.status_code == 422
    r = client.post(PRODUCTS, headers=admin, json=sugar(unit_of_measure="crates"))
    assert r.status_code == 422
    r = client.post(PRODUCTS, headers=admin, json=sugar(selling_price="-1"))
    assert r.status_code == 422


def test_duplicates_rejected(client: TestClient, admin) -> None:
    client.post(PRODUCTS, headers=admin, json=sugar(sku="SUG-2KG", barcode="5000159407236"))
    r = client.post(PRODUCTS, headers=admin, json=sugar(name="Other", sku="sug-2kg"))
    assert r.status_code == 409 and r.json()["error"]["details"][0]["field"] == "sku"
    r = client.post(PRODUCTS, headers=admin, json=sugar(name="Other", barcode="5000159407236"))
    assert r.status_code == 409 and "White Sugar 2kg" in r.json()["error"]["message"]


def test_expiry_tracked_opening_stock_requires_expiry(client: TestClient, admin) -> None:
    milk = {
        "name": "Fresh Milk 500ml",
        "selling_price": "65",
        "tracks_expiry": True,
        "opening_stock": {"quantity": "24", "unit_cost": "48"},
    }
    r = client.post(PRODUCTS, headers=admin, json=milk)
    assert r.status_code == 422 and "expiry" in r.json()["error"]["message"]
    milk["opening_stock"]["expiry_date"] = str(date.today() + timedelta(days=6))
    r = client.post(PRODUCTS, headers=admin, json=milk)
    assert r.status_code == 201
    assert r.json()["next_expiry"] == milk["opening_stock"]["expiry_date"]
    batches = client.get(f"{PRODUCTS}/{r.json()['id']}/batches", headers=admin).json()
    assert batches[0]["days_to_expiry"] == 6


def test_cashier_sees_products_without_costs(client: TestClient, admin, auth_headers) -> None:
    client.post(
        PRODUCTS, headers=admin, json=sugar(opening_stock={"quantity": "5", "unit_cost": "200"})
    )
    _, cashier = auth_headers("cashier")
    item = client.get(PRODUCTS, headers=cashier).json()["items"][0]
    assert item["name"] == "White Sugar 2kg"
    for secret in ("avg_cost", "purchase_price", "stock_value", "margin_percent"):
        assert secret not in item
    assert client.post(PRODUCTS, headers=cashier, json=sugar(name="New")).status_code == 403


def test_role_limits_on_product_changes(client: TestClient, admin, auth_headers) -> None:
    p = client.post(PRODUCTS, headers=admin, json=sugar()).json()
    _, officer = auth_headers("inventory_officer")
    r = client.patch(f"{PRODUCTS}/{p['id']}", headers=officer, json={"selling_price": "250"})
    assert r.status_code == 200 and r.json()["selling_price"] == "250.00"
    r = client.patch(f"{PRODUCTS}/{p['id']}", headers=officer, json={"is_active": False})
    assert r.status_code == 403
    assert client.delete(f"{PRODUCTS}/{p['id']}", headers=officer).status_code == 403

    _, manager = auth_headers("store_manager")
    r = client.patch(f"{PRODUCTS}/{p['id']}", headers=manager, json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert client.get(PRODUCTS, headers=manager).json()["total"] == 0
    assert client.get(PRODUCTS, headers=manager, params={"status": "inactive"}).json()["total"] == 1


def test_quantity_cannot_be_edited_directly(client: TestClient, admin) -> None:
    p = client.post(PRODUCTS, headers=admin, json=sugar()).json()
    r = client.patch(f"{PRODUCTS}/{p['id']}", headers=admin, json={"quantity_on_hand": "999"})
    assert r.status_code == 200 and r.json()["quantity_on_hand"] == "0.000"


def test_delete_only_without_history(client: TestClient, admin) -> None:
    fresh = client.post(PRODUCTS, headers=admin, json=sugar(name="Typo product")).json()
    assert client.delete(f"{PRODUCTS}/{fresh['id']}", headers=admin).status_code == 200
    used = client.post(
        PRODUCTS, headers=admin, json=sugar(opening_stock={"quantity": "1", "unit_cost": "1"})
    ).json()
    r = client.delete(f"{PRODUCTS}/{used['id']}", headers=admin)
    assert r.status_code == 409 and r.json()["error"]["code"] == "HAS_HISTORY"


def test_search_filters_and_lookup(client: TestClient, admin) -> None:
    client.post(
        PRODUCTS,
        headers=admin,
        json=sugar(
            sku="SUG-2KG",
            barcode="5000159407236",
            opening_stock={"quantity": "5", "unit_cost": "200"},
        ),
    )
    client.post(
        PRODUCTS,
        headers=admin,
        json={
            "name": "Pishori Rice 2kg",
            "sku": "RICE-2KG",
            "selling_price": "390",
            "min_stock_level": "5",
            "opening_stock": {"quantity": "50", "unit_cost": "300"},
        },
    )
    client.post(PRODUCTS, headers=admin, json={"name": "Bottled Water 1L", "selling_price": "60"})

    def names(**params):  # type: ignore[no-untyped-def]
        return [
            p["name"] for p in client.get(PRODUCTS, headers=admin, params=params).json()["items"]
        ]

    assert names(search="sugar") == ["White Sugar 2kg"]
    assert names(search="suger") == ["White Sugar 2kg"]  # typo tolerated (trigram)
    assert names(search="rice-2kg") == ["Pishori Rice 2kg"]
    assert names(stock="low") == ["White Sugar 2kg"]
    assert names(stock="out") == ["Bottled Water 1L"]
    assert names(stock="ok") == ["Pishori Rice 2kg"]

    r = client.get(f"{PRODUCTS}/lookup", headers=admin, params={"code": "5000159407236"})
    assert r.json()["match"] == "barcode" and r.json()["product"]["sku"] == "SUG-2KG"
    r = client.get(f"{PRODUCTS}/lookup", headers=admin, params={"code": "rice-2kg"})
    assert r.json()["match"] == "sku"
    assert (
        client.get(f"{PRODUCTS}/lookup", headers=admin, params={"code": "999"}).status_code == 404
    )


def test_internal_barcode_generation_and_svg(client: TestClient, admin) -> None:
    p = client.post(PRODUCTS, headers=admin, json=sugar()).json()
    assert client.get(f"{PRODUCTS}/{p['id']}/barcode.svg", headers=admin).status_code == 422
    r = client.post(f"{PRODUCTS}/{p['id']}/barcode", headers=admin)
    assert r.status_code == 200 and r.json()["barcode"].startswith("20")
    assert client.post(f"{PRODUCTS}/{p['id']}/barcode", headers=admin).status_code == 409
    svg = client.get(f"{PRODUCTS}/{p['id']}/barcode.svg", headers=admin)
    assert svg.headers["content-type"] == "image/svg+xml" and b"<svg" in svg.content


def test_image_upload_serving_and_rejection(client: TestClient, admin) -> None:
    p = client.post(PRODUCTS, headers=admin, json=sugar()).json()
    buf = io.BytesIO()
    Image.new("RGB", (1200, 900), (200, 30, 30)).save(buf, format="JPEG")
    r = client.post(
        f"{PRODUCTS}/{p['id']}/image",
        headers=admin,
        files={"file": ("photo.jpg", buf.getvalue(), "image/jpeg")},
    )
    assert r.status_code == 200, r.text
    url = r.json()["image_url"]
    assert url.startswith("/api/v1/media/products/") and url.endswith(".webp")
    img = client.get(url)  # public, unguessable name
    assert img.status_code == 200 and img.headers["content-type"] == "image/webp"
    thumb_url = r.json()["thumbnail_url"]
    assert thumb_url == url.replace("/products/", "/products/thumbs/")
    thumb = client.get(thumb_url)
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/webp"
    assert len(thumb.content) < len(img.content)
    with Image.open(io.BytesIO(thumb.content)) as t:
        assert max(t.size) <= 160
    assert client.get("/api/v1/media/products/thumbs/..%2Fx.webp").status_code == 404

    fake = client.post(
        f"{PRODUCTS}/{p['id']}/image",
        headers=admin,
        files={"file": ("evil.jpg", b"<?php echo 1; ?>", "image/jpeg")},
    )
    assert fake.status_code == 422 and fake.json()["error"]["code"] == "INVALID_IMAGE"
    assert client.get("/api/v1/media/products/..%2F..%2Fetc%2Fpasswd").status_code == 404

    removed = client.delete(f"{PRODUCTS}/{p['id']}/image", headers=admin).json()
    assert removed["image_url"] is None and client.get(url).status_code == 404
    assert removed["thumbnail_url"] is None and client.get(thumb_url).status_code == 404


def test_product_changes_are_audited(client: TestClient, admin) -> None:
    p = client.post(PRODUCTS, headers=admin, json=sugar()).json()
    client.patch(f"{PRODUCTS}/{p['id']}", headers=admin, json={"selling_price": "250"})
    logs = client.get("/api/v1/audit-logs", headers=admin, params={"action": "product"}).json()
    update = next(i for i in logs["items"] if i["action"] == "product.update")
    assert update["before"] == {"selling_price": "245.00"} and update["after"] == {
        "selling_price": "250"
    }
