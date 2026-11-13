"""Engine SQLAlchemy sobre python-oracledb en modo thin. Un pool por proceso."""
from __future__ import annotations

from functools import lru_cache

import oracledb
from sqlalchemy import Engine, create_engine

from .config import get_settings


@lru_cache
def get_engine() -> Engine:
    s = get_settings()
    password = s.DB_PASSWORD.get_secret_value()

    def creator() -> oracledb.Connection:
        # Sin init_oracle_client(): python-oracledb usa modo thin.
        return oracledb.connect(user=s.DB_USER, password=password, dsn=s.DB_DSN)

    return create_engine(
        "oracle+oracledb://",
        creator=creator,
        pool_size=s.DB_POOL_MIN,
        max_overflow=s.DB_POOL_MAX - s.DB_POOL_MIN,
        pool_timeout=30,
        pool_recycle=1800,
        pool_pre_ping=True,
        hide_parameters=True,
    )
