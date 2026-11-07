"""Plain data types passed between OCR pipeline stages (no database, no HTTP)."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass
class Word:
    text: str
    conf: float  # 0-100 from the OCR engine (100 for PDF text layers)
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def cx(self) -> float:
        return self.left + self.width / 2

    @property
    def cy(self) -> float:
        return self.top + self.height / 2


@dataclass
class Line:
    words: list[Word]
    page: int = 1

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def conf(self) -> float:
        return sum(w.conf for w in self.words) / len(self.words) if self.words else 0.0

    @property
    def top(self) -> int:
        return min(w.top for w in self.words)

    @property
    def bottom(self) -> int:
        return max(w.bottom for w in self.words)


@dataclass
class Quality:
    """Image quality measurements used to warn about photos that are hard to read."""

    blur: float = 0.0  # variance of the Laplacian; higher = sharper
    brightness: float = 0.0  # mean grey level 0-255
    contrast: float = 0.0  # standard deviation of grey levels
    width: int = 0
    height: int = 0
    skew_degrees: float = 0.0
    document_detected: bool = False
    score: float = 1.0  # 0..1 overall
    problems: list[str] = field(default_factory=list)


@dataclass
class Field:
    value: str | Decimal | date | None
    confidence: float  # 0..1
    source: str = ""  # the text it was read from


@dataclass
class ExtractedItem:
    raw_text: str
    description: str
    quantity: Decimal | None
    unit_price: Decimal | None
    line_total: Decimal | None
    item_code: str | None = None
    confidence: float = 0.0
    arithmetic_ok: bool = False


@dataclass
class Extraction:
    supplier_name: Field
    kra_pin: Field
    invoice_number: Field
    invoice_date: Field
    subtotal: Field
    tax_total: Field
    grand_total: Field
    items: list[ExtractedItem]
    vat_rate: Decimal | None = None
    prices_include_vat: bool = False
    header_lines: list[str] = field(default_factory=list)
