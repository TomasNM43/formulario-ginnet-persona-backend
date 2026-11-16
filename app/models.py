"""Definición Core de la tabla EXISTENTE GINNET_AUDIO.PERSONA_AUDIO (solo para consultas; no se crea ni modifica)."""
from __future__ import annotations

import enum
from functools import lru_cache

from sqlalchemy import TIMESTAMP, Column, Integer, MetaData, Numeric, String, Table
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.expression import FunctionElement


class sys_timestamp(FunctionElement):
    """SYSTIMESTAMP de Oracle (se escribe sin paréntesis)."""

    type = TIMESTAMP()
    inherit_cache = True
    name = "systimestamp"


@compiles(sys_timestamp, "oracle")
def _oracle_systimestamp(element, compiler, **kw) -> str:  # noqa: ANN001
    return "SYSTIMESTAMP"


@compiles(sys_timestamp)
def _default_systimestamp(element, compiler, **kw) -> str:  # noqa: ANN001
    return "systimestamp()"  # solo tests (SQLite con función registrada)


class Estado(str, enum.Enum):
    PENDIENTE = "pendiente"
    PROCESANDO = "procesando"
    LISTO = "listo"
    ERROR = "error"


@lru_cache
def usuarios_table(schema: str) -> Table:
    """Tabla EXISTENTE GINNET_AUDIO.USUARIOS (solo lectura). CLAVE = código de alumno."""
    return Table(
        "USUARIOS",
        MetaData(),
        Column("ID_USUARIO", Integer, primary_key=True),
        Column("NOMBRES", String(100), nullable=False),
        Column("APELLIDOS", String(100), nullable=False),
        Column("CORREO", String(200), nullable=False),
        Column("CLAVE", String(100), nullable=False),
        schema=schema,
    )


@lru_cache
def persona_audio_det_table(schema: str) -> Table:
    """Tabla hija EXISTENTE: un registro por audio/frase de cada envío."""
    return Table(
        "PERSONA_AUDIO_DET",
        MetaData(),
        Column("ID_DET", Integer, primary_key=True),
        Column("ID_PERSONA_AUDIO", Integer, nullable=False),
        Column("TAG", String(50), nullable=False),
        Column("ID_FRASE", String(20), nullable=False),
        Column("ORDEN", Numeric, nullable=False),
        Column("RUTA_AUDIO", String(500), nullable=False),
        Column("TRANSCRIPCION", String(500)),
        Column("SIMILITUD", Numeric(5, 4)),
        Column("FECHA_CREACION", TIMESTAMP),
        schema=schema,
    )


@lru_cache
def persona_audio_frases_table(schema: str) -> Table:
    return Table(
        "PERSONA_AUDIO_FRASES",
        MetaData(),
        Column("ID", String(20), primary_key=True),
        Column("FRASE", String(500)),
        Column("ORDEN", Numeric, nullable=False),
        schema=schema,
    )


@lru_cache
def persona_audio_table(schema: str) -> Table:
    return Table(
        "PERSONA_AUDIO",
        MetaData(),
        Column("ID_PERSONA_AUDIO", Integer, primary_key=True),
        Column("NOMBRES", String(100)),
        Column("APELLIDOS", String(100)),
        Column("TAG", String(200), nullable=False),
        Column("RUTA_REFERENCIA", String(500)),
        Column("RUTA_PRUEBA", String(500)),
        Column("ESTADO", String(20), nullable=False),
        Column("ERROR_MSG", String(1000)),
        Column("FECHA_CREACION", TIMESTAMP),
        Column("FECHA_INICIO", TIMESTAMP),
        schema=schema,
    )
