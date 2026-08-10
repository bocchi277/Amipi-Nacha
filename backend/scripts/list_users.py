"""
Utility CLI Script: List All Registered System Accounts.

Usage:
  python3 backend/scripts/list_users.py
"""
import asyncio
import sys
from pathlib import Path

# Ensure app package is in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models import User


async def list_all_users():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).order_by(User.created_at.desc()))
        users = result.scalars().all()

        print("\n==========================================================================================")
        print("                           AMIPI ACH SYSTEM — REGISTERED ACCOUNTS                          ")
        print("==========================================================================================")
        print(f"Total Registered Users: {len(users)}\n")

        if not users:
            print("No registered accounts found in database.")
            print("To register an account, use the frontend UI or promote_admin.py script.\n")
            return

        header = f"{'USERNAME':<20} | {'EMAIL':<30} | {'ROLE':<8} | {'ACTIVE':<6} | {'CREATED AT'}"
        print(header)
        print("-" * len(header))

        for u in users:
            role_str = u.role.value if hasattr(u.role, "value") else str(u.role)
            created_str = u.created_at.strftime("%Y-%m-%d %H:%M:%S") if u.created_at else "N/A"
            print(f"{u.username:<20} | {u.email:<30} | {role_str.upper():<8} | {str(u.is_active):<6} | {created_str}")

        print("==========================================================================================\n")


if __name__ == "__main__":
    asyncio.run(list_all_users())
