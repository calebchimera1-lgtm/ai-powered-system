"""Load a small SYNTHETIC supermarket catalogue for demonstrations.

    python -m scripts.seed_demo_catalog

Creates categories, demo suppliers and the products named in the project brief (sugar,
rice, cooking oil, maize flour, milk, bread, soap, bottled water) plus a few more, with
opening stock, expiry batches, and a couple of stock events so every screen has data.
All names marked "(Demo)" and every price/quantity are invented, not real business data.
Barcodes use the in-store 20-prefix range, so they cannot clash with real products.

Run seed_demo_users first. Refuses to run in production or if products already exist.
"""

import sys
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import Category, Product, Supplier, SupplierProduct, User
from app.schemas.catalog import OpeningStock, ProductCreate
from app.schemas.stock import AdjustmentCreate, WriteOffCreate
from app.services import inventory_service, product_service, stock_service
from app.services.audit_service import RequestContext
from app.utils.barcodes import internal_ean13

D = Decimal
CTX = RequestContext(ip_address="127.0.0.1", user_agent="seed_demo_catalog")

CATEGORIES = {
    "Food": None,
    "Dry goods": "Food",
    "Dairy": "Food",
    "Bakery": "Food",
    "Beverages": None,
    "Household": None,
    "Cleaning": "Household",
}

SUPPLIERS = [
    ("Nairobi Wholesale Distributors (Demo)", "P051111111A", "Jane Achieng", "+254 711 000 101"),
    ("Rift Valley Dairy Co-op (Demo)", "P052222222B", "Samuel Kiptoo", "+254 722 000 202"),
    ("Coast Household Supplies (Demo)", "P053333333C", "Halima Said", "+254 733 000 303"),
]

# name, category, supplier index, unit, sell, cost, opening qty, min, max, expiry days
PRODUCTS = [
    ("White Sugar 2kg", "Dry goods", 0, "pcs", "245", "198", 46, 15, 150, None),
    ("Pishori Rice 2kg", "Dry goods", 0, "pcs", "390", "305", 32, 10, 100, None),
    ("Vegetable Cooking Oil 1L", "Dry goods", 0, "pcs", "350", "281", 8, 12, 80, None),
    ("Maize Flour 2kg", "Dry goods", 0, "pcs", "180", "142", 64, 20, 200, None),
    ("Fresh Milk 500ml", "Dairy", 1, "pcs", "65", "48", 36, 24, 120, 4),
    ("White Bread 400g", "Bakery", 1, "pcs", "70", "52", 18, 10, 60, 3),
    ("Bar Soap 800g", "Cleaning", 2, "pcs", "185", "139", 40, 10, 90, None),
    ("Bottled Water 1L", "Beverages", 2, "pcs", "60", "38", 0, 24, 240, None),
    ("Loose Sugar (per kg)", "Dry goods", 0, "kg", "125", "98", D("25.5"), 10, 100, None),
    ("Natural Yoghurt 500ml", "Dairy", 1, "pcs", "150", "112", 14, 6, 40, 12),
]


def main() -> int:
    if get_settings().is_production:
        print("Refusing to seed demo data in production.", file=sys.stderr)
        return 1
    with SessionLocal() as db:
        if db.scalar(select(func.count(Product.id))):
            print("Products already exist; not seeding the demo catalogue.", file=sys.stderr)
            return 1
        admin = db.scalar(select(User).where(User.username == "admin")) or db.scalar(
            select(User).order_by(User.id)
        )
        officer = db.scalar(select(User).where(User.username == "inventory")) or admin
        if admin is None:
            print("Create users first (seed_demo_users).", file=sys.stderr)
            return 1

        cats: dict[str, Category] = {}
        for name, parent in CATEGORIES.items():
            cats[name] = Category(name=name, parent=cats.get(parent) if parent else None)
            db.add(cats[name])
        suppliers = [
            Supplier(
                name=n,
                kra_pin=pin,
                contact_person=c,
                phone=ph,
                payment_terms_days=30,
                notes="Synthetic demo supplier",
            )
            for n, pin, c, ph in SUPPLIERS
        ]
        db.add_all(suppliers)
        db.commit()

        today = date.today()
        for i, (name, cat, sup, unit, sell, cost, qty, mn, mx, exp) in enumerate(PRODUCTS, 1):
            opening = None
            if qty:
                opening = OpeningStock(
                    quantity=D(str(qty)),
                    unit_cost=D(cost),
                    expiry_date=today + timedelta(days=exp) if exp else None,
                    batch_number=f"LOT-{i:03d}A" if exp else None,
                )
            p = product_service.create_product(
                db,
                ProductCreate(
                    name=name,
                    category_id=cats[cat].id,
                    default_supplier_id=suppliers[sup].id,
                    unit_of_measure=unit,
                    selling_price=D(sell),
                    min_stock_level=D(mn),
                    max_stock_level=D(mx),
                    tracks_expiry=exp is not None,
                    opening_stock=opening,
                    description="Synthetic demo product",
                ),
                admin,
                CTX,
            )
            p.barcode = internal_ean13(p.id)
            db.add(
                SupplierProduct(
                    supplier_id=suppliers[sup].id,
                    product_id=p.id,
                    supplier_sku=f"S{sup + 1}-{i:03d}",
                    last_unit_price=D(cost),
                    lead_time_days=2 if exp else 5,
                )
            )
            db.commit()

        # A few events so the ledger, batches and approvals screens have something to show.
        milk = db.scalar(select(Product).where(Product.name == "Fresh Milk 500ml"))
        inventory_service.apply_movement(
            db,
            product_id=milk.id,
            quantity=D("24"),
            movement_type="PURCHASE_IN",
            user=officer,
            unit_cost=D("50"),
            batch_info=inventory_service.BatchInfo("LOT-005B", today + timedelta(days=9)),
            reference_type="demo",
            reason="Delivery (demo)",
        )
        db.commit()
        stock_service.write_off(
            db,
            WriteOffCreate(
                product_id=milk.id, quantity=D("2"), kind="DAMAGED", notes="Leaking packets (demo)"
            ),
            officer,
            CTX,
        )
        soap = db.scalar(select(Product).where(Product.name == "Bar Soap 800g"))
        stock_service.create_adjustment(
            db,
            AdjustmentCreate(
                product_id=soap.id,
                counted_quantity=D("38"),
                reason_code="COUNT_CORRECTION",
                notes="Shelf count (demo)",
            ),
            officer,
            CTX,
        )
        rice = db.scalar(select(Product).where(Product.name == "Pishori Rice 2kg"))
        stock_service.create_adjustment(
            db,
            AdjustmentCreate(
                product_id=rice.id,
                quantity_change=D("-20"),
                reason_code="THEFT_SUSPECTED",
                notes="Bags missing after weekend delivery (demo)",
            ),
            officer,
            CTX,
        )

    print(f"Demo catalogue created: {len(PRODUCTS)} products, {len(SUPPLIERS)} suppliers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
