"""Definición Core de la tabla EXISTENTE GINNET_AUDIO.PERSONA_AUDIO (solo para consultas; no se crea ni modifica)."""
from __future__ import annotations

import enum
from functools import lru_cache

from sqlalchemy import TIMESTAMP, Column, Integer, MetaData, String, Table
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
