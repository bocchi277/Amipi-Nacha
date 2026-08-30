"""TEMPORARY audit script #4 — verifies deduplicate merges bank-detail duplicates."""
import asyncio
import os
import sys

import httpx
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import app  # noqa: E402
from app.db.session import AsyncSessionLocal, async_engine  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models import AccountType, User, UserRole, Vendor  # noqa: E402


async def main():
    if "_test" not in os.getenv("DATABASE_URL", ""):
        print("REFUSING: not a test database")
        return 1

    async with async_engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE TABLE audit_logs, vendor_remittances, vendor_change_requests, "
            "payments, nacha_files, vendors, upload_batches, users CASCADE;"))

    # Seed: two vendors sharing bank details under DIFFERENT names (inserted directly,
    # simulating rows that predate the create_vendor duplicate check), plus a
    # same-name pair, plus an unrelated vendor that must be left alone.
    async with AsyncSessionLocal() as s:
        s.add(User(email="a@a.com", username="admin1",
                   password_hash=hash_password("Password123!"),
                   role=UserRole.ADMIN, is_active=True))
        for name, rt, acc in [
            ("ACME SUPPLIES INC", "021000021", "111111111"),   # bank-dup A
            ("ACME SUPPLIES LLC", "021000021", "111111111"),   # bank-dup A (diff name)
            ("BETA TRADING",      "021000021", "222222222"),   # name-dup B
            ("BETA TRADING",      "026009768", "333333333"),   # name-dup B (diff bank)
            ("GAMMA UNIQUE CO",   "026013356", "444444444"),   # unrelated
        ]:
            s.add(Vendor(name=name, routing_number=rt, account_number=acc,
                         account_type=AccountType.CHECKING, is_active=True))
        await s.commit()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as c:
        lr = await c.post("/api/v1/auth/login",
                          data={"username": "admin1", "password": "Password123!"})
        AH = {"Authorization": f"Bearer {lr.json()['access_token']}"}

        before = (await c.get("/api/v1/vendors", headers=AH)).json()
        print(f"before: {len(before)} vendors")
        for v in sorted(before, key=lambda x: x["name"]):
            print(f"   {v['name']:<22} {v['routing_number']}/{v['account_number']}")

        r = await c.post("/api/v1/vendors/deduplicate", headers=AH)
        body = r.json()
        print(f"\ndeduplicate -> HTTP {r.status_code}, merged={body.get('merged_count')}, "
              f"primaries={body.get('primary_vendors_count')}")

        after = (await c.get("/api/v1/vendors", headers=AH)).json()
        print(f"\nafter: {len(after)} vendors")
        for v in sorted(after, key=lambda x: x["name"]):
            print(f"   {v['name']:<22} {v['routing_number']}/{v['account_number']}")

        names_after = {v["name"] for v in after}
        checks = [
            ("bank-detail duplicate merged (ACME pair -> 1)",
             len([v for v in after if v["name"].startswith("ACME")]) == 1),
            ("same-name duplicate merged (BETA pair -> 1)",
             len([v for v in after if v["name"] == "BETA TRADING"]) == 1),
            ("unrelated vendor preserved",
             "GAMMA UNIQUE CO" in names_after),
            ("total reduced 5 -> 3", len(after) == 3),
        ]
        print()
        allok = True
        for label, ok in checks:
            print(f"  {'✓' if ok else '✗'} {label}")
            allok &= ok
        print(f"\n{'ALL CHECKS PASS' if allok else 'FAILURES PRESENT'}")

    await async_engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
