#!/bin/sh
set -e

echo "[entrypoint] waiting for MySQL ${MYSQL_HOST:-mysql}:${MYSQL_PORT:-3306} ..."
python - <<'PY'
import os, socket, time, sys
host = os.getenv("MYSQL_HOST", "mysql")
port = int(os.getenv("MYSQL_PORT", "3306"))
deadline = time.time() + 120
while time.time() < deadline:
    try:
        with socket.create_connection((host, port), timeout=3):
            print("[entrypoint] MySQL is reachable")
            sys.exit(0)
    except OSError:
        time.sleep(2)
print("[entrypoint] MySQL not ready in time", file=sys.stderr)
sys.exit(1)
PY

echo "[entrypoint] alembic upgrade head"
alembic upgrade head

echo "[entrypoint] starting uvicorn"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
