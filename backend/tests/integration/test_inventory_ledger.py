"""The stock ledger: balances, WAC, batches/FEFO, negative-stock guard, append-only rule
and concurrent updates."""

import threading
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.database import SessionLocal
from app.core.exceptions import ValidationFailed
from app.models import Product, ProductBatch, StockMovement
from app.services import inventory_service
from app.services.inventory_service import InsufficientStock, ledger_balance

D = Decimal


def out(db, user, product, qty, kind="SALE_OUT", **kw):  # type: ignore[no-untyped-def]
    ms = inventory_service.apply_movement(
        db, product_id=product.id, quantity=-D(str(qty)), movement_type=kind, user=user, **kw
    )
    db.commit()
    db.refresh(product)
    return ms


def test_receipts_update_balance_wac_and_last_cost(db, catalog) -> None:
    p = catalog.product()
    catalog.receive(p, 10, "200")
    catalog.receive(p, 30, "220")
    assert p.quantity_on_hand == D("40.000")
    assert p.avg_cost == D("215.0000")
    assert p.purchase_price == D("220.00")
    assert ledger_balance(db, p.id) == p.quantity_on_hand


def test_sale_uses_wac_and_does_not_change_it(db, catalog) -> None:
    p = catalog.product()
    catalog.receive(p, 10, "200")
    catalog.receive(p, 30, "220")
    [m] = out(db, catalog.user, p, 4)
    assert m.unit_cost == D("215.0000") and m.quantity == D("-4.000")
    assert m.balance_after == D("36.000")
    assert p.avg_cost == D("215.0000")


def test_found_stock_is_valued_at_current_wac(db, catalog) -> None:
    p = catalog.product()
    catalog.receive(p, 10, "100")
    [m] = inventory_service.apply_movement(
        db, product_id=p.id, quantity=D("2"), movement_type="ADJUSTMENT_IN", user=catalog.user
    )
    db.commit()
    db.refresh(p)
    assert m.unit_cost == D("100.0000") and p.avg_cost == D("100.0000")
    assert p.quantity_on_hand == D("12.000")


def test_negative_stock_is_blocked_without_authorisation(db, catalog) -> None:
    p = catalog.product()
    catalog.receive(p, 3, "100")
    with pytest.raises(InsufficientStock, match="3 pcs available, 5 requested"):
        out(db, catalog.user, p, 5)
    db.rollback()
    db.refresh(p)
    assert p.quantity_on_hand == D("3.000")
    assert db.scalar(select(StockMovement).where(StockMovement.quantity < 0)) is None


def test_negative_stock_allowed_when_explicitly_authorised(db, catalog) -> None:
    p = catalog.product()
    catalog.receive(p, 3, "100")
    out(db, catalog.user, p, 5, kind="ADJUSTMENT_OUT", allow_negative=True)
    assert p.quantity_on_hand == D("-2.000")
    # Receiving into negative stock resets WAC to the new cost.
    catalog.receive(p, 10, "120")
    assert p.quantity_on_hand == D("8.000") and p.avg_cost == D("120.0000")
    assert ledger_balance(db, p.id) == D("8.000")


def test_whole_units_enforced_but_weighed_goods_allow_decimals(db, catalog) -> None:
    bread = catalog.product("White Bread 400g")
    with pytest.raises(ValidationFailed, match="whole number"):
        catalog.receive(bread, "2.5", "50")
    db.rollback()
    sugar = catalog.product("Loose Sugar", unit_of_measure="kg")
    catalog.receive(sugar, "25.5", "150")
    out(db, catalog.user, sugar, "1.250")
    assert sugar.quantity_on_hand == D("24.250")


def test_direction_must_match_movement_type(db, catalog) -> None:
    p = catalog.product()
    with pytest.raises(ValidationFailed, match="must decrease"):
        inventory_service.apply_movement(
            db, product_id=p.id, quantity=D("1"), movement_type="SALE_OUT", user=catalog.user
        )
    with pytest.raises(ValidationFailed, match="unit cost is required"):
        inventory_service.apply_movement(
            db, product_id=p.id, quantity=D("1"), movement_type="PURCHASE_IN", user=catalog.user
        )


def test_expiry_tracked_products_need_expiry_on_receipt(db, catalog) -> None:
    milk = catalog.product("Fresh Milk 500ml", tracks_expiry=True)
    with pytest.raises(ValidationFailed, match="expiry"):
        catalog.receive(milk, 10, "50")
    db.rollback()
    catalog.receive(milk, 10, "50", expiry=date.today() + timedelta(days=5))
    assert milk.quantity_on_hand == D("10.000")


def test_fefo_deducts_earliest_expiry_first_and_splits_ledger(db, catalog) -> None:
    milk = catalog.product("Fresh Milk 500ml", tracks_expiry=True)
    late = date.today() + timedelta(days=9)
    soon = date.today() + timedelta(days=2)
    catalog.receive(milk, 10, "50", expiry=late, batch="B-LATE")
    catalog.receive(milk, 4, "52", expiry=soon, batch="B-SOON")

    movements = out(db, catalog.user, milk, 6)
    by_batch = {m.batch.batch_number: m.quantity for m in movements}
    assert by_batch == {"B-SOON": D("-4.000"), "B-LATE": D("-2.000")}
    assert [m.balance_after for m in movements] == [D("10.000"), D("8.000")]

    batches = {b.batch_number: b.quantity_remaining for b in db.scalars(select(ProductBatch))}
    assert batches == {"B-SOON": D("0.000"), "B-LATE": D("8.000")}
    assert ledger_balance(db, milk.id) == milk.quantity_on_hand == D("8.000")


def test_same_batch_received_twice_is_merged(db, catalog) -> None:
    milk = catalog.product("Fresh Milk 500ml", tracks_expiry=True)
    exp = date.today() + timedelta(days=7)
    catalog.receive(milk, 5, "50", expiry=exp, batch="L1")
    catalog.receive(milk, 5, "50", expiry=exp, batch="L1")
    [batch] = db.scalars(select(ProductBatch)).all()
    assert batch.quantity_received == D("10.000") == batch.quantity_remaining


def test_specific_batch_deduction_checks_batch_quantity(db, catalog) -> None:
    milk = catalog.product("Fresh Milk 500ml", tracks_expiry=True)
    catalog.receive(milk, 3, "50", expiry=date.today() + timedelta(days=2), batch="A")
    catalog.receive(milk, 9, "50", expiry=date.today() + timedelta(days=8), batch="B")
    batch_a = db.scalar(select(ProductBatch).where(ProductBatch.batch_number == "A"))
    with pytest.raises(InsufficientStock, match="only 3"):
        out(db, catalog.user, milk, 5, kind="DAMAGED", batch_id=batch_a.id)


def test_ledger_is_append_only(db, catalog) -> None:
    p = catalog.product()
    [m] = catalog.receive(p, 5, "100")
    for sql in (
        "UPDATE stock_movements SET quantity = 50 WHERE id = :i",
        "DELETE FROM stock_movements WHERE id = :i",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            db.execute(text(sql), {"i": m.id})
        db.rollback()


def test_concurrent_sales_cannot_oversell(db, catalog) -> None:
    """Two tills sell 6 of the last 10 at the same moment: one must fail."""
    p = catalog.product()
    catalog.receive(p, 10, "100")
    user_id = catalog.user.id
    barrier = threading.Barrier(2)
    results: list[str] = []

    def sell() -> None:
        with SessionLocal() as s:
            from app.models import User

            user = s.get(User, user_id)
            barrier.wait()
            try:
                inventory_service.apply_movement(
                    s, product_id=p.id, quantity=D("-6"), movement_type="SALE_OUT", user=user
                )
                s.commit()
                results.append("ok")
            except InsufficientStock:
                s.rollback()
                results.append("insufficient")

    threads = [threading.Thread(target=sell) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    assert sorted(results) == ["insufficient", "ok"]
    db.expire_all()
    fresh = db.get(Product, p.id)
    assert fresh.quantity_on_hand == D("4.000") == ledger_balance(db, p.id)


def test_many_concurrent_small_sales_keep_ledger_consistent(db, catalog) -> None:
    p = catalog.product()
    catalog.receive(p, 100, "100")
    user_id = catalog.user.id

    def sell_three_times() -> None:
        from app.models import User

        with SessionLocal() as s:
            user = s.get(User, user_id)
            for _ in range(3):
                inventory_service.apply_movement(
                    s, product_id=p.id, quantity=D("-1"), movement_type="SALE_OUT", user=user
                )
                s.commit()

    threads = [threading.Thread(target=sell_three_times) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    db.expire_all()
    fresh = db.get(Product, p.id)
    assert fresh.quantity_on_hand == D("85.000") == ledger_balance(db, p.id)
    balances = sorted(
        m.balance_after
        for m in db.scalars(select(StockMovement).where(StockMovement.movement_type == "SALE_OUT"))
    )
    assert balances == [D(n) for n in range(85, 100)]  # every running balance is distinct
