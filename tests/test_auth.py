import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import get_engine
from app.main import app


@pytest.fixture()
def client(engine):
    app.dependency_overrides[get_engine] = lambda: engine
    yield TestClient(app)
    app.dependency_overrides.clear()


def login(client, correo="ana@mail.com", clave="A001"):
    return client.post("/api/auth/login", json={"correo": correo, "clave": clave})


def test_login_ok_is_case_insensitive_on_email(client):
    r = login(client, correo="  ANA@mail.COM ")
    assert r.status_code == 200
    body = r.json()
    assert body["user"] == {"nombres": "Ana", "apellidos": "Gil", "correo": "Ana@Mail.com"}
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["nombres"] == "Ana"


@pytest.mark.parametrize("correo,clave", [("ana@mail.com", "mala"), ("nadie@mail.com", "A001"), ("ana@mail.com", "a001")])
def test_login_fails_with_same_generic_error(client, correo, clave):
    r = login(client, correo, clave)
    assert r.status_code == 401 and r.json()["detail"] == "Credenciales inválidas"


@pytest.mark.parametrize("path,method", [("/api/envios/1", "get"), ("/api/voice/phrases", "get"), ("/api/auth/me", "get")])
def test_protected_endpoints_need_token(client, path, method):
    assert getattr(client, method)(path).status_code == 401
    assert getattr(client, method)(path, headers={"Authorization": "Bearer basura"}).status_code == 401


def test_public_endpoints_stay_open(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/config").status_code == 200


def test_expired_and_wrongly_signed_tokens_rejected(client):
    s = get_settings()
    secret = s.JWT_SECRET.get_secret_value()
    expired = jwt.encode({"sub": "1", "exp": int(time.time()) - 10}, secret, algorithm="HS256")
    forged = jwt.encode({"sub": "1", "exp": int(time.time()) + 600}, "otra-clave-" * 4, algorithm="HS256")
    for tok in (expired, forged):
        assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 401
