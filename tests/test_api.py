import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db import get_engine
from app.main import app
from app.models import persona_audio_table
from app.routers import envios
from tests.conftest import MP3, WAV


@pytest.fixture()
def client(engine):
    app.dependency_overrides[get_engine] = lambda: engine
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def files(ref=WAV, test=MP3, ref_name="r.wav", test_name="p.mp3"):
    return {
        "referencia": (ref_name, io.BytesIO(ref), "audio/wav"),
        "prueba": (test_name, io.BytesIO(test), "audio/mpeg"),
    }


def count_files() -> int:
    root = get_settings().AUDIO_ROOT
    return sum(1 for p in Path(root).rglob("*") if p.is_file()) if root.exists() else 0


def rows(engine):
    with engine.connect() as c:
        return c.execute(select(persona_audio_table("main"))).all()


def test_post_ok_and_get(client, engine):
    before = count_files()
    r = client.post("/api/envios", data={"nombres": "José", "apellidos": "Núñez"}, files=files())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["estado"] == "pendiente" and body["tag"].startswith("jose-nunez_")
    assert count_files() == before + 2
    row = rows(engine)[0]
    assert row.ESTADO == "pendiente" and row.FECHA_CREACION is not None and Path(row.RUTA_PRUEBA).exists()

    g = client.get(f"/api/envios/{body['id']}")
    assert g.status_code == 200 and g.json()["estado"] == "pendiente" and "ruta" not in g.text.lower()
    assert client.get("/api/envios/9999").status_code == 404


def test_error_state_has_generic_message(client, engine):
    body = client.post("/api/envios", data={"nombres": "A", "apellidos": "B"}, files=files()).json()
    with engine.begin() as c:
        c.exec_driver_sql("UPDATE PERSONA_AUDIO SET ESTADO='error', ERROR_MSG='ORA-12345 D:\\secreto'")
    g = client.get(f"/api/envios/{body['id']}").json()
    assert g["error"] == envios.GENERIC_PROCESSING_ERROR and "ORA" not in str(g)


def test_rejects_fake_audio_and_long_names(client, engine):
    r = client.post("/api/envios", data={"nombres": "A", "apellidos": "B"}, files=files(ref=b"MZ" + b"0" * 30))
    assert r.status_code == 422
    r = client.post("/api/envios", data={"nombres": "ñ" * 51, "apellidos": "B"}, files=files())
    assert r.status_code == 422 and "bytes" in r.json()["detail"]
    assert rows(engine) == []


def test_tag_conflict_retries_and_cleans(client, engine, monkeypatch):
    first = client.post("/api/envios", data={"nombres": "A", "apellidos": "B"}, files=files()).json()
    tags_seq = iter([first["tag"], first["tag"], "a-b_ffffff"])
    monkeypatch.setattr(envios.tags, "generate_tag", lambda n, a: next(tags_seq))
    before = count_files()
    r = client.post("/api/envios", data={"nombres": "A", "apellidos": "B"}, files=files())
    assert r.status_code == 201 and r.json()["tag"] == "a-b_ffffff"
    assert count_files() == before + 2  # los intentos fallidos no dejan archivos


def test_insert_failure_deletes_files_without_leaking(client, engine, monkeypatch):
    before = count_files()
    with engine.begin() as c:
        c.exec_driver_sql("DROP TABLE PERSONA_AUDIO")
    r = client.post("/api/envios", data={"nombres": "A", "apellidos": "B"}, files=files())
    assert r.status_code == 500
    assert "PERSONA_AUDIO" not in r.text and "no such table" not in r.text
    assert count_files() == before


def test_always_gives_up_after_5_conflicts(client, engine, monkeypatch):
    first = client.post("/api/envios", data={"nombres": "A", "apellidos": "B"}, files=files()).json()
    monkeypatch.setattr(envios.tags, "generate_tag", lambda n, a: first["tag"])
    r = client.post("/api/envios", data={"nombres": "A", "apellidos": "B"}, files=files())
    assert r.status_code == 503


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}
