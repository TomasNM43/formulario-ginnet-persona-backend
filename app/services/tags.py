from __future__ import annotations

import re
import secrets
import unicodedata

MAX_TAG_BYTES = 200
_SUFFIX_LEN = 6
_INVALID = re.compile(r"[^a-z0-9\-_]")
_DASHES = re.compile(r"-{2,}")


def normalize(text: str) -> str:
    """Sin tildes, minúsculas, espacios a guiones y solo [a-z0-9-_]."""
    decomposed = unicodedata.normalize("NFKD", text)
    no_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    s = re.sub(r"\s+", "-", no_marks.strip().lower())
    s = _INVALID.sub("", s)
    return _DASHES.sub("-", s).strip("-")


def generate_tag(nombres: str, apellidos: str) -> str:
    """`{nombres}-{apellidos}_{6 hex}`, siempre <= 200 bytes (el resultado es ASCII)."""
    n = normalize(nombres) or "x"
    a = normalize(apellidos) or "x"
    suffix = secrets.token_hex(_SUFFIX_LEN // 2)
    base = f"{n}-{a}"
    base = base[: MAX_TAG_BYTES - _SUFFIX_LEN - 1].rstrip("-_")
    return f"{base}_{suffix}"
