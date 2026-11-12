import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from watchdog_backend import __version__
from watchdog_backend.api import (
    actions,
    auth,
    domain,
    evaluation,
    explore,
    health,
    investigations,
    knowledge,
    metrics,
    observability,
    process,
    watch,
)
from watchdog_backend.api.domain_context import DomainMiddleware
from watchdog_backend.config import get_settings
from watchdog_backend.identity.middleware import AuthMiddleware
from watchdog_backend.observability.requests import RequestMetricsMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(RequestMetricsMiddleware)  # innermost: sees the pack and the route
    app.add_middleware(DomainMiddleware)  # CORS headers also wrap its 400s
    app.add_middleware(AuthMiddleware)  # outside the pack: sign-in comes first
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(domain.router, prefix="/api")
    app.include_router(metrics.router, prefix="/api")
    app.include_router(process.router, prefix="/api")
    app.include_router(knowledge.router, prefix="/api")
    app.include_router(investigations.router, prefix="/api")
    app.include_router(actions.router, prefix="/api")
    app.include_router(watch.router, prefix="/api")
    app.include_router(evaluation.router, prefix="/api")
    app.include_router(observability.router, prefix="/api")
    app.include_router(explore.router, prefix="/api")
    return app


app = create_app()
