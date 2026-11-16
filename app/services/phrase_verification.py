"""Verificación de un audio contra una frase esperada (síncrona)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO

from . import phrase_matcher
from .transcription_service import Transcriber


@dataclass(frozen=True)
class PhraseVerification:
    match: bool
    similarity: float
    transcription: str


def verify_audio(transcriber: Transcriber, path: "str | BinaryIO", expected: str, language: str, threshold: float) -> PhraseVerification:
    result = transcriber.transcribe(path, language)
    sim = phrase_matcher.similarity(phrase_matcher.normalize(expected), phrase_matcher.normalize(result.text))
    return PhraseVerification(match=sim >= threshold, similarity=sim, transcription=result.text)
