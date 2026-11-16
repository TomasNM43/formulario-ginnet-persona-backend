from __future__ import annotations

from pydantic import BaseModel, Field


class FraseOut(BaseModel):
    id: str
    frase: str
    orden: int


class VerifyPhraseResponse(BaseModel):
    success: bool
    match: bool
    similarity: float = Field(ge=0, le=1)
    phrase_id: str | None = None
    expected_phrase: str
    transcription: str
    normalized_expected: str
    normalized_transcription: str
    missing_words: list[str]
    language: str
    duration_seconds: float
