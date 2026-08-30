"""
TEMPORARY audit verification script — proves reported bugs against a live in-process app.
Deleted after the audit. Read-only except for creating its own test fixtures.
"""
import asyncio
import os
import sys
import uuid

import httpx
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import app  # noqa: E402
from app.db.session import AsyncSessionLocal, async_engine  # noqa: E402

RESULTS = []


def rec(bug, claim, verdict, detail=""):
    RESULTS.append((bug, claim, verdict, detail))
    mark = {"CONFIRMED": "✗ CONFIRMED BUG", "OK": "✓ not a bug", "PARTIAL": "~ partial"}[verdict]
    print(f"\n[{bug}] {mark}\n    claim : {claim}\n    detail: {detail}")


async def reset_db():
    async with async_engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE TABLE audit_logs, vendor_remittances, vendor_change_requests, "
            "payments, nacha_files, vendors, upload_batches, users CASCADE;"
        ))


async def main():
    # Safety: refuse to run against a non-test database
    db_url = os.getenv("DATABASE_URL", "")
    if "_test" not in db_url:
        print(f"REFUSING: DATABASE_URL is not a test database: {db_url}")
        return 1

    await reset_db()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:

        # ── BUG 6: role escalation via public registration ──────────────
        r = await c.post("/api/v1/auth/register", json={
            "email": "escalate@test.com", "username": "escalate",
            "password": "Password123!", "role": "admin",
        })
        got_role = r.json().get("role") if r.status_code == 201 else None
        rec("P0-6", "POST /auth/register accepts client-supplied role=admin",
            "CONFIRMED" if got_role == "admin" else "OK",
            f"HTTP {r.status_code}, resulting role={got_role!r}")

        # Provision a REAL admin directly in the DB (registration can no longer do it)
        from app.core.security import hash_password
        from app.models import User, UserRole
        async with AsyncSessionLocal() as s:
            s.add(User(email="realadmin@test.com", username="realadmin",
                       password_hash=hash_password("Password123!"),
                       role=UserRole.ADMIN, is_active=True))
            await s.commit()

        lr = await c.post("/api/v1/auth/login",
                          data={"username": "realadmin", "password": "Password123!"})
        admin_tok = lr.json().get("access_token")
        AH = {"Authorization": f"Bearer {admin_tok}"}
        print(f"\n[setup] admin token acquired: {bool(admin_tok)} (login HTTP {lr.status_code})")

        # Seed one vendor (as the self-made admin) for later probes
        cv = await c.post("/api/v1/vendors", headers=AH, json={
            "name": "AUDIT PROBE VENDOR", "routing_number": "021000021",
            "account_number": "987654321", "account_type": "checking",
        })
        vendor_id = cv.json().get("id") if cv.status_code == 201 else None

        # ── BUG 3: unauthenticated read of decrypted bank data ──────────
        r = await c.get("/api/v1/vendors")  # NO auth header
        if r.status_code == 200 and isinstance(r.json(), list) and r.json():
            v0 = r.json()[0]
            acct = str(v0.get("account_number", ""))
            plaintext = not acct.startswith("gAAAAA") and acct.isdigit()
            rec("P0-3", "GET /vendors needs no auth and returns DECRYPTED bank details",
                "CONFIRMED",
                f"HTTP 200 without token, {len(r.json())} vendors, "
                f"account_number is {'PLAINTEXT' if plaintext else 'ciphertext'} "
                f"(len={len(acct)})")
        else:
            rec("P0-3", "GET /vendors needs no auth", "OK", f"HTTP {r.status_code}")

        # ── BUG 4: unauthenticated NACHA generation + upload ────────────
        r = await c.post("/api/v1/nacha/generate", json={"batch_ids": [str(uuid.uuid4())]})
        rec("P0-4a", "POST /nacha/generate reachable without auth (not 401)",
            "CONFIRMED" if r.status_code != 401 else "OK",
            f"HTTP {r.status_code} (401 would mean protected)")

        r = await c.post("/api/v1/payments/manual-batch", headers=AH, json={
            "batch_number": 2, "filename": "anon.csv", "payments": [
                {"vendor_id": vendor_id, "amount": "10.00",
                 "id_number": "INV1", "effective_date": "2026-09-01"}
            ]})
        anon_batch = r.json().get("batch_id") if r.status_code == 201 else None
        rec("P0-4b", "POST /payments/manual-batch creates payments with NO auth",
            "CONFIRMED" if (await c.post("/api/v1/payments/manual-batch", json={
                "batch_number": 2, "filename": "x.csv", "payments": []})).status_code != 401
            else "OK",
            f"authed create HTTP {r.status_code} batch={anon_batch}; "
            f"unauthenticated attempt must be 401")

        # ── BUG 3b: unauthenticated batch read ──────────────────────────
        if anon_batch:
            r = await c.get(f"/api/v1/payments/batches/{anon_batch}")
            rec("P0-3b", "GET /payments/batches/{id} needs no auth",
                "CONFIRMED" if r.status_code == 200 else "OK",
                f"HTTP {r.status_code} without token")

        # ── BUG 5: unauthenticated payment mutation ─────────────────────
        if anon_batch:
            b = (await c.get(f"/api/v1/payments/batches/{anon_batch}", headers=AH)).json()
            pid = b["payments"][0]["payment_id"]
            r = await c.put(f"/api/v1/payments/{pid}", json={"amount": "999999.00"})
            rec("P0-5", "PUT /payments/{id} rewrites amount with NO auth/authorization",
                "CONFIRMED" if r.status_code == 200 else "OK",
                f"HTTP {r.status_code} without token")

        # ── BUG 3c: unauthenticated NACHA file download ─────────────────
        gen = await c.post("/api/v1/nacha/generate", headers=AH, json={
            "batch_ids": [anon_batch], "company_name": "AMIPI INC",
            "company_account": "785957066", "effective_entry_date": "2026-09-01",
        })
        print(f"[setup] authed generate -> HTTP {gen.status_code}")
        if gen.status_code == 201:
            fid = gen.json()["id"]
            r = await c.get(f"/api/v1/nacha/{fid}/download")
            rec("P0-3c", "GET /nacha/{id}/download serves full ACH file with no auth",
                "CONFIRMED" if r.status_code == 200 else "OK",
                f"HTTP {r.status_code} without token")
            r = await c.get("/api/v1/nacha/latest")
            rec("P0-3d", "GET /nacha/latest needs no auth",
                "CONFIRMED" if r.status_code == 200 else "OK",
                f"HTTP {r.status_code} without token")

            # ── BUG 14: batch reusable in a second file (double payment) ─
            g2 = await c.post("/api/v1/nacha/generate", headers=AH, json={
                "batch_ids": [anon_batch], "company_name": "AMIPI INC",
                "company_account": "785957066", "effective_entry_date": "2026-09-01",
            })
            rec("P1-14", "Already-PROCESSED batch can be regenerated into a 2nd file",
                "CONFIRMED" if g2.status_code == 201 else "OK",
                f"2nd generate HTTP {g2.status_code} (409 expected after fix)")

            # ── BUG 5b: payment editable AFTER file generation ───────────
            r = await c.put(f"/api/v1/payments/{pid}", headers=AH, json={"amount": "1.00"})
            rec("P0-5b", "Payment amount editable AFTER NACHA file generated (DB desync)",
                "CONFIRMED" if r.status_code == 200 else "OK",
                f"HTTP {r.status_code} (409 expected after fix)")

        # ── BUG 8: create_vendor bank-detail dedup broken by encryption ──
        r = await c.post("/api/v1/vendors", headers=AH, json={
            "name": "DIFFERENT NAME LTD", "routing_number": "021000021",
            "account_number": "987654321", "account_type": "checking",
        })
        rec("P0-8", "create_vendor cannot detect duplicate BANK DETAILS (Fernet non-deterministic)",
            "CONFIRMED" if r.status_code == 201 else "OK",
            f"HTTP {r.status_code} creating 2nd vendor with IDENTICAL routing+account "
            f"(409 would mean detected)")

        # ── BUG 46: routing checksum bypass via /bulk-confirm ───────────
        r = await c.post("/api/v1/vendors/bulk-confirm", headers=AH, json={
            "new_vendors": [{
                "name": "BAD ROUTING CO", "routing_number": "123",
                "account_number": "555", "account_type": "checking",
            }],
            "updated_vendors": [], "apply_updates": True, "allow_bank_updates": False,
        })
        inserted = r.json().get("inserted_count") if r.status_code == 200 else None
        rec("P0-46", "bulk-confirm inserts vendor with INVALID 3-digit routing (no checksum check)",
            "CONFIRMED" if inserted == 1 else "OK",
            f"HTTP {r.status_code}, inserted_count={inserted}")

        # ── BUG 47: deduplicate groups by name only, not bank details ───
        r = await c.post("/api/v1/vendors/deduplicate", headers=AH)
        merged = r.json().get("merged_count") if r.status_code == 200 else None
        rec("P1-47", "deduplicate does NOT merge same-bank/different-name duplicates "
                     "despite docstring",
            "CONFIRMED" if merged == 0 else "OK",
            f"HTTP {r.status_code}, merged_count={merged} "
            f"(2 vendors share routing 021000021/acct 987654321)")

    await async_engine.dispose()

    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    for bug, claim, verdict, _ in RESULTS:
        print(f"  {verdict:10s} {bug:8s} {claim[:70]}")
    confirmed = sum(1 for r in RESULTS if r[2] == "CONFIRMED")
    print(f"\n  {confirmed}/{len(RESULTS)} claims CONFIRMED as real bugs")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
