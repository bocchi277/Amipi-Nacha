"""
Pytest configuration & fixtures for DB schema and API testing.
"""
import pytest
import pytest_asyncio
from typing import AsyncGenerator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.db.session import get_async_db
from app.main import app

# Async test engine using NullPool
test_async_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    poolclass=NullPool,
)

TestingAsyncSessionLocal = async_sessionmaker(
    test_async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a fresh transactional DB session for each test."""
    async with TestingAsyncSessionLocal() as session:
        # Ensure schema migrations for newly added columns
        await session.execute(
            text("ALTER TABLE payments ADD COLUMN IF NOT EXISTS invoice_breakdown JSONB;")
        )
        # Truncate tables for test isolation
        await session.execute(
            text("TRUNCATE TABLE audit_logs, payments, nacha_files, vendors, upload_batches, users CASCADE;")
        )
        await session.commit()


        # Override FastAPI dependency to use test session
        async def _override_get_db():
            yield session

        app.dependency_overrides[get_async_db] = _override_get_db

        yield session
        await session.rollback()
        app.dependency_overrides.clear()
