"""Worker de procesamiento. Ejecutar: python worker.py  (servicio de Windows vía NSSM)."""
from __future__ import annotations

import logging
import os
import signal
import threading
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, func, literal_column, select, update

from app.config import get_settings
from app.db import get_engine
from app.logging_setup import setup_logging
from app.models import Estado, persona_audio_table, sys_timestamp

log = logging.getLogger("worker")

POLL_SECONDS = 5
MAX_CLAIM_ATTEMPTS = 5
MAX_ERROR_BYTES = 1000


@dataclass(frozen=True)
class Job:
    id: int
    tag: str
    ruta_referencia: str
    ruta_prueba: str


def truncate_bytes(msg: str, limit: int = MAX_ERROR_BYTES) -> str:
    return msg.encode("utf-8")[:limit].decode("utf-8", errors="ignore")


def procesar(ruta_referencia: str, ruta_prueba: str) -> None:
    """PUNTO DE EXTENSIÓN: reemplazar por el análisis real. Debe lanzar excepción si falla."""
    for ruta in (ruta_referencia, ruta_prueba):
        if not ruta or not os.path.isfile(ruta):
            raise FileNotFoundError("Archivo de audio no encontrado")
        with open(ruta, "rb") as f:
            if not f.read(1):
                raise ValueError("Archivo de audio vacío")


def _stuck_cutoff(minutes: int) -> Any:
    return sys_timestamp() - func.numtodsinterval(minutes, literal_column("'MINUTE'"))


def requeue_stuck(engine: Engine, schema: str, minutes: int) -> int:
    t = persona_audio_table(schema)
    with engine.begin() as conn:
        res = conn.execute(
            update(t)
            .where(t.c.ESTADO == Estado.PROCESANDO.value, t.c.FECHA_INICIO < _stuck_cutoff(minutes))
            .values(ESTADO=Estado.PENDIENTE.value, FECHA_INICIO=None)
        )
        return res.rowcount


def claim_next(engine: Engine, schema: str) -> Job | None:
    """Reclamo atómico: el UPDATE condicionado por ESTADO='pendiente' decide quién gana."""
    t = persona_audio_table(schema)
    for _ in range(MAX_CLAIM_ATTEMPTS):
        with engine.connect() as conn:
            cand = conn.execute(
                select(t.c.ID_PERSONA_AUDIO, t.c.TAG, t.c.RUTA_REFERENCIA, t.c.RUTA_PRUEBA)
                .where(t.c.ESTADO == Estado.PENDIENTE.value)
                .order_by(t.c.FECHA_CREACION, t.c.ID_PERSONA_AUDIO)
                .limit(1)  # Oracle: FETCH FIRST 1 ROWS ONLY
            ).first()
            if cand is None:
                conn.rollback()
                return None
            res = conn.execute(
                update(t)
                .where(t.c.ID_PERSONA_AUDIO == cand.ID_PERSONA_AUDIO, t.c.ESTADO == Estado.PENDIENTE.value)
                .values(ESTADO=Estado.PROCESANDO.value, FECHA_INICIO=sys_timestamp())
            )
            if res.rowcount != 1:
                conn.rollback()  # otro worker ganó; reintentar con el siguiente candidato
                continue
            conn.commit()
            return Job(cand.ID_PERSONA_AUDIO, cand.TAG, cand.RUTA_REFERENCIA or "", cand.RUTA_PRUEBA or "")
    return None


def finish(engine: Engine, schema: str, job_id: int, error: str | None) -> None:
    t = persona_audio_table(schema)
    values = {"ESTADO": Estado.LISTO.value, "ERROR_MSG": None}
    if error is not None:
        values = {"ESTADO": Estado.ERROR.value, "ERROR_MSG": truncate_bytes(error)}
    with engine.begin() as conn:
        conn.execute(
            update(t)
            .where(t.c.ID_PERSONA_AUDIO == job_id, t.c.ESTADO == Estado.PROCESANDO.value)
            .values(**values)
        )


def run_one(engine: Engine, schema: str) -> bool:
    job = claim_next(engine, schema)
    if job is None:
        return False
    log.info("procesando", extra={"ctx": {"id": job.id, "tag": job.tag}})
    try:
        procesar(job.ruta_referencia, job.ruta_prueba)
    except Exception as exc:
        log.exception("fallo procesando", extra={"ctx": {"id": job.id}})
        error: str | None = f"{type(exc).__name__}: {exc}" or "Error desconocido"
    else:
        error = None
    finish(engine, schema, job.id, error)
    log.info("terminado", extra={"ctx": {"id": job.id, "estado": "error" if error else "listo"}})
    return True


def main() -> None:
    settings = get_settings()
    setup_logging(settings.LOG_DIR, "worker")
    engine = get_engine()
    stop = threading.Event()

    def _stop(signum: int, _frame: Any) -> None:
        log.info("señal %s recibida, cerrando", signum)
        stop.set()

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _stop)

    log.info("worker iniciado")
    while not stop.is_set():
        try:
            n = requeue_stuck(engine, settings.DB_SCHEMA, settings.STUCK_JOB_MINUTES)
            if n:
                log.warning("trabajos atascados reencolados", extra={"ctx": {"count": n}})
            if run_one(engine, settings.DB_SCHEMA):
                continue  # hay más trabajo posible: no esperar
        except Exception:
            log.exception("error en el ciclo del worker")
        stop.wait(POLL_SECONDS)
    engine.dispose()
    log.info("worker detenido")


if __name__ == "__main__":
    main()
