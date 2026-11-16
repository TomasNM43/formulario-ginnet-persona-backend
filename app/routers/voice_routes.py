from __future__ import annotations

import logging
import os
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import Engine, select

from ..config import Settings, get_settings
from ..db import get_engine
from ..models import persona_audio_frases_table
from ..schemas_voice import FraseOut, VerifyPhraseResponse
from .auth import get_current_user
from ..services import phrase_matcher
from ..services.transcription_service import AudioDecodeError, Transcriber, transcribe_file

logger = logging.getLogger("app.voice")
router = APIRouter(prefix="/api/voice", tags=["Voice"], dependencies=[Depends(get_current_user)])

ALLOWED_CONTENT_PREFIXES = ("audio/", "video/mp4", "video/webm", "application/octet-stream")


@router.get("/phrases", response_model=list[FraseOut])
def list_phrases(engine: Engine = Depends(get_engine), settings: Settings = Depends(get_settings)) -> list[FraseOut]:
    t = persona_audio_frases_table(settings.DB_SCHEMA)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                select(t.c.ID, t.c.FRASE, t.c.ORDEN).where(t.c.FRASE.is_not(None)).order_by(t.c.ORDEN)
            ).all()
    except Exception:
        logger.exception("No se pudieron leer las frases")
        raise HTTPException(503, "Base de datos no disponible")
    return [FraseOut(id=r.ID, frase=r.FRASE, orden=int(r.ORDEN)) for r in rows]


def get_transcriber(request: Request) -> Transcriber:
    transcriber = getattr(request.app.state, "transcriber", None)
    if transcriber is None:
        raise HTTPException(status_code=503, detail="Motor de transcripción no disponible")
    return transcriber


@router.post("/verify-phrase", response_model=VerifyPhraseResponse)
async def verify_phrase(
    file: UploadFile = File(...),
    expected_phrase: str | None = Form(None),
    phrase_id: str | None = Form(None),
    language: str = Form("es-ES"),
    threshold: float | None = Form(None),
    settings: Settings = Depends(get_settings),
    transcriber: Transcriber = Depends(get_transcriber),
    engine: Engine = Depends(get_engine),
) -> VerifyPhraseResponse:
    work_dir: Path | None = None
    dest: str | None = None
    try:
        filename = os.path.basename((file.filename or "").replace("\\", "/"))
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in settings.voice_allowed_extensions:
            raise HTTPException(415, "Extensión de audio no permitida")
        content_type = (file.content_type or "").lower()
        if not content_type.startswith(ALLOWED_CONTENT_PREFIXES):
            raise HTTPException(415, "Tipo de contenido no permitido")
        if file.size is not None and file.size > settings.voice_max_file_bytes:
            raise HTTPException(413, f"El archivo supera {settings.MAX_FILE_SIZE_MB} MB")
        if phrase_id:
            # La frase esperada sale de la BD (no del cliente).
            t = persona_audio_frases_table(settings.DB_SCHEMA)
            with engine.connect() as conn:
                row = conn.execute(select(t.c.FRASE).where(t.c.ID == phrase_id)).first()
            if row is None or not row.FRASE:
                raise HTTPException(404, "Frase no encontrada")
            expected_phrase = row.FRASE
        if not expected_phrase or not expected_phrase.strip():
            raise HTTPException(422, "expected_phrase o phrase_id es obligatorio")
        if threshold is None:
            threshold = settings.PHRASE_THRESHOLD
        if not 0 <= threshold <= 1:
            raise HTTPException(422, "threshold debe estar entre 0 y 1")

        work_dir = Path(settings.TEMP_DIR) / uuid.uuid4().hex[:8]
        work_dir.mkdir(parents=True, exist_ok=True)
        dest = str(work_dir / filename)
        with open(dest, "wb") as out:
            shutil.copyfileobj(file.file, out)
        if os.path.getsize(dest) > settings.voice_max_file_bytes:
            raise HTTPException(413, f"El archivo supera {settings.MAX_FILE_SIZE_MB} MB")

        try:
            result = await run_in_threadpool(transcribe_file, transcriber, dest, language)
        except AudioDecodeError:
            raise HTTPException(422, "No se pudo decodificar el audio")

        norm_expected = phrase_matcher.normalize(expected_phrase)
        norm_transcription = phrase_matcher.normalize(result.text)
        similarity = phrase_matcher.similarity(norm_expected, norm_transcription)
        return VerifyPhraseResponse(
            success=True,
            phrase_id=phrase_id,
            match=similarity >= threshold,
            similarity=similarity,
            expected_phrase=expected_phrase,
            transcription=result.text,
            normalized_expected=norm_expected,
            normalized_transcription=norm_transcription,
            missing_words=phrase_matcher.missing_words(norm_expected, norm_transcription),
            language=language,
            duration_seconds=result.duration_seconds,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error verificando frase hablada")
        raise HTTPException(500, "Error interno del servidor")
    finally:
        if dest:
            try:
                os.remove(dest)
            except OSError:
                pass
        if work_dir:
            try:
                os.rmdir(work_dir)
            except OSError:
                pass
