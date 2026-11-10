import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from watchdog_backend import __version__
from watchdog_backend.api import domain, health, metrics, process
from watchdog_backend.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router, prefix="/api")
    app.include_router(domain.router, prefix="/api")
    app.include_router(metrics.router, prefix="/api")
    app.include_router(process.router, prefix="/api")
    return app


app = create_app()
