"""
Admin Account Provisioning Script.

Usage:
  python3 backend/scripts/promote_admin.py <username_or_email> [password]

Promotes an existing user to Admin (updating password if provided), or creates a new Admin user if not found.
"""
import sys
import os
import asyncio

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select, func
from app.db.session import AsyncSessionLocal
from app.models import User, UserRole
from app.core.security import hash_password


async def promote_or_create_admin(identifier: str, password: str = "AdminPass123!"):
    async with AsyncSessionLocal() as db:
        clean_ident = identifier.strip()
        clean_lower = clean_ident.lower()

        # Case-insensitive search by username or email
        res = await db.execute(
            select(User).where(
                (func.lower(User.username) == clean_lower) | (func.lower(User.email) == clean_lower)
            )
        )
        user = res.scalar_one_or_none()

        if user:
            user.role = UserRole.ADMIN
            if password:
                user.password_hash = hash_password(password)
            await db.commit()
            await db.refresh(user)
            print(f"SUCCESS: Existing user '{user.username}' (Email: {user.email}) has been PROMOTED to ADMIN.")
            if password:
                print(f"  Password updated for '{user.username}'.")
        else:
            username = clean_ident
            email = f"{clean_lower}@amipi.com" if "@" not in clean_ident else clean_ident.lower()

            # Secondary check for email collision
            res_e = await db.execute(select(User).where(func.lower(User.email) == email))
            user_e = res_e.scalar_one_or_none()
            if user_e:
                user_e.role = UserRole.ADMIN
                if password:
                    user_e.password_hash = hash_password(password)
                await db.commit()
                await db.refresh(user_e)
                print(f"SUCCESS: Found user '{user_e.username}' by email '{user_e.email}'. PROMOTED to ADMIN.")
                if password:
                    print(f"  Password updated for '{user_e.username}'.")
                return

            new_admin = User(
                email=email,
                username=username,
                password_hash=hash_password(password),
                role=UserRole.ADMIN,
            )
            db.add(new_admin)
            await db.commit()
            await db.refresh(new_admin)
            print(f"SUCCESS: Created NEW ADMIN account.")
            print(f"  Username: {new_admin.username}")
            print(f"  Email:    {new_admin.email}")
            print(f"  Password: {password}")
            print(f"  Role:     ADMIN")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 backend/scripts/promote_admin.py <username_or_email> [password]")
        sys.exit(1)

    ident = sys.argv[1]
    pwd = sys.argv[2] if len(sys.argv) > 2 else "AdminPass123!"
    asyncio.run(promote_or_create_admin(ident, pwd))
