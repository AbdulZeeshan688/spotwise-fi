"""Health check endpoint (API-01)."""

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from spotwise.db.session import check_db_connection

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Health status of the API and its database."""

    status: Literal["ok", "degraded"]
    db: Literal["ok", "unreachable"]


def get_db_check() -> bool:
    """Dependency wrapper so tests can replace the real DB check."""
    return check_db_connection()


@router.get("/health", response_model=HealthResponse)
def health(response: Response, db_ok: Annotated[bool, Depends(get_db_check)]) -> HealthResponse:
    """Return 200 when the DB is reachable, 503 otherwise."""
    if db_ok:
        return HealthResponse(status="ok", db="ok")
    logger.warning("Health check: database unreachable")
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="degraded", db="unreachable")
