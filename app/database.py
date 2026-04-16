import logging
import os

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.database_url,
    echo=settings.app_debug,
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_size=1,
    max_overflow=4,
)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, connection_record):
    """Enable WAL mode and busy timeout on every SQLite connection."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()

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
        ("videos", "channel_name", "VARCHAR(256)"),
        ("videos", "channel_url", "VARCHAR(512)"),
        ("videos", "description", "TEXT"),
        ("videos", "upload_date", "VARCHAR(20)"),
        ("videos", "view_count", "INTEGER"),
        ("videos", "like_count", "INTEGER"),
        ("videos", "tags_json", "TEXT"),
        ("videos", "top_comments_json", "TEXT"),
        ("videos", "category", "VARCHAR(128)"),
    ]
    for table, column, col_type in migrations:
        try:
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
            logger.info("DB migration: added column %s.%s", table, column)
        except Exception:
            pass  # column already exists


def _ensure_database_dir() -> None:
    """Create parent directory of the database file so SQLite can create the file."""
    url = settings.database_url
    if "sqlite" in url and "///" in url:
        path = url.split("///", 1)[-1].split("?")[0].lstrip("./")
        if path and path != ":memory:":
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)


async def init_db() -> None:
    from app.models import db  # noqa: F401 — ensure models are registered

    _ensure_database_dir()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _add_missing_columns(conn)


async def get_session() -> AsyncSession:  # type: ignore[return]
    async with AsyncSessionLocal() as session:
        yield session
