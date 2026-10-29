"""FastAPI application entry point: `uvicorn spotwise.api.main:app`."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from spotwise.api.routes import health
from spotwise.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def create_app() -> FastAPI:
    """Build the FastAPI app with middleware and routes."""
    app = FastAPI(title="SpotWise FI", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    return app


app = create_app()
