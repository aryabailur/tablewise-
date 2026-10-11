#!/bin/sh
# Wait for Postgres, seed once (restaurant table missing or empty), then serve.
set -e

# Host-provided LLM settings (HOST_*) override backend/.env values; empty ones are ignored.
for name in LLM_PROVIDER GROQ_API_KEY LLM_MODEL ANTHROPIC_API_KEY; do
  eval "host_value=\${HOST_$name:-}"
  if [ -n "$host_value" ]; then
    export "$name=$host_value"
  fi
  unset "HOST_$name"
done
unset host_value

python - <<'PY'
import os, sys, time
from sqlalchemy import create_engine, text

url = os.environ.get("DATABASE_URL", "")
if not url.startswith("postgresql"):
    sys.exit(0)  # SQLite / unset: nothing to wait for
engine = create_engine(url, pool_pre_ping=True)
for attempt in range(60):
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        print("[entrypoint] postgres is ready", flush=True)
        break
    except Exception as exc:  # noqa: BLE001
        print(f"[entrypoint] waiting for postgres ({attempt + 1}/60): {exc.__class__.__name__}", flush=True)
        time.sleep(2)
else:
    sys.exit("[entrypoint] postgres never became ready")
PY

NEEDS_SEED=$(python - <<'PY'
import os
from sqlalchemy import create_engine, inspect, text

url = os.environ.get("DATABASE_URL")
if not url:
    print("no"); raise SystemExit
engine = create_engine(url)
if not inspect(engine).has_table("restaurant"):
    print("yes"); raise SystemExit
with engine.connect() as conn:
    count = conn.execute(text("select count(*) from restaurant")).scalar() or 0
print("yes" if count == 0 else "no")
PY
)

if [ "$NEEDS_SEED" = "yes" ]; then
  echo "[entrypoint] empty database or index: running python -m app.seed"
  python -m app.seed
else
  echo "[entrypoint] database already seeded"
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
