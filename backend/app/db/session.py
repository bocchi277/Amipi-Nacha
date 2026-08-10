"""
Database session management for Async & Sync SQLAlchemy.
"""
from collections.abc import AsyncGenerator
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings

# Async engine & session (for FastAPI async route handlers)
async_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Sync engine & session (for Alembic migrations and sync scripts)
sync_engine = create_engine(
    settings.SYNC_DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

SyncSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=sync_engine,
)


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency for providing async DB sessions in FastAPI endpoint routes.

    The session is NOT auto-committed — route handlers / service layers
    must call ``await session.commit()`` explicitly to persist changes.
    This prevents accidental commits of partial / invalid state.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
