"""Transcripción con faster-whisper (síncrona; se ejecuta en un threadpool)."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import BinaryIO

log = logging.getLogger("app.transcription")


class AudioDecodeError(Exception):
    """El audio no pudo decodificarse."""


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    duration_seconds: float


def whisper_language(language: str) -> str | None:
    """'es-ES' -> 'es'. Vacío -> None (detección automática)."""
    code = language.strip().replace("_", "-").split("-")[0].lower()
    return code or None


class Transcriber:
    def __init__(self, model_name: str, device: str, compute_type: str) -> None:
        from faster_whisper import WhisperModel

        self._model = WhisperModel(model_name, device=device, compute_type=compute_type)
        self._lock = threading.Lock()

    def transcribe(self, path: "str | BinaryIO", language: str) -> TranscriptionResult:
        # faster-whisper decodifica con PyAV (ffmpeg embebido) y remuestrea a mono 16 kHz.
        try:
            with self._lock:  # una transcripción a la vez sobre el modelo compartido
                segments, info = self._model.transcribe(
                    path, language=whisper_language(language), vad_filter=True, beam_size=5
                )
                text = " ".join(s.text.strip() for s in segments).strip()
        except Exception as exc:
            if _is_decode_error(exc):
                raise AudioDecodeError(str(exc)) from exc
            raise
        return TranscriptionResult(text=text, duration_seconds=round(float(info.duration), 2))


def _is_decode_error(exc: Exception) -> bool:
    try:
        import av

        if isinstance(exc, av.error.FFmpegError):
            return True
    except ImportError:  # pragma: no cover
        pass
    return isinstance(exc, (EOFError, ValueError)) and "decod" in str(exc).lower()


def transcribe_file(transcriber: Transcriber, path: str, language: str) -> TranscriptionResult:
    return transcriber.transcribe(path, language)
