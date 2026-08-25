"""
Authentication FastAPI Router.

Provides registration, login (JWT generation), and user profile endpoints.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_async_db
from app.models import User, UserRole

router = APIRouter(prefix="/auth", tags=["Authentication"])


class RegisterUserSchema(BaseModel):
    email: str
    username: str
    password: str
    role: Optional[UserRole] = None


class TokenResponseSchema(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str


class UserProfileSchema(BaseModel):
    id: str
    email: str
    username: str
    role: str
    is_active: bool


@router.post("/register", response_model=UserProfileSchema, status_code=status.HTTP_201_CREATED)
async def register_user(
    payload: RegisterUserSchema,
    db: AsyncSession = Depends(get_async_db),
):
    """Register a new standard user account."""
    if len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters long.")

    # Check duplicate email
    res_e = await db.execute(select(User).where(User.email == payload.email.strip().lower()))
    if res_e.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered.")

    # Check duplicate username
    res_u = await db.execute(select(User).where(User.username == payload.username.strip()))
    if res_u.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already taken.")

    pw_hash = hash_password(payload.password)
    user = User(
        email=payload.email.strip().lower(),
        username=payload.username.strip(),
        password_hash=pw_hash,
        role=payload.role or UserRole.USER,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return UserProfileSchema(
        id=str(user.id),
        email=user.email,
        username=user.username,
        role=user.role.value,
        is_active=user.is_active,
    )


@router.post("/login", response_model=TokenResponseSchema)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_async_db),
):
    """Authenticate credentials and return JWT Bearer token."""
    # Find user by username or email
    username_input = form_data.username.strip()
    res = await db.execute(
        select(User).where(
            (User.username == username_input) | (User.email == username_input.lower())
        )
    )
    user = res.scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user account.")

    access_token = create_access_token(data={"sub": str(user.id), "role": user.role.value})
    return TokenResponseSchema(
        access_token=access_token,
        token_type="bearer",
        role=user.role.value,
        username=user.username,
    )


@router.get("/me", response_model=UserProfileSchema)
async def get_current_user_profile(
    current_user: User = Depends(get_current_user),
):
    """Fetch current logged-in user profile."""
    return UserProfileSchema(
        id=str(current_user.id),
        email=current_user.email,
        username=current_user.username,
        role=current_user.role.value,
        is_active=current_user.is_active,
    )
