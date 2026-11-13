from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy import Engine, insert, select, text
from sqlalchemy.exc import IntegrityError

from ..config import Settings, get_settings
from ..db import get_engine
from ..models import Estado, persona_audio_table, sys_timestamp
from ..schemas import ConfigPublica, EnvioCreado, EnvioIn, EnvioOut
from ..services import storage, tags

log = logging.getLogger("app.envios")
router = APIRouter(prefix="/api")

MAX_TAG_ATTEMPTS = 5
GENERIC_PROCESSING_ERROR = "El procesamiento del envío falló. Contacte al administrador."


def is_tag_conflict(exc: IntegrityError) -> bool:
    msg = str(exc.orig).upper()
    return ("ORA-00001" in msg and "PERSONA_AUDIO_TAG_UK" in msg) or (
        "UNIQUE CONSTRAINT FAILED" in msg and "TAG" in msg  # SQLite (tests)
    )


@router.get("/health")
def health(engine: Engine = Depends(get_engine)) -> dict[str, str]:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1 FROM DUAL" if engine.dialect.name == "oracle" else "SELECT 1")).scalar_one()
    except Exception:
        log.exception("health check de BD falló")
        raise HTTPException(status_code=503, detail="Base de datos no disponible")
    return {"status": "ok"}


@router.get("/config", response_model=ConfigPublica)
def public_config(settings: Settings = Depends(get_settings)) -> ConfigPublica:
    return ConfigPublica(allowed_extensions=sorted(settings.allowed_extensions), max_upload_mb=settings.MAX_UPLOAD_MB)


@router.post("/envios", response_model=EnvioCreado, status_code=201)
def crear_envio(
    nombres: str = Form(...),
    apellidos: str = Form(...),
    referencia: UploadFile = File(...),
    prueba: UploadFile = File(...),
    engine: Engine = Depends(get_engine),
    settings: Settings = Depends(get_settings),
) -> EnvioCreado:
    try:
        datos = EnvioIn(nombres=nombres, apellidos=apellidos)
    except ValidationError as exc:
        msgs = [e["msg"].removeprefix("Value error, ") for e in exc.errors()]
        raise HTTPException(status_code=422, detail="; ".join(msgs))

    try:
        ext_ref = storage.validate_audio_file(
            referencia.file, referencia.filename, settings.allowed_extensions, settings.max_upload_bytes
        )
        ext_test = storage.validate_audio_file(
            prueba.file, prueba.filename, settings.allowed_extensions, settings.max_upload_bytes
        )
    except storage.StorageError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    table = persona_audio_table(settings.DB_SCHEMA)
    for attempt in range(1, MAX_TAG_ATTEMPTS + 1):
        tag = tags.generate_tag(datos.nombres, datos.apellidos)
        try:
            paths = storage.build_paths(settings.AUDIO_ROOT, tag, ext_ref, ext_test)
        except storage.PathTooLongError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        try:
            storage.save_files(paths, referencia.file, prueba.file)
        except storage.FileCollisionError:
            log.warning("colisión de carpeta de tag", extra={"ctx": {"attempt": attempt}})
            continue
        except OSError:
            log.exception("no se pudieron guardar los audios")
            raise HTTPException(status_code=500, detail="No se pudieron guardar los archivos")

        try:
            with engine.begin() as conn:
                new_id = conn.execute(
                    insert(table)
                    .values(
                        NOMBRES=datos.nombres,
                        APELLIDOS=datos.apellidos,
                        TAG=tag,
                        RUTA_REFERENCIA=str(paths.referencia),
                        RUTA_PRUEBA=str(paths.prueba),
                        ESTADO=Estado.PENDIENTE.value,
                        FECHA_CREACION=sys_timestamp(),
                    )
                    .returning(table.c.ID_PERSONA_AUDIO)
                ).scalar_one()
        except IntegrityError as exc:
            storage.remove_folder(paths.folder)
            if is_tag_conflict(exc):
                log.warning("tag duplicado, reintentando", extra={"ctx": {"attempt": attempt}})
                continue
            log.exception("INSERT falló")
            raise HTTPException(status_code=500, detail="No se pudo registrar el envío")
        except Exception:
            storage.remove_folder(paths.folder)
            log.exception("INSERT falló")
            raise HTTPException(status_code=500, detail="No se pudo registrar el envío")

        log.info("envío creado", extra={"ctx": {"id": new_id, "tag": tag}})
        return EnvioCreado(id=new_id, tag=tag, estado=Estado.PENDIENTE)

    log.error("no se obtuvo un tag único tras %d intentos", MAX_TAG_ATTEMPTS)
    raise HTTPException(status_code=503, detail="No se pudo generar un identificador único; reintente")


@router.get("/envios/{envio_id}", response_model=EnvioOut)
def obtener_envio(
    envio_id: int, engine: Engine = Depends(get_engine), settings: Settings = Depends(get_settings)
) -> EnvioOut:
    t = persona_audio_table(settings.DB_SCHEMA)
    with engine.connect() as conn:
        row = conn.execute(
            select(t.c.ID_PERSONA_AUDIO, t.c.TAG, t.c.NOMBRES, t.c.APELLIDOS, t.c.ESTADO, t.c.FECHA_CREACION).where(
                t.c.ID_PERSONA_AUDIO == envio_id
            )
        ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Envío no encontrado")
    estado = Estado(row.ESTADO)
    return EnvioOut(
        id=row.ID_PERSONA_AUDIO,
        tag=row.TAG,
        nombres=row.NOMBRES,
        apellidos=row.APELLIDOS,
        estado=estado,
        fecha_creacion=row.FECHA_CREACION,
        error=GENERIC_PROCESSING_ERROR if estado is Estado.ERROR else None,
    )
