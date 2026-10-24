#!/bin/sh
set -e
# Wait for Postgres, apply migrations/roles, optionally load the synthetic demo data.
python - <<'PY'
import time, sys
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from app.config import get_settings
url = make_url(get_settings().admin_database_url).set(database="postgres")
for i in range(60):
    try:
        with create_engine(url).connect() as c:
            c.execute(text("SELECT 1"))
        break
    except Exception:
        time.sleep(1)
else:
    sys.exit("database not reachable")
PY
python -m scripts.bootstrap_db
if [ "${SEED_ON_START:-true}" = "true" ]; then
  python -m seed.load
fi
exec "$@"
