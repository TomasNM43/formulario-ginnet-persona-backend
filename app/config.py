"""Configuración compartida por la API y el worker (se lee de .env / variables de entorno)."""
from __future__ import annotations

import os
import re
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
SUPPORTED_EXTENSIONS = frozenset({"wav", "mp3", "flac", "ogg"})
_IDENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]{0,127}$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    DB_USER: str = Field(min_length=1)
    DB_PASSWORD: SecretStr
    DB_DSN: str = Field(min_length=1)
    DB_SCHEMA: str = "GINNET_AUDIO"
    DB_POOL_MIN: int = Field(2, ge=1)
    DB_POOL_MAX: int = Field(10, ge=1)
    AUDIO_ROOT: Path
    MAX_UPLOAD_MB: int = Field(200, ge=1)
    ALLOWED_EXTENSIONS: str = "wav,mp3,flac"
    CORS_ORIGINS: str = "http://localhost:5173"
    LOG_DIR: Path
    STUCK_JOB_MINUTES: int = Field(15, ge=1)

    # Verificación de frase hablada
    TRANSCRIPTION_ENGINE: str = "faster-whisper"
    WHISPER_MODEL: str = "small"
    WHISPER_DEVICE: str = "cpu"
    WHISPER_COMPUTE_TYPE: str = "int8"
    PRELOAD_WHISPER: bool = True
    PHRASE_THRESHOLD: float = Field(1.0, ge=0, le=1)
    PHRASE_LANGUAGE: str = "es-ES"

    # Autenticación JWT (solo la API; el worker no la necesita)
    JWT_SECRET: SecretStr = SecretStr("")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = Field(60, ge=1)
    MAX_FILE_SIZE_MB: int = Field(10, ge=1)
    VOICE_ALLOWED_EXTENSIONS: str = "wav,mp3,flac,m4a,ogg,webm,mp4"
    TEMP_DIR: Path = Path(tempfile.gettempdir()) / "ginnet_voice"

    @field_validator("DB_SCHEMA")
    @classmethod
    def _schema_is_identifier(cls, v: str) -> str:
        # El esquema se usa como identificador (no admite bind variables): solo se permite un identificador simple.
        if not _IDENT_RE.match(v):
            raise ValueError("DB_SCHEMA no es un identificador Oracle válido")
        return v

    @model_validator(mode="after")
    def _check_consistency(self) -> "Settings":
        if self.DB_POOL_MAX < self.DB_POOL_MIN:
            raise ValueError("DB_POOL_MAX debe ser >= DB_POOL_MIN")
        unknown = set(self.allowed_extensions) - SUPPORTED_EXTENSIONS
        if not self.allowed_extensions or unknown:
            raise ValueError(
                f"ALLOWED_EXTENSIONS debe contener solo: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            )
        return self

    @property
    def allowed_extensions(self) -> frozenset[str]:
        return frozenset(e.strip().lower().lstrip(".") for e in self.ALLOWED_EXTENSIONS.split(",") if e.strip())

    @property
    def voice_allowed_extensions(self) -> frozenset[str]:
        return frozenset(e.strip().lower().lstrip(".") for e in self.VOICE_ALLOWED_EXTENSIONS.split(",") if e.strip())

    @property
    def voice_max_file_bytes(self) -> int:
        return self.MAX_FILE_SIZE_MB * 1024 * 1024

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024


def load_settings(env_file: str | os.PathLike[str] | None = None) -> Settings:
    path = env_file or os.environ.get("ENV_FILE") or BACKEND_DIR / ".env"
    return Settings(_env_file=path)  # type: ignore[call-arg]


@lru_cache
def get_settings() -> Settings:
    try:
        return load_settings()
    except ValidationError as exc:
        # Solo nombres de variable y motivo; nunca valores (evita filtrar el password).
        lines = [f"  - {'.'.join(str(p) for p in e['loc']) or 'configuración'}: {e['msg']}" for e in exc.errors()]
        sys.stderr.write("Configuración inválida o incompleta:\n" + "\n".join(lines) + "\n")
        raise SystemExit(1) from None
