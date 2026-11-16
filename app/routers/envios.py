from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy import Engine, insert, select, text
from sqlalchemy.exc import IntegrityError

from ..config import Settings, get_settings
from ..db import get_engine
from ..models import Estado, persona_audio_det_table, persona_audio_frases_table, persona_audio_table, sys_timestamp
from ..schemas import ConfigPublica, EnvioCreado, EnvioIn, EnvioOut
from ..services import storage, tags
from ..services.auth import User
from ..services.phrase_verification import PhraseVerification, verify_audio
from ..services.transcription_service import AudioDecodeError, Transcriber
from .auth import get_current_user
from .voice_routes import get_transcriber

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
    frase_ids: list[str] = Form(...),
    audios: list[UploadFile] = File(...),
    user: User = Depends(get_current_user),
    engine: Engine = Depends(get_engine),
    settings: Settings = Depends(get_settings),
    transcriber: Transcriber = Depends(get_transcriber),
) -> EnvioCreado:
    try:
        # Nombre y apellidos salen del usuario autenticado, no del cliente.
        datos = EnvioIn(nombres=user.nombres, apellidos=user.apellidos)
    except ValidationError as exc:
        msgs = [e["msg"].removeprefix("Value error, ") for e in exc.errors()]
        raise HTTPException(status_code=422, detail="; ".join(msgs))

    if len(frase_ids) != len(audios) or len(set(frase_ids)) != len(frase_ids):
        raise HTTPException(status_code=422, detail="Cada frase requiere exactamente un audio")

    frases_t = persona_audio_frases_table(settings.DB_SCHEMA)
    try:
        with engine.connect() as conn:
            frases = {
                r.ID: (r.FRASE, r.ORDEN)
                for r in conn.execute(
                    select(frases_t.c.ID, frases_t.c.FRASE, frases_t.c.ORDEN).where(frases_t.c.FRASE.is_not(None))
                )
            }
    except Exception:
        log.exception("no se pudieron leer las frases")
        raise HTTPException(status_code=503, detail="Base de datos no disponible")
    if set(frase_ids) != set(frases):
        raise HTTPException(status_code=422, detail="Se deben enviar los audios de todas las frases")

    try:
        exts = [
            storage.validate_audio_file(a.file, a.filename, settings.allowed_extensions, settings.max_upload_bytes)
            for a in audios
        ]
    except storage.StorageError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # La verificación del cliente no es de fiar: se repite aquí antes de guardar nada.
    similitudes: list[PhraseVerification] = []
    for fid, audio in zip(frase_ids, audios):
        audio.file.seek(0)
        try:
            v = verify_audio(
                transcriber, audio.file, frases[fid][0], settings.PHRASE_LANGUAGE, settings.PHRASE_THRESHOLD
            )
        except AudioDecodeError:
            raise HTTPException(status_code=422, detail="No se pudo decodificar uno de los audios")
        except Exception:
            log.exception("falló la verificación de frase")
            raise HTTPException(status_code=500, detail="No se pudo verificar el audio")
        if not v.match:
            raise HTTPException(status_code=422, detail=f"El audio de la frase {fid} no coincide con la frase esperada")
        similitudes.append(v)

    table = persona_audio_table(settings.DB_SCHEMA)
    det = persona_audio_det_table(settings.DB_SCHEMA)
    for attempt in range(1, MAX_TAG_ATTEMPTS + 1):
        tag = tags.generate_tag(datos.nombres, datos.apellidos)
        try:
            paths = storage.build_paths(settings.AUDIO_ROOT, tag, exts)
        except storage.PathTooLongError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        try:
            storage.save_files(paths, [a.file for a in audios])
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
                        ESTADO=Estado.PENDIENTE.value,
                        FECHA_CREACION=sys_timestamp(),
                    )
                    .returning(table.c.ID_PERSONA_AUDIO)
                ).scalar_one()
                conn.execute(
                    insert(det),
                    [
                        {
                            "ID_PERSONA_AUDIO": new_id,
                            "TAG": tag,
                            "ID_FRASE": fid,
                            "ORDEN": frases[fid][1],
                            "RUTA_AUDIO": str(path),
                            "TRANSCRIPCION": v.transcription.encode("utf-8")[:500].decode("utf-8", "ignore"),
                            "SIMILITUD": v.similarity,
                            "FECHA_CREACION": datetime.now(),
                        }
                        for fid, path, v in zip(frase_ids, paths.files, similitudes)
                    ],
                )
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


@router.get("/envios/{envio_id}", response_model=EnvioOut, dependencies=[Depends(get_current_user)])
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
