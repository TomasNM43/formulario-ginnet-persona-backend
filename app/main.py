from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .logging_setup import setup_logging
from .routers import auth, envios, voice_routes
from .services.auth import check_secret


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.transcriber = None
    if settings.PRELOAD_WHISPER:
        from .services.transcription_service import Transcriber

        # Se carga una sola vez; la carga bloqueante va al threadpool.
        app.state.transcriber = await run_in_threadpool(
            Transcriber, settings.WHISPER_MODEL, settings.WHISPER_DEVICE, settings.WHISPER_COMPUTE_TYPE
        )
    yield
    app.state.transcriber = None


def create_app() -> FastAPI:
    settings = get_settings()
    check_secret(settings)
    setup_logging(settings.LOG_DIR, "api")
    log = logging.getLogger("app")

    app = FastAPI(
        title="Formulario Ginnet Audio", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )
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

    app.include_router(auth.router)
    app.include_router(envios.router)
    app.include_router(voice_routes.router)
    return app


app = create_app()
