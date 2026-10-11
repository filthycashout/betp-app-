from __future__ import annotations

import os
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


class DatabaseUnavailable(RuntimeError):
    """Raised without exposing credentials when the governed Postgres store is unavailable."""


def database_url() -> str:
    return (
        os.getenv("PHILTHY_SPORTS_AI_DATABASE_URL", "").strip()
        or os.getenv("DATABASE_URL", "").strip()
    )


def _sqlalchemy_postgres_url(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    raise DatabaseUnavailable("sports_ai requires a PostgreSQL DATABASE_URL")


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    url = database_url()
    if not url:
        raise DatabaseUnavailable("sports_ai PostgreSQL DATABASE_URL is not configured")
    try:
        return create_engine(
            _sqlalchemy_postgres_url(url),
            pool_pre_ping=True,
            future=True,
            connect_args={"connect_timeout": 5},
        )
    except Exception as exc:
        raise DatabaseUnavailable("sports_ai PostgreSQL engine could not be created") from exc


def reset_engine_cache() -> None:
    """Test/support hook. It never changes persistent data."""

    engine = get_engine.cache_info()
    if engine.currsize:
        try:
            get_engine().dispose()
        except Exception:
            pass
    get_engine.cache_clear()
