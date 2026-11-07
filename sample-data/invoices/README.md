# Sample supplier invoices (SYNTHETIC)

**Every document in this folder is synthetic test data.** The suppliers, the PINs (for
example `P051111111A`), the invoice numbers and the prices are invented, and each
supplier name is marked "(Demo)". These are not real invoices and must not be used as
such.

They were generated with:

```bash
cd backend
python -c "from pathlib import Path; from datetime import date; \
from scripts.generate_synthetic_invoices import generate; \
generate(Path('../sample-data/invoices'), 12, seed=42, today=date(2026, 11, 7))"
```

| File pattern | What it imitates |
|---|---|
| `*-classic-*` | A tax invoice with Description / Qty / Unit Price / Amount columns |
| `*-coded-*` | The same, with the supplier's own item codes in the first column |
| `*-receipt-*` | A narrow till receipt ("2 x 52.00") |
| `*-inclusive-*` | Prices that include VAT, with VAT shown as part of the total |
| `*-pdf-*` | A PDF with a text layer (read without OCR) |
| `-clean` / `-scan` / `-phone` | Rendered page / scanner noise and tilt / phone photo with perspective and shadow |

Each document has a `.truth.json` beside it, with the correct fields, lines and printed
text. `python -m scripts.evaluate_ocr --data ../sample-data/invoices` scores the system
against them.

To try them in the app, seed the demo catalogue (`make seed`); it includes the
matching suppliers and products. Then upload any of these files under
**Purchasing → Scan invoices**.
