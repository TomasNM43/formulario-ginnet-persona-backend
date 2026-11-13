import pytest
from pydantic import SecretStr

from app.config import load_settings

REQUIRED = ["DB_USER", "DB_PASSWORD", "DB_DSN", "AUDIO_ROOT", "LOG_DIR"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in REQUIRED + ["DB_SCHEMA", "ALLOWED_EXTENSIONS", "DB_POOL_MIN", "DB_POOL_MAX", "CORS_ORIGINS"]:
        monkeypatch.delenv(k, raising=False)


def write_env(tmp_path, extra=""):
    f = tmp_path / ".env"
    f.write_text(
        "DB_USER=app\nDB_PASSWORD=p4ss\nDB_DSN=host:1521/SVC\nAUDIO_ROOT=D:\\audios\nLOG_DIR=C:\\logs\n" + extra,
        encoding="utf-8",
    )
    return f


def test_loads_env_and_defaults(tmp_path):
    s = load_settings(write_env(tmp_path, "ALLOWED_EXTENSIONS=wav, MP3\nCORS_ORIGINS=http://a,http://b\n"))
    assert isinstance(s.DB_PASSWORD, SecretStr)
    assert s.DB_SCHEMA == "GINNET_AUDIO" and s.MAX_UPLOAD_MB == 200 and s.STUCK_JOB_MINUTES == 15
    assert s.allowed_extensions == {"wav", "mp3"}
    assert s.cors_origins == ["http://a", "http://b"]
    assert "p4ss" not in repr(s) and "p4ss" not in str(s.model_dump())


def test_missing_required_fails(tmp_path):
    f = tmp_path / ".env"
    f.write_text("DB_USER=app\n", encoding="utf-8")
    with pytest.raises(Exception) as ei:
        load_settings(f)
    assert "DB_PASSWORD" in str(ei.value) and "DB_DSN" in str(ei.value)


@pytest.mark.parametrize("extra", ["DB_SCHEMA=x; drop\n", "DB_POOL_MIN=5\nDB_POOL_MAX=2\n", "ALLOWED_EXTENSIONS=exe\n"])
def test_invalid_values(tmp_path, extra):
    with pytest.raises(Exception):
        load_settings(write_env(tmp_path, extra))
