import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.database_url,
    echo=settings.app_debug,
    connect_args={"check_same_thread": False},
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def _add_missing_columns(conn) -> None:
    """Safely add new columns to existing tables (SQLite-compatible)."""
    migrations = [
        ("analysis_runs", "current_step", "VARCHAR(64)"),
    ]
    for table, column, col_type in migrations:
        try:
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
            logger.info("DB migration: added column %s.%s", table, column)
        except Exception:
            pass  # column already exists


async def init_db() -> None:
    from app.models import db  # noqa: F401 — ensure models are registered

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _add_missing_columns(conn)


async def get_session() -> AsyncSession:  # type: ignore[return]
    async with AsyncSessionLocal() as session:
        yield session
