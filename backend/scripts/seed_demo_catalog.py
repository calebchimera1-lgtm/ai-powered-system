"""Load a small SYNTHETIC supermarket catalogue for demonstrations.

    python -m scripts.seed_demo_catalog                     # catalogue only
    python -m scripts.seed_demo_catalog --history-days 90   # plus 90 days of trading

Creates categories, demo suppliers and the products named in the project brief (sugar,
rice, cooking oil, maize flour, milk, bread, soap, bottled water) plus a few more, with
opening stock, expiry batches, and a couple of stock events so every screen has data.
All names marked "(Demo)" and every price/quantity are invented, not real business data.
Barcodes use the in-store 20-prefix range, so they cannot clash with real products.

Run seed_demo_users first. Refuses to run in production or if products already exist.
"""

import argparse
import json
import sys
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import Category, Product, Supplier, SupplierProduct, User
from app.schemas.catalog import OpeningStock, ProductCreate
from app.schemas.stock import AdjustmentCreate, WriteOffCreate
from app.services import inventory_service, product_service, stock_service
from app.services.audit_service import RequestContext
from app.utils.barcodes import internal_ean13
from scripts.demo_history import simulate

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

# Illustrative VAT setting only (not tax advice): staples such as these are commonly
# zero-rated or exempt in Kenya, so the demo sells them without VAT.
ZERO_VAT = {"Maize Flour 2kg", "White Bread 400g", "Fresh Milk 500ml"}

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
    parser = argparse.ArgumentParser(description="Seed the synthetic demo catalogue")
    parser.add_argument(
        "--history-days",
        type=int,
        default=0,
        help="Also simulate this many days of trading (sales, deliveries, returns, expenses)",
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="Random seed for the simulated history"
    )
    args = parser.parse_args()
    if not 0 <= args.history_days <= 730:
        print("--history-days must be between 0 and 730", file=sys.stderr)
        return 2
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
        history = args.history_days
        start = today - timedelta(days=history)
        for i, (name, cat, sup, unit, sell, cost, qty, mn, mx, exp) in enumerate(PRODUCTS, 1):
            if history and not qty:
                qty = mx // 2  # the simulation starts with some stock of everything
            opening = None
            if qty and history:
                opening = None  # recorded below, dated at the start of the history
            elif qty:
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
                    vat_rate=D(0) if name in ZERO_VAT else D(16),
                    description="Synthetic demo product",
                ),
                admin,
                CTX,
            )
            if qty and history:
                inventory_service.apply_movement(
                    db,
                    product_id=p.id,
                    quantity=D(str(qty)),
                    movement_type="OPENING",
                    user=admin,
                    unit_cost=D(cost),
                    batch_info=inventory_service.BatchInfo(
                        f"LOT-{i:03d}0", start + timedelta(days=min(exp, 3)) if exp else None
                    ),
                    reference_type="product",
                    reference_id=p.id,
                    reason="Opening stock",
                    occurred_at=datetime.combine(start, time(6, 0), ZoneInfo("Africa/Nairobi")),
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

        if history:
            print(f"Simulating {history} days of trading from {start} (this takes a while)...")
            stats = simulate(db, start=start, end=today - timedelta(days=1), seed=args.seed)
            labels = stats.pop("anomaly_labels", [])
            print("  " + ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in stats.items()))
            if labels:
                # Ground truth for scripts/evaluate_anomalies.py, kept out of the database
                # so the detector cannot see it.
                path = Path(get_settings().storage_dir) / "demo" / "anomaly-ground-truth.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"synthetic": True, "labels": labels}, indent=2))
                print(f"  {len(labels)} injected irregularities (ground truth: {path})")

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
