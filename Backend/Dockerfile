# Waypoint backend: FastAPI on uvicorn. Applies database migrations, then serves on port 8000.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.lock .
RUN pip install -r requirements.lock

COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app

# Non-root. /app itself stays writable for the weather HTTP cache (.cache.sqlite); the code stays root-owned.
RUN useradd --create-home --uid 10001 waypoint && chown waypoint /app
USER waypoint

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=4).status == 200 else 1)"]

# --proxy-headers: the client IP (used by the per-IP session limit) comes from the reverse proxy in front.
# Only the proxy can reach this port in docker-compose.yml, so trusting its X-Forwarded-For is safe.
CMD ["sh", "-c", "python -m alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
