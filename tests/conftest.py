import os
import tempfile
from datetime import datetime
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="ginnet_tests_"))
os.environ.update(
    {
        "ENV_FILE": str(_TMP / "no-existe.env"),
        "DB_USER": "u",
        "DB_PASSWORD": "super-secreto",
        "DB_DSN": "localhost:1521/X",
        "DB_SCHEMA": "main",  # esquema por defecto de SQLite
        "AUDIO_ROOT": str(_TMP / "audios"),
        "LOG_DIR": str(_TMP / "logs"),
    }
)

import pytest  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.models import persona_audio_table  # noqa: E402

WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 64
MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 64
FLAC = b"fLaC" + b"\x00" * 64


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})

    @event.listens_for(eng, "connect")
    def _fns(dbapi_conn, _rec):
        dbapi_conn.create_function("systimestamp", 0, lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"))

    t = persona_audio_table("main")
    t.metadata.create_all(eng)
    # Simula PERSONA_AUDIO_TAG_UK
    with eng.begin() as c:
        c.exec_driver_sql('CREATE UNIQUE INDEX persona_audio_tag_uk ON PERSONA_AUDIO ("TAG")')
    yield eng
    eng.dispose()
