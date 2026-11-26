"""Queue every approved supplier invoice that is not yet in the document archive.

    python -m scripts.archive_invoices

Use once after setting up the document archive, to file invoices approved before it existed.
The worker then uploads them one by one; each invoice is filed only once.
"""

import sys

from app.core.database import SessionLocal
from app.core.exceptions import AppError
from app.services import archive_service


def main() -> int:
    with SessionLocal() as db:
        try:
            n = archive_service.queue_all_approved(db)
        except AppError as exc:
            print(exc.message, file=sys.stderr)
            return 1
    print(f"Queued {n} approved invoice(s) for the document archive.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
