from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

MAX_PATH_BYTES = 500
CHUNK_SIZE = 1024 * 1024


class StorageError(Exception):
    """Error de validación/almacenamiento con mensaje seguro para el cliente."""


class PathTooLongError(StorageError):
    pass


class FileCollisionError(StorageError):
    """La carpeta del tag ya existe (colisión de tag): se debe reintentar con otro sufijo."""


def get_extension(filename: str | None, allowed: frozenset[str]) -> str:
    ext = Path(filename or "").suffix.lower().lstrip(".")
    if ext not in allowed:
        raise StorageError(f"Formato no permitido. Formatos válidos: {', '.join(sorted(allowed))}")
    return ext


def get_size(fileobj: BinaryIO) -> int:
    fileobj.seek(0, 2)
    size = fileobj.tell()
    fileobj.seek(0)
    return size


def detect_audio_format(header: bytes) -> str | None:
    """Detecta el formato real por cabecera (no confía en la extensión)."""
    if header[:4] == b"RIFF" and header[8:12] == b"WAVE":
        return "wav"
    if header[:4] == b"fLaC":
        return "flac"
    if header[:4] == b"OggS":
        return "ogg"
    if header[:3] == b"ID3" or (len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0):
        return "mp3"
    return None


def validate_audio_file(fileobj: BinaryIO, filename: str | None, allowed: frozenset[str], max_bytes: int) -> str:
    """Valida extensión, tamaño y cabecera. Devuelve la extensión. Deja el cursor en 0."""
    ext = get_extension(filename, allowed)
    size = get_size(fileobj)
    if size == 0:
        raise StorageError("El archivo está vacío")
    if size > max_bytes:
        raise StorageError(f"El archivo excede el tamaño máximo de {max_bytes // (1024 * 1024)} MB")
    header = fileobj.read(16)
    fileobj.seek(0)
    if detect_audio_format(header) != ext:
        raise StorageError("El contenido del archivo no corresponde a un audio válido de ese formato")
    return ext


@dataclass(frozen=True)
class AudioPaths:
    folder: Path
    referencia: Path
    prueba: Path


def build_paths(root: Path, tag: str, ext_ref: str, ext_test: str, now: datetime | None = None) -> AudioPaths:
    """`{root}\\{yyyy}\\{mm}\\{tag}\\referencia.{ext}` y `prueba.{ext}`; valida 500 bytes UTF-8."""
    now = now or datetime.now()
    folder = root / f"{now:%Y}" / f"{now:%m}" / tag
    paths = AudioPaths(folder, folder / f"referencia.{ext_ref}", folder / f"prueba.{ext_test}")
    for p in (paths.referencia, paths.prueba):
        if len(str(p).encode("utf-8")) > MAX_PATH_BYTES:
            raise PathTooLongError("La ruta de almacenamiento resultante es demasiado larga")
    return paths


def save_files(paths: AudioPaths, referencia: BinaryIO, prueba: BinaryIO) -> None:
    """Copia por bloques. Si falla, no deja residuos."""
    try:
        paths.folder.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise FileCollisionError("tag en uso") from exc
    try:
        for dest, src in ((paths.referencia, referencia), (paths.prueba, prueba)):
            src.seek(0)
            with open(dest, "xb") as out:
                shutil.copyfileobj(src, out, CHUNK_SIZE)
    except BaseException:
        remove_folder(paths.folder)
        raise


def remove_folder(folder: Path) -> None:
    shutil.rmtree(folder, ignore_errors=True)
