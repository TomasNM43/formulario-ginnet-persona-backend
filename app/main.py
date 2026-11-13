from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .logging_setup import setup_logging
from .routers import envios


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.LOG_DIR, "api")
    log = logging.getLogger("app")

    app = FastAPI(title="Formulario Ginnet Audio", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.error("excepción no controlada en %s %s", request.method, request.url.path, exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": "Error interno del servidor"})

    app.include_router(envios.router)
    return app


app = create_app()
