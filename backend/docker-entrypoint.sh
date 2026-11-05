#!/bin/sh
# Usage: docker-entrypoint.sh api|worker|<any command>
set -e

wait_for_db() {
  python - <<'PY'
import sys, time
from sqlalchemy import create_engine, text
from app.core.config import get_settings

url = get_settings().database_url
for attempt in range(60):
    try:
        with create_engine(url).connect() as conn:
            conn.execute(text("SELECT 1"))
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        print(f"Waiting for database ({attempt + 1}/60): {exc.__class__.__name__}", flush=True)
        time.sleep(2)
print("Database did not become available", file=sys.stderr)
sys.exit(1)
PY
}

case "$1" in
  api)
    wait_for_db
    echo "Applying database migrations..."
    alembic upgrade head
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 \
      --workers "${API_WORKERS:-2}" --proxy-headers --forwarded-allow-ips="*"
    ;;
  worker)
    wait_for_db
    exec python -m app.workers.runner
    ;;
  *)
    exec "$@"
    ;;
esac
