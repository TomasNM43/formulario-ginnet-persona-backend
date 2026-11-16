from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import Engine

from ..config import Settings, get_settings
from ..db import get_engine
from ..services import auth
from ..services.auth import User

log = logging.getLogger("app.auth")
router = APIRouter(prefix="/api/auth", tags=["Auth"])
bearer = HTTPBearer(auto_error=False)

UNAUTHORIZED = HTTPException(
    status_code=401, detail="Credenciales inválidas", headers={"WWW-Authenticate": "Bearer"}
)


class LoginIn(BaseModel):
    correo: str
    clave: str


class UserOut(BaseModel):
    nombres: str
    apellidos: str
    correo: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    engine: Engine = Depends(get_engine),
    settings: Settings = Depends(get_settings),
) -> User:
    if creds is None:
        raise HTTPException(status_code=401, detail="No autenticado", headers={"WWW-Authenticate": "Bearer"})
    try:
        user_id = auth.decode_token(settings, creds.credentials)
    except auth.InvalidToken:
        raise HTTPException(status_code=401, detail="Sesión inválida o expirada", headers={"WWW-Authenticate": "Bearer"})
    try:
        user = auth.get_user(engine, settings, user_id)
    except Exception:
        log.exception("no se pudo leer el usuario")
        raise HTTPException(status_code=503, detail="Base de datos no disponible")
    if user is None:
        raise HTTPException(status_code=401, detail="Sesión inválida o expirada", headers={"WWW-Authenticate": "Bearer"})
    return user


@router.post("/login", response_model=TokenOut)
def login(
    body: LoginIn, engine: Engine = Depends(get_engine), settings: Settings = Depends(get_settings)
) -> TokenOut:
    try:
        user = auth.authenticate(engine, settings, body.correo, body.clave)
    except Exception:
        log.exception("login: error de BD")
        raise HTTPException(status_code=503, detail="Base de datos no disponible")
    if user is None:
        log.warning("login fallido")
        raise UNAUTHORIZED
    return TokenOut(
        access_token=auth.create_token(settings, user),
        user=UserOut(nombres=user.nombres, apellidos=user.apellidos, correo=user.correo),
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut(nombres=user.nombres, apellidos=user.apellidos, correo=user.correo)
