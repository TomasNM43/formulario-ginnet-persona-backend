"""Normalización de frases y cálculo de similitud."""
from __future__ import annotations

import re
import unicodedata

try:
    from rapidfuzz import fuzz

    def _ratio(a: str, b: str) -> float:
        return fuzz.ratio(a, b) / 100
except ImportError:  # pragma: no cover - alternativa sin rapidfuzz
    from difflib import SequenceMatcher

    def _ratio(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio()

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.lower())
    no_accents = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    no_punct = _PUNCT_RE.sub(" ", no_accents.replace("_", " "))
    return re.sub(r"\s+", " ", no_punct).strip()


def similarity(normalized_expected: str, normalized_transcription: str) -> float:
    if not normalized_expected or not normalized_transcription:
        return 0.0
    return round(_ratio(normalized_expected, normalized_transcription), 4)


def missing_words(normalized_expected: str, normalized_transcription: str) -> list[str]:
    """Palabras esperadas que no aparecen en la transcripción (respeta repeticiones)."""
    remaining = normalized_transcription.split()
    missing: list[str] = []
    for word in normalized_expected.split():
        if word in remaining:
            remaining.remove(word)
        else:
            missing.append(word)
    return missing
