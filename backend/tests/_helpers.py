"""
Shared test helpers.

Registration deliberately cannot self-assign privileged roles (that was a
privilege-escalation vulnerability), so tests that need an administrator must
provision one directly against the database instead of through the public API.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    email_clean = email.strip().lower()
    username_clean = username.strip()

    existing = await db_session.execute(
        select(User).where((User.email == email_clean) | (User.username == username_clean))
    )
    user = existing.scalar_one_or_none()
    if user is not None:
        user.role = UserRole.ADMIN
        user.password_hash = hash_password(password)
        user.is_active = True
        await db_session.commit()
        await db_session.refresh(user)
        return user

    user = User(
        email=email_clean,
        username=username_clean,
        password_hash=hash_password(password),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user
