"""Emisión/validación de JWT y autenticación contra GINNET_AUDIO.USUARIOS."""
from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import Engine, func, select

from ..config import Settings
from ..models import usuarios_table

MIN_SECRET_LEN = 32
_DUMMY = "x" * 16


class InvalidToken(Exception):
    pass


@dataclass(frozen=True)
class User:
    id: int
    nombres: str
    apellidos: str
    correo: str


def check_secret(settings: Settings) -> None:
    if len(settings.JWT_SECRET.get_secret_value()) < MIN_SECRET_LEN:
        raise RuntimeError(f"JWT_SECRET es obligatorio y debe tener al menos {MIN_SECRET_LEN} caracteres")


def authenticate(engine: Engine, settings: Settings, correo: str, clave: str) -> User | None:
    t = usuarios_table(settings.DB_SCHEMA)
    with engine.connect() as conn:
        row = conn.execute(
            select(t.c.ID_USUARIO, t.c.NOMBRES, t.c.APELLIDOS, t.c.CORREO, t.c.CLAVE).where(
                func.lower(t.c.CORREO) == correo.strip().lower()
            )
        ).first()
    stored = row.CLAVE.strip() if row else _DUMMY
    ok = hmac.compare_digest(stored.encode("utf-8"), clave.strip().encode("utf-8"))  # tiempo constante
    if row is None or not ok:
        return None
    return User(row.ID_USUARIO, row.NOMBRES, row.APELLIDOS, row.CORREO)


def create_token(settings: Settings, user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user.id), "iat": now, "exp": now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)}
    return jwt.encode(payload, settings.JWT_SECRET.get_secret_value(), algorithm=settings.JWT_ALGORITHM)


def decode_token(settings: Settings, token: str) -> int:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET.get_secret_value(),
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "sub"]},
        )
        return int(payload["sub"])
    except (jwt.PyJWTError, ValueError) as exc:
        raise InvalidToken from exc


def get_user(engine: Engine, settings: Settings, user_id: int) -> User | None:
    t = usuarios_table(settings.DB_SCHEMA)
    with engine.connect() as conn:
        row = conn.execute(
            select(t.c.ID_USUARIO, t.c.NOMBRES, t.c.APELLIDOS, t.c.CORREO).where(t.c.ID_USUARIO == user_id)
        ).first()
    return User(row.ID_USUARIO, row.NOMBRES, row.APELLIDOS, row.CORREO) if row else None
