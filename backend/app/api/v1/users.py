"""
User Management API Router (Admin Only).

Provides administrative operations for user accounts:
- List all users
- Provision new standard or administrator accounts
- Activate / Deactivate user accounts
- Reset user passwords
All operations record audit trail entries in AuditLog.
"""
from datetime import datetime
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.core.security import hash_password
from app.db.session import get_async_db
from app.models import AuditLog, User, UserRole

router = APIRouter(prefix="/users", tags=["User Management"])


class UserResponseSchema(BaseModel):
    id: str
    email: str
    username: str
    role: str
    is_active: bool
    created_at: Optional[datetime] = None


class CreateUserSchema(BaseModel):
    email: str
    username: str
    password: str
    role: Optional[UserRole] = UserRole.USER


class UpdateUserStatusSchema(BaseModel):
    is_active: bool


class ResetPasswordSchema(BaseModel):
    new_password: str


@router.get("", response_model=List[UserResponseSchema])
async def list_users(
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    """List all registered system user accounts (Admin only)."""
    stmt = select(User).order_by(desc(User.created_at))
    res = await db.execute(stmt)
    users = res.scalars().all()

    return [
        UserResponseSchema(
            id=str(u.id),
            email=u.email,
            username=u.username,
            role=u.role.value,
            is_active=u.is_active,
            created_at=u.created_at,
        )
        for u in users
    ]


@router.post("", response_model=UserResponseSchema, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: CreateUserSchema,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    """Provision a new user account (Admin only)."""
    email_clean = payload.email.strip().lower()
    username_clean = payload.username.strip()

    if not email_clean or "@" not in email_clean:
        raise HTTPException(status_code=400, detail="Valid email address is required.")
    if not username_clean:
        raise HTTPException(status_code=400, detail="Username is required.")
    if len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters long.")

    # Check for duplicate email
    res_e = await db.execute(select(User).where(User.email == email_clean))
    if res_e.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email is already registered.")

    # Check for duplicate username
    res_u = await db.execute(select(User).where(User.username == username_clean))
    if res_u.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username is already taken.")

    pw_hash = hash_password(payload.password)
    user_role = payload.role or UserRole.USER
    new_user = User(
        email=email_clean,
        username=username_clean,
        password_hash=pw_hash,
        role=user_role,
        is_active=True,
    )
    db.add(new_user)

    # Record in AuditLog
    audit_entry = AuditLog(
        user_id=admin_user.id,
        action="USER_CREATED",
        entity_type="user",
        entity_id=username_clean,
        details={
            "created_by_admin": admin_user.username,
            "created_username": username_clean,
            "created_email": email_clean,
            "role": user_role.value,
        },
    )
    db.add(audit_entry)

    await db.commit()
    await db.refresh(new_user)

    return UserResponseSchema(
        id=str(new_user.id),
        email=new_user.email,
        username=new_user.username,
        role=new_user.role.value,
        is_active=new_user.is_active,
        created_at=new_user.created_at,
    )


@router.put("/{user_id}/status", response_model=UserResponseSchema)
async def update_user_status(
    user_id: str,
    payload: UpdateUserStatusSchema,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    """Activate or deactivate a user account (Admin only)."""
    try:
        uid = uuid.UUID(user_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid user ID format.")

    if uid == admin_user.id and not payload.is_active:
        raise HTTPException(status_code=400, detail="Administrators cannot deactivate their own account.")

    res = await db.execute(select(User).where(User.id == uid))
    target_user = res.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="User account not found.")

    target_user.is_active = payload.is_active

    audit_entry = AuditLog(
        user_id=admin_user.id,
        action="USER_STATUS_UPDATED",
        entity_type="user",
        entity_id=target_user.username,
        details={
            "updated_by_admin": admin_user.username,
            "target_user_id": str(target_user.id),
            "target_username": target_user.username,
            "is_active": payload.is_active,
        },
    )
    db.add(audit_entry)
    await db.commit()
    await db.refresh(target_user)

    return UserResponseSchema(
        id=str(target_user.id),
        email=target_user.email,
        username=target_user.username,
        role=target_user.role.value,
        is_active=target_user.is_active,
        created_at=target_user.created_at,
    )


@router.post("/{user_id}/reset-password")
async def reset_user_password(
    user_id: str,
    payload: ResetPasswordSchema,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    """Admin reset password for a specified user account."""
    try:
        uid = uuid.UUID(user_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid user ID format.")

    if len(payload.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters long.")

    res = await db.execute(select(User).where(User.id == uid))
    target_user = res.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="User account not found.")

    target_user.password_hash = hash_password(payload.new_password)

    audit_entry = AuditLog(
        user_id=admin_user.id,
        action="USER_PASSWORD_RESET",
        entity_type="user",
        entity_id=target_user.username,
        details={
            "reset_by_admin": admin_user.username,
            "target_username": target_user.username,
        },
    )
    db.add(audit_entry)
    await db.commit()

    return {"status": "ok", "message": f"Password reset successfully for user {target_user.username}."}
