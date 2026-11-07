"""Match extracted text to registered suppliers and products.

Products, in order (the first confident answer wins):
1. Code: the supplier's own product code (from Supplier products) or the barcode/SKU.
2. Alias: the exact description this supplier used before, learnt from approved invoices.
3. Fuzzy: RapidFuzz similarity after normalising units ("2 KG" -> "2KG", "1LTR" -> "1L")
   and expanding abbreviations against the product's words ("WHT" -> "WHITE"). Pack sizes
   must agree: "Sugar 1kg" is never matched to "Sugar 2kg".

Scores: >= 88 is treated as a match, 65-87 as a suggestion the reviewer must confirm,
below 65 as an unknown (possibly new) product.
"""

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

MATCH = 88
SUGGEST = 65

_UNIT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(KGS?|KILO|G|GMS?|GRAMS?|LTRS?|LITRES?|LT|L|ML|PCS?|PK)\b"
)
_UNIT_MAP = {
    "KGS": "KG",
    "KILO": "KG",
    "GMS": "G",
    "GM": "G",
    "GRAM": "G",
    "GRAMS": "G",
    "LTRS": "L",
    "LTR": "L",
    "LITRES": "L",
    "LITRE": "L",
    "LT": "L",
    "PCS": "PC",
}
_NOISE = re.compile(r"[^A-Z0-9 ]+")


@dataclass(frozen=True)
class SupplierRef:
    id: int
    name: str
    kra_pin: str | None


@dataclass(frozen=True)
class ProductRef:
    id: int
    name: str
    sku: str
    barcode: str | None


@dataclass
class ProductMatch:
    product_id: int | None
    method: str  # CODE, ALIAS, FUZZY, NONE
    score: float
    suggestion_only: bool = False


_LOOKALIKE_SIZE = re.compile(r"\b[IL|!]((?:\d)*)\s?(L|LT|LTR|KG|ML|G)\b")


def normalise(text: str) -> str:
    t = text.upper()
    # OCR reads "1L" as "IL"/"iL"/"lL": fix a look-alike 1 directly before a unit.
    t = _LOOKALIKE_SIZE.sub(lambda m: f"1{m.group(1)}{m.group(2)}", t)
    t = _UNIT_RE.sub(lambda m: f"{m.group(1)}{_UNIT_MAP.get(m.group(2), m.group(2))} ", t)
    t = _NOISE.sub(" ", t)
    return " ".join(t.split())


def sizes(text: str) -> set[str]:
    return {
        tok
        for tok in normalise(text).split()
        if re.fullmatch(r"\d+(?:\.\d+)?(KG|G|L|ML|PC|PK)", tok)
    }


def _expand(desc_tokens: list[str], name_tokens: list[str]) -> list[str]:
    """Replace abbreviations by the product word they start (WHT->WHITE needs a
    consonant-skeleton check; SUG->SUGAR is a plain prefix)."""
    out = []
    for tok in desc_tokens:
        if len(tok) >= 3 and tok.isalpha():
            for nt in name_tokens:
                if nt.startswith(tok) or (len(tok) >= 3 and _skeleton(nt).startswith(tok)):
                    tok = nt
                    break
        out.append(tok)
    return out


def _skeleton(word: str) -> str:
    """Word without vowels after the first letter: WHITE -> WHT, FLOUR -> FLR."""
    return word[:1] + re.sub(r"[AEIOU]", "", word[1:])


def score_product(description: str, name: str) -> float:
    d, n = normalise(description), normalise(name)
    d_sizes, n_sizes = sizes(d), sizes(n)
    if d_sizes and n_sizes and not (d_sizes & n_sizes):
        return 0.0  # different pack size: never the same product
    n_tokens = n.split()
    d_expanded = " ".join(_expand(d.split(), n_tokens))
    score = max(fuzz.token_set_ratio(d_expanded, n), fuzz.token_sort_ratio(d_expanded, n))
    if d_sizes and d_sizes == n_sizes:
        score = min(100.0, score + 5)
    return round(score, 1)


def match_product(
    description: str,
    item_code: str | None,
    raw_text: str,
    products: list[ProductRef],
    *,
    aliases: dict[str, int] | None = None,
    supplier_codes: dict[str, int] | None = None,
) -> ProductMatch:
    """`aliases` and `supplier_codes` are for the invoice's supplier only."""
    tokens = {t.strip(".,:;").upper() for t in raw_text.split()}
    if item_code and supplier_codes and item_code.upper() in supplier_codes:
        return ProductMatch(supplier_codes[item_code.upper()], "CODE", 100.0)
    for p in products:
        if (p.barcode and p.barcode in tokens) or (p.sku and p.sku.upper() in tokens):
            return ProductMatch(p.id, "CODE", 100.0)
    norm = normalise(description)
    if aliases and norm in aliases:
        return ProductMatch(aliases[norm], "ALIAS", 100.0)
    best_id, best = None, 0.0
    for p in products:
        s = score_product(description, p.name)
        if s > best:
            best_id, best = p.id, s
    if best >= MATCH:
        return ProductMatch(best_id, "FUZZY", best)
    if best >= SUGGEST:
        return ProductMatch(best_id, "FUZZY", best, suggestion_only=True)
    return ProductMatch(None, "NONE", best)


def match_supplier(
    pin: str | None, name: str | None, header_lines: list[str], suppliers: list[SupplierRef]
) -> tuple[int | None, float, str]:
    """(supplier_id, score 0-100, method). A KRA PIN match is near-certain."""
    if pin:
        for s in suppliers:
            if s.kra_pin and s.kra_pin.upper() == pin.upper():
                return s.id, 100.0, "PIN"
    best_id, best = None, 0.0
    texts = [t for t in [name, *header_lines] if t]
    for s in suppliers:
        target = normalise(re.sub(r"\(.*?\)", "", s.name))
        for t in texts:
            score = fuzz.token_set_ratio(normalise(t), target)
            if score > best:
                best_id, best = s.id, score
    if best >= 85:
        return best_id, round(best, 1), "NAME"
    return None, round(best, 1), "NONE"
