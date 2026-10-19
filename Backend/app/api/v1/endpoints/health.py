"""
GET /health: the process is up (liveness). It never touches the database, so a platform health
check doesn't keep a serverless database (Neon) awake or fail while that database is waking.
GET /ready: the app can serve requests, i.e. the database answers a SELECT 1 (readiness).
"""

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core import db

router = APIRouter()
log = logging.getLogger(__name__)


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/ready")
def ready():
    try:
        with db.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - any failure means the database is not usable
        # the reason goes to the log, not to a public endpoint
        log.exception("Readiness check: database query failed")
        return JSONResponse(status_code=503, content={"status": "error", "database": "unreachable"})
    return {"status": "ok", "database": "ok"}
