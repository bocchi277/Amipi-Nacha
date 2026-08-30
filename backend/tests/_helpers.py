"""
Shared test helpers.

Registration deliberately cannot self-assign privileged roles (that was a
privilege-escalation vulnerability), so tests that need an administrator must
provision one directly against the database instead of through the public API.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.business_dates import default_effective_date
from app.core.security import hash_password
from app.models import User, UserRole


async def create_admin_user(
    db_session: AsyncSession,
    username: str,
    email: str,
    password: str,
) -> User:
    """
    Provision an administrator account directly in the database.

    Mirrors what an operator would do via `scripts/create_user.py`, bypassing the
    public registration endpoint which always assigns the standard user role.
    """
    return await _upsert_user(db_session, username, email, password, UserRole.ADMIN)


async def create_standard_user(
    db_session: AsyncSession,
    username: str,
    email: str,
    password: str,
) -> User:
    """
    Provision a standard (non-admin) account directly in the database.

    ``POST /auth/register`` is administrator-only now: leaving it public gave anyone on
    the internet an account, and a standard account was enough to read every vendor's
    bank details. Tests that need an ordinary user create one here instead.
    """
    return await _upsert_user(db_session, username, email, password, UserRole.USER)


async def _upsert_user(
    db_session: AsyncSession,
    username: str,
    email: str,
    password: str,
    role: UserRole,
) -> User:
    email_clean = email.strip().lower()
    username_clean = username.strip()

    existing = await db_session.execute(
        select(User).where((User.email == email_clean) | (User.username == username_clean))
    )
    user = existing.scalar_one_or_none()
    if user is not None:
        user.role = role
        user.password_hash = hash_password(password)
        user.is_active = True
        await db_session.commit()
        await db_session.refresh(user)
        return user

    user = User(
        email=email_clean,
        username=username_clean,
        password_hash=hash_password(password),
        role=role,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def valid_effective_date() -> date:
    """
    An effective entry date that passes banking-day validation.

    Effective dates are now validated: past dates, weekends and Federal Reserve
    holidays are rejected because ACH will not settle on them. Tests must therefore
    compute a valid date rather than hardcoding one, which would rot as time passes.
    """
    return default_effective_date()


def valid_effective_date_str() -> str:
    """``valid_effective_date`` as ``YYYY-MM-DD`` for JSON payloads."""
    return valid_effective_date().isoformat()


def valid_effective_date_yymmdd() -> str:
    """``valid_effective_date`` as ``YYMMDD`` for NACHA fields."""
    return valid_effective_date().strftime("%y%m%d")
