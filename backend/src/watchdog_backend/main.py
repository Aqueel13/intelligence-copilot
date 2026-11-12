import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

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
from watchdog_backend.db import get_engine
from watchdog_backend.identity.middleware import AuthMiddleware
from watchdog_backend.observability.requests import RequestMetricsMiddleware


def _warm_process_cache() -> None:
    """Fill each pack's default process view so the first visitor does not wait for it."""
    from watchdog_backend.analytics import process_cache
    from watchdog_backend.analytics.metrics import MetricsEngine
    from watchdog_backend.analytics.process import ProcessAnalyzer
    from watchdog_backend.domain.pack import available_domains, get_pack

    for pack in available_domains():
        try:
            with get_engine().connect() as conn:
                analyzer = ProcessAnalyzer(MetricsEngine(get_pack(pack)))
                process_cache.warm(conn, analyzer, pack)
        except Exception:  # a cold cache only costs time; never take the app down
            logging.getLogger(__name__).exception("Process cache warm-up failed for %s", pack)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if get_settings().process_cache_warm:
        threading.Thread(target=_warm_process_cache, name="process-cache-warm", daemon=True).start()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
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
