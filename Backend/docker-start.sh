#!/bin/sh
# Container entrypoint: migrate the database, then serve on $PORT with one worker and no reload.
set -e

PORT="${PORT:-8000}"
# The agent's tools call this API over HTTP; default to this container on the port it was given
export API_BASE_URL="${API_BASE_URL:-http://localhost:$PORT}"

python -m alembic upgrade head

# One worker: sessions and cost counters live in this process's memory.
# --proxy-headers: the client IP (used by the per-IP session limit) comes from the platform's proxy
# (Render's load balancer, or nginx in docker-compose.yml), which is the only way to reach this port.
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --workers 1 --proxy-headers --forwarded-allow-ips='*'
