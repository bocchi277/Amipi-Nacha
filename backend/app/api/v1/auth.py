"""
Authentication FastAPI Router.

Provides registration, login (JWT generation), and user profile endpoints.
"""
from collections import defaultdict
from typing import Optional
import re
import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_async_db
from app.models import AuditLog, User, UserRole

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Pragmatic email shape check: local-part@domain.tld with no whitespace.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")

# ---------------------------------------------------------------------------
# Login throttling
# ---------------------------------------------------------------------------
# In-process sliding window keyed on (client IP, username). Deliberately simple and
# dependency-free; a multi-worker deployment should move this to Redis so the limit
# is shared, but even per-worker throttling defeats naive password guessing, which
# was previously completely unrestricted.
_MAX_FAILED_LOGINS = 8
_LOGIN_WINDOW_SECONDS = 300
_LOGIN_LOCKOUT_SECONDS = 300
_failed_logins: dict[str, list[float]] = defaultdict(list)


def _client_ip(request: Request) -> str:
    """Best-effort client IP, honouring the proxy header used by Render/Netlify."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _prune(key: str, now: float) -> list[float]:
    recent = [t for t in _failed_logins[key] if now - t < _LOGIN_WINDOW_SECONDS]
    _failed_logins[key] = recent
    return recent


def _login_retry_after(key: str) -> Optional[int]:
    """Seconds the caller must wait, or None when they may attempt a sign-in."""
    now = time.monotonic()
    recent = _prune(key, now)
    if len(recent) < _MAX_FAILED_LOGINS:
        return None
    unlock_at = recent[-1] + _LOGIN_LOCKOUT_SECONDS
    remaining = int(unlock_at - now)
    return remaining if remaining > 0 else None


def _record_failed_login(key: str) -> None:
    now = time.monotonic()
    _prune(key, now)
    _failed_logins[key].append(now)


def _clear_failed_logins(key: str) -> None:
    _failed_logins.pop(key, None)


class RegisterUserSchema(BaseModel):
    """
    Public self-registration payload.

    Deliberately has NO `role` field. Accepting a caller-supplied role here allowed
    anyone to self-register as an administrator. Roles are assigned server-side only:
    self-registration always yields the standard user role, and elevation happens via
    the admin-only ``POST /api/v1/users`` endpoint or ``scripts/create_user.py``.

    ``extra="forbid"`` makes an attempt to smuggle a role an explicit 422 rather than
    a silently ignored field.
    """

    model_config = ConfigDict(extra="forbid")

    email: str
    username: str
    password: str

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str) -> str:
        """
        Basic RFC-pragmatic email check.

        Implemented with a regex rather than pydantic's ``EmailStr`` so the app keeps
        working without the optional ``email-validator`` dependency. Previously this
        field accepted any string at all.
        """
        v = (v or "").strip()
        if not _EMAIL_RE.match(v):
            raise ValueError("A valid email address is required.")
        return v

    @field_validator("username")
    @classmethod
    def _validate_username(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Username is required.")
        return v


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
    admin_user: User = Depends(require_admin),
):
    """
    Provision a new standard user account. **Administrator only.**

    This endpoint used to be public. Combined with vendor endpoints that returned
    decrypted bank details to any authenticated user, that gave anyone on the internet
    a three-request path to AMIPI's entire vendor bank book: register, log in, read
    /vendors. Since every operator account is created by an administrator anyway,
    self-service registration has no legitimate use here and is now closed.

    Use this endpoint or ``POST /api/v1/users`` (which can also assign the admin role)
    to create accounts. The very first administrator is created out-of-band with
    ``scripts/create_user.py``.
    """
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
        # Role is server-assigned. Self-registration NEVER grants elevated privileges.
        role=UserRole.USER,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    db.add(
        AuditLog(
            user_id=admin_user.id,
            action="USER_REGISTERED_BY_ADMIN",
            entity_type="user",
            entity_id=user.username,
            details={
                "created_by_admin": admin_user.username,
                "created_username": user.username,
                "created_email": user.email,
                "role": user.role.value,
            },
        )
    )

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
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_async_db),
):
    """Authenticate credentials and return JWT Bearer token."""
    # Find user by username or email
    username_input = form_data.username.strip()

    # Throttle credential guessing. There was previously no limit at all, so an
    # attacker could try passwords indefinitely at full speed.
    throttle_key = f"{_client_ip(request)}|{username_input.lower()}"
    retry_after = _login_retry_after(throttle_key)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Too many failed sign-in attempts. Try again in "
                f"{retry_after} second(s)."
            ),
            headers={"Retry-After": str(retry_after)},
        )

    res = await db.execute(
        select(User).where(
            (User.username == username_input) | (User.email == username_input.lower())
        )
    )
    user = res.scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.password_hash):
        _record_failed_login(throttle_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user account.")

    _clear_failed_logins(throttle_key)
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
