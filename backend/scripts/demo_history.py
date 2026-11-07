"""Simulate a SYNTHETIC trading history for the demo store.

Everything goes through the real services (checkout, goods received, returns, ledger), so
the generated data obeys every rule the live system enforces: stock never goes negative,
costs follow the weighted average, perishables are sold oldest-expiry-first and expired
leftovers are written off.

Demand pattern (invented, but shaped like a Kenyan neighbourhood supermarket):
* base daily rate per product, Poisson-distributed;
* weekends about 25% busier;
* month-end payday (28th to 2nd) about 35% busier;
* lost sales when a product is out of stock (the customer simply doesn't buy it);
* ordinary back-office noise: small count corrections, the odd damaged item, customer
  returns (mostly taken by the cashier and approved by the manager).

For testing the anomaly detector, a few IRREGULARITIES are injected (shrinkage bursts,
bursts of small adjustments, refund spikes, damage spikes). They are recorded through the
normal services, exactly like real events, and their ground truth is returned separately
(`stats["anomaly_labels"]`) so the detector never sees it.

The random generator is seeded, so the same command produces the same data.
"""

import math
import random
import string
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Expense, ExpenseCategory, Product, ProductBatch, User
from app.schemas.procurement import GoodsReceivedCreate, GRNLine
from app.schemas.sales import CartLine, CheckoutRequest, ReturnCreate, ReturnLine
from app.schemas.stock import AdjustmentCreate
from app.services import inventory_service, procurement_service, sales_service, stock_service
from app.services.audit_service import RequestContext

D = Decimal
CTX = RequestContext(ip_address="127.0.0.1", user_agent="demo history generator")


@dataclass
class Demand:
    daily: float  # average units per day
    shelf_days: int | None = None  # perishables
    restock_every: int | None = None  # perishables are delivered on a schedule
    max_per_sale: int = 2
    weighed: bool = False  # sold by weight (kg)


DEMAND = {
    "White Sugar 2kg": Demand(9),
    "Pishori Rice 2kg": Demand(5),
    "Vegetable Cooking Oil 1L": Demand(6),
    "Maize Flour 2kg": Demand(14, max_per_sale=3),
    "Fresh Milk 500ml": Demand(22, shelf_days=7, restock_every=2, max_per_sale=4),
    "White Bread 400g": Demand(16, shelf_days=4, restock_every=1, max_per_sale=2),
    "Bar Soap 800g": Demand(4),
    "Bottled Water 1L": Demand(11, max_per_sale=6),
    "Loose Sugar (per kg)": Demand(6, weighed=True),
    "Natural Yoghurt 500ml": Demand(4, shelf_days=14, restock_every=4),
}


def _day_factor(d: date) -> float:
    f = 1.0
    if d.weekday() >= 5:
        f *= 1.25
    if d.day >= 28 or d.day <= 2:
        f *= 1.35
    return f


ANOMALY_KINDS = ("SHRINKAGE_BURST", "DAMAGE_SPIKE", "REFUND_SPIKE", "ADJUSTMENT_BURST")
# Shelf-stable products only: perishables have their own write-off pattern.
ANOMALY_PRODUCTS = (
    "White Sugar 2kg",
    "Vegetable Cooking Oil 1L",
    "Pishori Rice 2kg",
    "Bar Soap 800g",
    "Bottled Water 1L",
    "Maize Flour 2kg",
)


@dataclass
class Episode:
    kind: str
    start: date
    days: int
    product: str | None


def plan_anomalies(rng: random.Random, start: date, end: date) -> list[Episode]:
    """Spread a few irregularities over the period (none in the first 30 days, so every
    product has a normal history first; the last two fall in the final week)."""
    total = (end - start).days + 1
    if total < 45:
        return []
    count = max(4, total // 30)
    first, last = start + timedelta(days=30), end - timedelta(days=9)
    span = max((last - first).days, 1)
    out = []
    for k in range(count):
        kind = ANOMALY_KINDS[k % len(ANOMALY_KINDS)]
        day = (
            first + timedelta(days=int(span * k / max(count - 2, 1)))
            if k < count - 2
            else (end - timedelta(days=6 - 3 * (k - count + 2)))
        )
        product = rng.choice(ANOMALY_PRODUCTS) if kind != "REFUND_SPIKE" else None
        out.append(Episode(kind, min(day, end), 3 if kind == "SHRINKAGE_BURST" else 1, product))
    return out


def _poisson(rng: random.Random, lam: float) -> int:
    # Knuth's method is fine for the small rates used here.
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _mpesa_code(rng: random.Random) -> str:
    return "".join(rng.choice(string.ascii_uppercase + string.digits) for _ in range(10))


def _at(d: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(d, time(hour, minute), ZoneInfo(get_settings().store_timezone))


def simulate(db: Session, *, start: date, end: date, seed: int = 42, log=print) -> dict:  # type: ignore[no-untyped-def]
    rng = random.Random(seed)  # noqa: S311 - reproducible simulation, not security
    products = {p.name: p for p in db.scalars(select(Product).where(Product.is_active))}
    cashier = db.scalar(select(User).where(User.username == "cashier"))
    manager = db.scalar(select(User).where(User.username == "manager"))
    officer = db.scalar(select(User).where(User.username == "inventory")) or manager
    if not (cashier and manager and officer):
        raise RuntimeError("Run seed_demo_users first")
    cats = {c.name: c.id for c in db.scalars(select(ExpenseCategory))}

    # Supplier cost per product; cooking oil's cost jumps 12% halfway (a price-change event).
    cost = {name: p.avg_cost for name, p in products.items() if name in DEMAND}
    price_jump_day = start + (end - start) / 2
    stats = {"sales": 0, "deliveries": 0, "expired_write_offs": 0, "returns": 0, "lost_sales": 0}
    noise = random.Random(seed + 1)  # noqa: S311 - back-office noise and injected irregularities
    episodes = plan_anomalies(noise, start, end)
    labels: list[dict] = []

    def label(ep: Episode, entity: str, name: str, day: date, detail: str) -> None:
        labels.append(
            {
                "kind": ep.kind,
                "entity": entity,
                "name": name,
                "date": day.isoformat(),
                "detail": detail,
            }
        )

    def adjust(p: Product, change: int, user: User, when: datetime, note: str) -> bool:
        db.refresh(p)
        if change < 0 and p.quantity_on_hand + change < 0:
            return False
        stock_service.create_adjustment(
            db,
            AdjustmentCreate(
                product_id=p.id,
                quantity_change=D(change),
                reason_code="COUNT_CORRECTION",
                notes=note,
            ),
            user,
            CTX,
            at=when,
        )
        return True

    def damage(p: Product, qty: int, when: datetime, note: str) -> bool:
        db.refresh(p)
        if p.quantity_on_hand < qty:
            return False
        inventory_service.apply_movement(
            db,
            product_id=p.id,
            quantity=-D(qty),
            movement_type="DAMAGED",
            user=officer,
            reference_type="write_off",
            reason=f"Damaged goods: {note}",
            occurred_at=when,
        )
        db.commit()
        return True

    d = start
    while d <= end:
        # 1) Write off perishables that expired before today.
        for batch in db.scalars(
            select(ProductBatch).where(
                ProductBatch.quantity_remaining > 0, ProductBatch.expiry_date < d
            )
        ).all():
            inventory_service.apply_movement(
                db,
                product_id=batch.product_id,
                quantity=-batch.quantity_remaining,
                movement_type="EXPIRED",
                user=officer,
                batch_id=batch.id,
                reference_type="write_off",
                reason="Expired goods (demo)",
                occurred_at=_at(d, 7, 30),
            )
            stats["expired_write_offs"] += 1
        db.commit()

        # 2) Morning deliveries: perishables on schedule, others when at/below minimum.
        if d >= price_jump_day and "Vegetable Cooking Oil 1L" in cost:
            base = products["Vegetable Cooking Oil 1L"].purchase_price
            cost["Vegetable Cooking Oil 1L"] = (base * D("1.12")).quantize(D("0.01"))
            price_jump_day = end + timedelta(days=9999)  # only once
        by_supplier: dict[int, list[GRNLine]] = {}
        for name, demand in DEMAND.items():
            p = products.get(name)
            if p is None:
                continue
            db.refresh(p)
            due = demand.restock_every is not None and (d - start).days % demand.restock_every == 0
            low = p.quantity_on_hand <= p.min_stock_level
            if not (due or low):
                continue
            if demand.restock_every:
                # Expected units until the next delivery (+25% safety stock).
                units = demand.daily * (1 + demand.max_per_sale) / 2 * demand.restock_every
                need = D(math.ceil(units * 1.25)) - p.quantity_on_hand
            else:
                need = (p.max_stock_level or p.min_stock_level * 4) - p.quantity_on_hand
            if need <= 0:
                continue
            need = need.quantize(D("1"), ROUND_HALF_UP)
            drift = D(str(round(rng.uniform(0.98, 1.03), 3)))
            unit_cost = (cost.get(name, p.purchase_price or D(1)) * drift).quantize(D("0.01"))
            by_supplier.setdefault(p.default_supplier_id, []).append(
                GRNLine(
                    product_id=p.id,
                    quantity=need,
                    unit_cost=unit_cost,
                    expiry_date=d + timedelta(days=demand.shelf_days)
                    if demand.shelf_days
                    else None,
                    batch_number=f"L{d:%y%m%d}" if demand.shelf_days else None,
                )
            )
        for supplier_id, lines in by_supplier.items():
            procurement_service.receive_goods(
                db,
                GoodsReceivedCreate(
                    supplier_id=supplier_id,
                    supplier_invoice_number=f"DEMO-{d:%Y%m%d}-{supplier_id}",
                    invoice_date=d,
                    items=lines,
                    notes="Synthetic demo delivery",
                ),
                officer,
                CTX,
                received_at=_at(d, 8, rng.randint(0, 50)),
            )
            stats["deliveries"] += 1

        # 3) Sales through the day.
        factor = _day_factor(d)
        wanted: list[tuple[int, str]] = []  # (minute of day, product)
        for name, demand in DEMAND.items():
            if name not in products:
                continue
            for _ in range(_poisson(rng, demand.daily * factor)):
                wanted.append((rng.randint(7 * 60, 21 * 60), name))
        wanted.sort()
        # Group neighbouring wants into baskets of 1-4 products.
        i = 0
        sales_today: list = []
        while i < len(wanted):
            size = rng.choice((1, 1, 2, 2, 3, 4))
            basket = wanted[i : i + size]
            i += size
            minute = basket[0][0]
            lines: dict[int, D] = {}
            for _, name in basket:
                p, demand = products[name], DEMAND[name]
                q = (
                    D(str(rng.choice((0.5, 1, 1, 1.5, 2))))
                    if demand.weighed
                    else D(rng.randint(1, demand.max_per_sale))
                )
                lines[p.id] = lines.get(p.id, D(0)) + q
            # Drop lines the shelf can't satisfy (lost sales).
            ok_lines = []
            for pid, q in lines.items():
                p = db.get(Product, pid)
                db.refresh(p)
                if p.quantity_on_hand >= q:
                    ok_lines.append(CartLine(product_id=pid, quantity=q))
                else:
                    stats["lost_sales"] += 1
            if not ok_lines:
                continue
            method = rng.choices(("MPESA", "CASH", "CARD"), weights=(48, 44, 8))[0]
            user = manager if rng.random() < 0.1 else cashier
            req = CheckoutRequest(
                client_request_id=uuid.uuid4(),
                items=ok_lines,
                payment_method=method,
                amount_tendered=D("100000") if method == "CASH" else None,
                payment_reference=_mpesa_code(rng) if method == "MPESA" else None,
                notes="demo",
            )
            sale, _ = sales_service.checkout(
                db, req, user, CTX, sold_at=_at(d, minute // 60, minute % 60)
            )
            # Cash change computed against an inflated tender; tidy it to a realistic note.
            if method == "CASH":
                paid = (sale.grand_total / 50).to_integral_value(rounding=ROUND_CEILING) * 50
                sale.amount_tendered = paid
                sale.change_given = paid - sale.grand_total
                db.commit()
            sales_today.append(sale)
            stats["sales"] += 1

        # 4) Occasional customer returns (about 1 in 150 sales). The cashier takes most of
        #    them at the counter and the manager approves them.
        def refund(sale, by_cashier: bool, when: datetime, reason: str | None = None) -> None:  # type: ignore[no-untyped-def]
            item = sale.items[0]
            body = ReturnCreate(
                items=[
                    ReturnLine(
                        sale_item_id=item.id,
                        quantity=D("1") if item.quantity >= 1 else item.quantity,
                        condition=rng.choice(("RESALEABLE", "DAMAGED")),
                    )
                ],
                reason=reason or rng.choice(("Wrong item", "Damaged packaging", "Changed mind")),
                refund_method=sale.payment_method,
            )
            if by_cashier and sale.cashier_id == cashier.id:
                ret, _ = sales_service.create_return(db, sale, body, cashier, CTX, at=when)
                sales_service.approve_return(
                    db, ret, manager, CTX, None, at=when + timedelta(minutes=5)
                )
            else:
                sales_service.create_return(db, sale, body, manager, CTX, at=when)
            stats["returns"] += 1

        for sale in sales_today:
            if rng.random() < 1 / 150:
                refund(sale, noise.random() < 0.7, _at(d, 20, 30))

        # 4b) Everyday back-office noise: small count corrections and the odd breakage.
        stocked = [
            p
            for n, p in products.items()
            if n in DEMAND and not DEMAND[n].weighed and not DEMAND[n].shelf_days
        ]
        if noise.random() < 0.10:
            p = noise.choice(stocked)
            change = noise.choice((-2, -1, -1, -1, 1, 1, 2))
            adjust(p, change, officer, _at(d, 18, noise.randint(0, 59)), "Routine shelf count")
        if noise.random() < 0.06:
            p = noise.choice(stocked)
            damage(p, noise.choice((1, 1, 2)), _at(d, 12, noise.randint(0, 59)), "dropped/torn")

        # 4c) Injected irregularities (ground truth kept separately in `labels`).
        for ep in episodes:
            if not (ep.start <= d < ep.start + timedelta(days=ep.days)):
                continue
            p = products.get(ep.product) if ep.product else None
            when = _at(d, 19, noise.randint(0, 50))
            if ep.kind == "SHRINKAGE_BURST" and p is not None:
                qty = noise.randint(6, 12)
                if adjust(p, -qty, officer, when, "Count correction"):
                    label(ep, "product", p.name, d, f"{qty} units adjusted out")
                    label(ep, "user", officer.username, d, f"{qty} units of {p.name} adjusted out")
            elif ep.kind == "ADJUSTMENT_BURST" and p is not None:
                n = noise.randint(6, 9)
                done = sum(
                    adjust(p, -1, officer, when + timedelta(minutes=7 * i), "Count correction")
                    for i in range(n)
                )
                if done:
                    label(ep, "product", p.name, d, f"{done} separate one-unit adjustments")
                    label(ep, "user", officer.username, d, f"{done} adjustments of {p.name}")
            elif ep.kind == "DAMAGE_SPIKE" and p is not None:
                qty = noise.randint(10, 18)
                if damage(p, qty, when, "damaged in store"):
                    label(ep, "product", p.name, d, f"{qty} units written off as damaged")
            elif ep.kind == "REFUND_SPIKE":
                own = [s_ for s_ in sales_today if s_.cashier_id == cashier.id]
                n = min(len(own), noise.randint(6, 9))
                for i, sale in enumerate(noise.sample(own, n)):
                    refund(sale, True, _at(d, 20, 35 + i), "Customer returned item")
                if n:
                    label(ep, "user", cashier.username, d, f"{n} refunds in one day")

        # 5) Running costs.
        def expense(category: str, amount: str, text: str, day: date = d) -> None:
            if category in cats:
                db.add(
                    Expense(
                        category_id=cats[category],
                        expense_date=day,
                        amount=D(amount),
                        description=f"{text} (demo)",
                        payment_method="BANK",
                        recorded_by_id=manager.id,
                    )
                )

        if d.day == 1:
            expense("Rent", "30000", f"Shop rent {d:%B %Y}")
        if d.day == 15:
            expense("Electricity", str(rng.randint(6500, 9000)), "Electricity tokens")
            expense("Water", str(rng.randint(900, 1500)), "Water bill")
        if d.day == 28:
            expense("Salaries and wages", "54000", f"Staff salaries {d:%B %Y}")
        if d.weekday() == 0:
            expense(
                "Transport and delivery", str(rng.randint(800, 2000)), "Delivery motorbike fuel"
            )
        db.commit()

        if (d - start).days % 30 == 0:
            log(f"  {d}: {stats['sales']} sales so far")
        d += timedelta(days=1)
    stats["anomaly_labels"] = labels  # type: ignore[assignment]
    return stats
