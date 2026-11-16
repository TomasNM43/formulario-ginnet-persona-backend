import io
import re
from datetime import datetime
from pathlib import Path

import pytest

from app.schemas import EnvioIn
from app.services import storage, tags
from tests.conftest import FLAC, MP3, WAV

ALLOWED = frozenset({"wav", "mp3", "flac"})


def test_normalize_removes_accents_and_symbols():
    assert tags.normalize("  José  Ñandú ") == "jose-nandu"
    assert tags.normalize("O'Brien; DROP") == "obrien-drop"


def test_tag_format_and_limit():
    tag = tags.generate_tag("María José", "Pérez Núñez")
    assert tag.startswith("maria-jose-perez-nunez_")

    assert re.fullmatch(r"[a-z0-9\-_]+_[0-9a-f]{6}", tag)
    long = tags.generate_tag("a" * 150, "b" * 150)
    assert len(long.encode()) <= 200 and long[-7] == "_"


def test_tags_are_unique_and_never_empty():
    assert len({tags.generate_tag("Ana", "Gil") for _ in range(50)}) > 40
    assert tags.generate_tag("李", "!!!").startswith("x-x_")


def test_name_byte_validation():
    assert EnvioIn(nombres="ñ" * 50, apellidos="Gil").nombres == "ñ" * 50  # 100 bytes exactos
    with pytest.raises(ValueError):
        EnvioIn(nombres="ñ" * 51, apellidos="Gil")  # 102 bytes
    with pytest.raises(ValueError):
        EnvioIn(nombres="   ", apellidos="Gil")


def test_path_length_in_bytes(tmp_path: Path):
    now = datetime(2026, 1, 5)
    p = storage.build_paths(tmp_path, "ana-gil_abc123", ["wav", "mp3"], now)
    assert p.files[0] == tmp_path / "2026" / "01" / "ana-gil_abc123" / "frase-1.wav"
    assert p.files[1].name == "frase-2.mp3"
    with pytest.raises(storage.PathTooLongError):
        storage.build_paths(tmp_path / ("ñ" * 240), "t", ["wav"], now)  # 480 bytes solo en la raíz


@pytest.mark.parametrize("data,name", [(WAV, "a.wav"), (MP3, "a.MP3"), (FLAC, "a.flac")])
def test_valid_audio(data, name):
    assert storage.validate_audio_file(io.BytesIO(data), name, ALLOWED, 1024) == name.split(".")[-1].lower()


def test_invalid_audio():
    with pytest.raises(storage.StorageError):
        storage.validate_audio_file(io.BytesIO(b"MZ" + b"\0" * 50), "virus.wav", ALLOWED, 1024)  # no es audio
    with pytest.raises(storage.StorageError):
        storage.validate_audio_file(io.BytesIO(WAV), "a.txt", ALLOWED, 1024)  # extensión
    with pytest.raises(storage.StorageError):
        storage.validate_audio_file(io.BytesIO(WAV), "a.wav", ALLOWED, 10)  # tamaño
    with pytest.raises(storage.StorageError):
        storage.validate_audio_file(io.BytesIO(MP3), "a.wav", ALLOWED, 1024)  # extensión != contenido
    with pytest.raises(storage.StorageError):
        storage.validate_audio_file(io.BytesIO(b""), "a.wav", ALLOWED, 1024)
