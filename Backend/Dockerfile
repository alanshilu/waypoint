# Waypoint backend: FastAPI on uvicorn. Applies database migrations, then serves on $PORT (default 8000).
# Runs as-is on Render (which sets PORT) and in docker-compose.yml.
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
COPY docker-start.sh .

# Non-root. /app itself stays writable for the weather HTTP cache (.cache.sqlite); the code stays root-owned.
RUN useradd --create-home --uid 10001 waypoint && chown waypoint /app
USER waypoint

EXPOSE 8000

# Liveness only (GET /health doesn't touch the database), on whatever port the app was given
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["sh", "-c", "python -c \"import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://localhost:${PORT:-8000}/health', timeout=4).status == 200 else 1)\""]

CMD ["sh", "docker-start.sh"]
