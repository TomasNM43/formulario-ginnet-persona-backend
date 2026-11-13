from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, field_validator

from .models import Estado

MAX_NAME_BYTES = 100


def byte_len(value: str) -> int:
    return len(value.encode("utf-8"))


class EnvioIn(BaseModel):
    nombres: str
    apellidos: str

    @field_validator("nombres", "apellidos")
    @classmethod
    def _validate_name(cls, v: str, info) -> str:  # noqa: ANN001
        v = " ".join(v.split())  # recorta y colapsa espacios
        label = info.field_name
        if not v:
            raise ValueError(f"'{label}' es obligatorio")
        if byte_len(v) > MAX_NAME_BYTES:
            raise ValueError(f"'{label}' excede {MAX_NAME_BYTES} bytes (UTF-8); acórtalo")
        return v


class EnvioCreado(BaseModel):
    id: int
    tag: str
    estado: Estado


class EnvioOut(BaseModel):
    id: int
    tag: str
    nombres: str | None
    apellidos: str | None
    estado: Estado
    fecha_creacion: datetime | None
    error: str | None = None


class ConfigPublica(BaseModel):
    allowed_extensions: list[str]
    max_upload_mb: int
