import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db import get_engine
from app.main import app
from app.models import persona_audio_det_table, persona_audio_frases_table, persona_audio_table
from app.routers import envios
from app.routers.voice_routes import get_transcriber
from app.services.transcription_service import TranscriptionResult
from tests.conftest import FLAC, MP3, WAV, auth_headers


class FakeTranscriber:
    """Devuelve la 'transcripción' según el formato del audio: WAV=uno, MP3=dos, FLAC=tres."""

    def transcribe(self, src, language):
        head = src.read(4)
        return TranscriptionResult({b"RIFF": "uno", b"ID3\x03": "dos", b"fLaC": "tres"}.get(head, "otra cosa"), 1.0)


@pytest.fixture()
def client(engine):
    t = persona_audio_frases_table("main")
    with engine.begin() as c:
        c.execute(t.insert(), [{"ID": "F1", "FRASE": "Uno", "ORDEN": 1}, {"ID": "F2", "FRASE": "Dos", "ORDEN": 2},
                               {"ID": "F3", "FRASE": "Tres", "ORDEN": 3}])
    app.dependency_overrides[get_engine] = lambda: engine
    app.dependency_overrides[get_transcriber] = lambda: FakeTranscriber()
    c = TestClient(app, raise_server_exceptions=False)
    c.headers.update(auth_headers(c))
    yield c
    app.dependency_overrides.clear()


def files(a=WAV, b=MP3, c=FLAC, ids=("F1", "F2", "F3")):
    return [
        ("audios", ("a.wav", io.BytesIO(a), "audio/wav")),
        ("audios", ("b.mp3", io.BytesIO(b), "audio/mpeg")),
        ("audios", ("c.flac", io.BytesIO(c), "audio/flac")),
    ], {"frase_ids": list(ids)}


def post(client, nombres="A", apellidos="B", **kw):
    f, data = files(**kw)
    return client.post("/api/envios", data=data, files=f)


def count_files() -> int:
    root = get_settings().AUDIO_ROOT
    return sum(1 for p in Path(root).rglob("*") if p.is_file()) if root.exists() else 0


def rows(engine):
    with engine.connect() as c:
        return c.execute(select(persona_audio_table("main"))).all()


def det_rows(engine):
    with engine.connect() as c:
        return c.execute(select(persona_audio_det_table("main"))).all()


def test_post_ok_and_get(client, engine):
    before = count_files()
    r = post(client, "José", "Núñez")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["estado"] == "pendiente" and body["tag"].startswith("ana-gil_")
    assert count_files() == before + 3
    assert rows(engine)[0].ESTADO == "pendiente"
    det = det_rows(engine)
    assert [d.ID_FRASE for d in det] == ["F1", "F2", "F3"]
    assert all(Path(d.RUTA_AUDIO).exists() and d.SIMILITUD == 1 for d in det)

    g = client.get(f"/api/envios/{body['id']}")
    assert g.status_code == 200 and g.json()["estado"] == "pendiente" and "ruta" not in g.text.lower()
    assert client.get("/api/envios/9999").status_code == 404


def test_error_state_has_generic_message(client, engine):
    body = post(client).json()
    with engine.begin() as c:
        c.exec_driver_sql("UPDATE PERSONA_AUDIO SET ESTADO='error', ERROR_MSG='ORA-12345 D:\\secreto'")
    g = client.get(f"/api/envios/{body['id']}").json()
    assert g["error"] == envios.GENERIC_PROCESSING_ERROR and "ORA" not in str(g)


def test_rejects_fake_audio_and_long_names(client, engine):
    assert post(client, a=b"MZ" + b"0" * 30).status_code == 422
    with engine.begin() as c:
        c.exec_driver_sql("UPDATE USUARIOS SET NOMBRES = '" + "ñ" * 51 + "'")
    r = post(client)
    assert r.status_code == 422 and "bytes" in r.json()["detail"]
    assert rows(engine) == [] and det_rows(engine) == []


def test_rejects_wrong_phrase_without_saving(client, engine):
    before = count_files()
    r = post(client, ids=("F2", "F1", "F3"))  # frases intercambiadas: los audios no coinciden
    assert r.status_code == 422 and "no coincide" in r.json()["detail"]
    assert rows(engine) == [] and count_files() == before


def test_requires_all_phrases_once(client, engine):
    assert post(client, ids=("F1", "F2", "F2")).status_code == 422
    assert post(client, ids=("F1", "F2", "NOPE")).status_code == 422
    assert rows(engine) == []


def test_tag_conflict_retries_and_cleans(client, engine, monkeypatch):
    first = post(client).json()
    tags_seq = iter([first["tag"], first["tag"], "a-b_ffffff"])
    monkeypatch.setattr(envios.tags, "generate_tag", lambda n, a: next(tags_seq))
    before = count_files()
    r = post(client)
    assert r.status_code == 201 and r.json()["tag"] == "a-b_ffffff"
    assert count_files() == before + 3  # los intentos fallidos no dejan archivos


def test_insert_failure_deletes_files_without_leaking(client, engine, monkeypatch):
    before = count_files()
    with engine.begin() as c:
        c.exec_driver_sql("DROP TABLE PERSONA_AUDIO")
    r = post(client)
    assert r.status_code == 500
    assert "PERSONA_AUDIO" not in r.text and "no such table" not in r.text
    assert count_files() == before


def test_always_gives_up_after_5_conflicts(client, engine, monkeypatch):
    first = post(client).json()
    monkeypatch.setattr(envios.tags, "generate_tag", lambda n, a: first["tag"])
    assert post(client).status_code == 503


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}
