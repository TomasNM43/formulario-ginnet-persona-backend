import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers.voice_routes import get_transcriber
from app.services import phrase_matcher
from app.services.transcription_service import AudioDecodeError, TranscriptionResult
from tests.conftest import auth_headers


class FakeTranscriber:
    def __init__(self, text="Hola, ¿cómo estás?", error=None):
        self.text, self.error = text, error

    def transcribe(self, path, language):
        if self.error:
            raise self.error
        return TranscriptionResult(self.text, 1.5)


@pytest.fixture()
def client(engine):
    from app.config import get_settings
    from app.db import get_engine
    from app.models import persona_audio_frases_table

    t = persona_audio_frases_table(get_settings().DB_SCHEMA)
    t.metadata.create_all(engine)
    with engine.begin() as c:
        c.execute(t.insert(), [
            {"ID": "F2", "FRASE": "Segunda frase", "ORDEN": 2},
            {"ID": "F1", "FRASE": "Hola, ¿cómo estás?", "ORDEN": 1},
        ])
    holder = {"t": FakeTranscriber()}
    app.dependency_overrides[get_transcriber] = lambda: holder["t"]
    app.dependency_overrides[get_engine] = lambda: engine
    c = TestClient(app)
    c.holder = holder
    c.headers.update(auth_headers(c))
    yield c
    app.dependency_overrides.clear()


def test_list_phrases_ordered(client):
    r = client.get("/api/voice/phrases")
    assert [p["id"] for p in r.json()] == ["F1", "F2"]


def test_verify_by_phrase_id(client):
    r = client.post(
        "/api/voice/verify-phrase",
        files={"file": ("a.webm", b"data", "audio/webm")},
        data={"phrase_id": "F1", "expected_phrase": "ignorada"},
    )
    assert r.status_code == 200 and r.json()["match"] and r.json()["phrase_id"] == "F1"


def test_verify_unknown_phrase_id(client):
    r = client.post(
        "/api/voice/verify-phrase",
        files={"file": ("a.webm", b"data", "audio/webm")},
        data={"phrase_id": "NOPE"},
    )
    assert r.status_code == 404


def post(client, name="a.webm", ctype="audio/webm", phrase="hola como estas", **form):
    return client.post(
        "/api/voice/verify-phrase",
        files={"file": (name, b"data", ctype)},
        data={"expected_phrase": phrase, **form},
    )


def test_match(client):
    r = post(client)
    assert r.status_code == 200
    body = r.json()
    assert body["match"] and body["similarity"] == 1.0 and body["missing_words"] == []


def test_mismatch_missing_words(client):
    client.holder["t"] = FakeTranscriber("hola")
    body = post(client).json()
    assert not body["match"] and body["missing_words"] == ["como", "estas"]


def test_silence(client):
    client.holder["t"] = FakeTranscriber("")
    r = post(client)
    assert r.status_code == 200 and r.json()["transcription"] == "" and not r.json()["match"]


@pytest.mark.parametrize(
    "kwargs,status",
    [
        ({"name": "a.txt"}, 415),
        ({"ctype": "text/plain"}, 415),
        ({"phrase": "  "}, 422),
        ({"threshold": "1.5"}, 422),
    ],
)
def test_validation(client, kwargs, status):
    assert post(client, **kwargs).status_code == status


def test_decode_error(client):
    client.holder["t"] = FakeTranscriber(error=AudioDecodeError("x"))
    assert post(client).status_code == 422


def test_unexpected_error(client):
    client.holder["t"] = FakeTranscriber(error=RuntimeError("boom"))
    assert post(client).status_code == 500


def test_normalize():
    assert phrase_matcher.normalize("  ¡Canción, ÁÉÍ!  ok ") == "cancion aei ok"
