"""GET /health for load balancers and the Docker healthcheck: the app is up and the database answers."""

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core import db

router = APIRouter()
log = logging.getLogger(__name__)


@router.get("")
def health():
    try:
        with db.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - any failure means the database is not usable
        # the reason goes to the log, not to a public endpoint
        log.exception("Health check: database query failed")
        return JSONResponse(status_code=503, content={"status": "error", "database": "unreachable"})
    return {"status": "ok", "database": "ok"}
