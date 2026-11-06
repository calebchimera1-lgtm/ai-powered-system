"""Human-readable document numbers such as RCPT-2026-000123.

Numbers come from PostgreSQL sequences, so they are unique even with several tills
checking out at once. A sequence never reuses a number, so a rolled-back sale leaves a
gap; that is normal and auditors expect it.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings

KINDS = {
    "sale": ("RCPT", "sale_receipt_seq"),
    "return": ("RTN", "sale_return_seq"),
    "purchase_order": ("PO", "purchase_order_seq"),
    "goods_received": ("GRN", "goods_received_seq"),
}


def next_number(db: Session, kind: str) -> str:
    prefix, sequence = KINDS[kind]
    value = db.execute(text(f"SELECT nextval('{sequence}')")).scalar_one()
    year = datetime.now(ZoneInfo(get_settings().store_timezone)).year
    return f"{prefix}-{year}-{value:06d}"
