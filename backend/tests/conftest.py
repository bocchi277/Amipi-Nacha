"""
Pytest configuration & fixtures for DB schema and API testing.
"""
import os
import re
import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import get_current_user, get_optional_current_user
from app.config import settings
from app.core.security import hash_password
from app.db.session import get_async_db
from app.main import app
from app.models import User, UserRole

# ---------------------------------------------------------------------------
# SAFETY GUARD
# ---------------------------------------------------------------------------
# The `db_session` fixture TRUNCATEs every application table. Pointed at a real
# deployment that would destroy production data, so refuse to run unless the target
# database is unambiguously a throwaway test database.
_ALLOWED_DB_NAME = re.compile(r"(test|_ci|scratch)", re.IGNORECASE)


def _database_name(url: str) -> str:
    tail = url.rsplit("/", 1)[-1]
    return tail.split("?", 1)[0]


def _assert_safe_test_database() -> None:
    url = settings.DATABASE_URL or ""
    db_name = _database_name(url)

    if os.getenv("AMIPI_ALLOW_UNSAFE_TEST_DB") == "1":
        return

    if not db_name or not _ALLOWED_DB_NAME.search(db_name):
        raise RuntimeError(
            "\n"
            "==================================================================\n"
            " REFUSING TO RUN TESTS — UNSAFE TARGET DATABASE\n"
            "==================================================================\n"
            f" Target database : {db_name!r}\n"
            "\n"
            " The test suite TRUNCATEs all application tables. The database name\n"
            " must contain 'test', '_ci' or 'scratch' to prove it is disposable.\n"
            "\n"
            " Set DATABASE_URL to a dedicated test database, e.g.:\n"
            "   postgresql+asyncpg://amipi:amipipass@127.0.0.1:5432/amipi_ach_test\n"
            "\n"
            " To override deliberately (NOT recommended):\n"
            "   AMIPI_ALLOW_UNSAFE_TEST_DB=1\n"
            "==================================================================\n"
        )


_assert_safe_test_database()


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_auth: test performs its own authentication; do not inject a default "
        "authenticated user. Required for any test asserting 401/403 behaviour.",
    )


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
        # Truncate tables for test isolation. Schema itself comes from Alembic
        # (`alembic upgrade head`) — tests no longer patch columns at runtime.
        await session.execute(
            text("TRUNCATE TABLE audit_logs, vendor_remittances, vendor_change_requests, payments, nacha_files, vendors, upload_batches, users CASCADE;")
        )
        await session.commit()

        # Override FastAPI dependency to use test session
        async def _override_get_db():
            yield session

        app.dependency_overrides[get_async_db] = _override_get_db

        yield session
        await session.rollback()
        app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function", autouse=True)
async def default_authenticated_user(request, db_session) -> AsyncGenerator[User | None, None]:
    """
    Inject a default authenticated administrator for business-logic tests.

    Money-handling and bank-data endpoints now correctly require authentication. The
    majority of the suite exercises business logic rather than access control, so a
    default identity is supplied here instead of threading tokens through every call.

    Tests that assert authentication or authorization behaviour must be decorated with
    ``@pytest.mark.real_auth`` so no identity is injected and the genuine dependency
    chain (token parsing, role checks) runs untouched.
    """
    if "real_auth" in request.keywords:
        yield None
        return

    suffix = uuid.uuid4().hex[:8]
    user = User(
        email=f"default_test_admin_{suffix}@amipi.test",
        username=f"default_test_admin_{suffix}",
        password_hash=hash_password("DefaultTestPassword123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_current_user] = lambda: user

    yield user

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_optional_current_user, None)
