"""
User Provisioning CLI Script.

Usage:
  python3 backend/scripts/create_user.py <username> <email> <password> [role]

Arguments:
  username : Unique username
  email    : Valid email address
  password : Password (min 8 characters)
  role     : 'user' (default) or 'admin'

Examples:
  python3 backend/scripts/create_user.py alice alice@amipi.com "AlicePass123!" user
  python3 backend/scripts/create_user.py superadmin admin@amipi.com "AdminSecurePass123!" admin
"""
import sys
import os
import asyncio

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select, func
from app.db.session import AsyncSessionLocal
from app.models import User, UserRole, AuditLog
from app.core.security import hash_password


async def create_user_cli(username: str, email: str, password: str, role_str: str = "user"):
    username = username.strip()
    email = email.strip().lower()
    role_str = role_str.strip().lower()

    if not username:
        print("ERROR: Username cannot be empty.")
        sys.exit(1)
    if not email or "@" not in email:
        print("ERROR: Invalid email address.")
        sys.exit(1)
    if len(password) < 8:
        print("ERROR: Password must be at least 8 characters long.")
        sys.exit(1)

    role = UserRole.ADMIN if role_str == "admin" else UserRole.USER

    async with AsyncSessionLocal() as db:
        # Check duplicate username
        res_u = await db.execute(select(User).where(func.lower(User.username) == username.lower()))
        if res_u.scalar_one_or_none():
            print(f"ERROR: Username '{username}' already exists.")
            sys.exit(1)

        # Check duplicate email
        res_e = await db.execute(select(User).where(func.lower(User.email) == email))
        if res_e.scalar_one_or_none():
            print(f"ERROR: Email '{email}' is already registered.")
            sys.exit(1)

        new_user = User(
            username=username,
            email=email,
            password_hash=hash_password(password),
            role=role,
            is_active=True,
        )
        db.add(new_user)

        audit_entry = AuditLog(
            action="USER_CREATED_CLI",
            entity_type="user",
            entity_id=username,
            details={"username": username, "email": email, "role": role.value},
        )
        db.add(audit_entry)

        await db.commit()
        await db.refresh(new_user)

        print("\n=======================================================")
        print("🎉 USER ACCOUNT PROVISIONED SUCCESSFULLY")
        print("=======================================================")
        print(f"  ID        : {new_user.id}")
        print(f"  Username  : {new_user.username}")
        print(f"  Email     : {new_user.email}")
        print(f"  Role      : {new_user.role.value.upper()}")
        print(f"  Status    : {'ACTIVE' if new_user.is_active else 'INACTIVE'}")
        print("=======================================================\n")


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)

    username = sys.argv[1]
    email = sys.argv[2]
    password = sys.argv[3]
    role = sys.argv[4] if len(sys.argv) > 4 else "user"

    asyncio.run(create_user_cli(username, email, password, role))


if __name__ == "__main__":
    main()
