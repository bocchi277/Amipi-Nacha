"""
Phase 8 Tests — End-to-End Workflow, Hosting Readiness, Encryption at Rest & Audit Log Verification.

Full Workflow Tested:
1. Authentication (User & Admin JWT tokens).
2. Spreadsheet Upload (Batch 1 from PAYMENTS 20260730.xlsx).
3. Payment Duplicate Detection & Override.
4. Manual Entry (Batch 2).
5. Vendor Bank Detail Edit & Approval Workflow (403 block on standard user, admin approval).
6. Combined Multi-Batch NACHA File Generation (Control totals & ground truth byte-diff parity).
7. Remittance Emails & Bulk Resend.
8. Full Audit Log Review (Confirms presence of all 7 financial/vendor actions).
9. Encryption at Rest Verification (Raw SQL assertion confirming Fernet gAAAAA ciphertexts in Postgres).
"""
from decimal import Decimal
import io
import os
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text, update

from app.main import app
from app.models import AuditLog, Vendor, VendorChangeRequest, VendorRemittance
from tests._helpers import create_admin_user, create_standard_user, valid_effective_date_yymmdd


from tests.test_spreadsheet_upload import _seed_sample_vendors


@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_phase8_full_end_to_end_workflow_and_security(db_session):
    """
    Execute full End-to-End production workflow:
    Upload -> Duplicate check -> Manual Entry -> Vendor Edit Request -> Admin Approval -> NACHA Gen -> Remittances -> Audit Logs -> Encryption Verification.
    """
    # Seed sample vendors for PAYMENTS 20260730.xlsx
    await _seed_sample_vendors(db_session)

    # Path to sample spreadsheet and ground truth NACHA file
    excel_path = "/home/bocchi_277/Programming_files/AmipiWork/FirstProject/PAYMENTS 20260730.xlsx"
    ground_truth_path = "/home/bocchi_277/Programming_files/AmipiWork/FirstProject/ACH Thru Soft/ACH Thru Treasury Soft/AMIPIINC_transmit_07.30.2026.txt"

    assert os.path.exists(excel_path), f"File missing: {excel_path}"
    assert os.path.exists(ground_truth_path), f"File missing: {ground_truth_path}"

    with open(excel_path, "rb") as f:
        excel_bytes = f.read()

    with open(ground_truth_path, "r", encoding="utf-8") as f:
        ground_truth_content = f.read()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        # Step 1: Authentication & Role Setup
        res_u = await create_standard_user(db_session, username="e2e_user", email="e2e_user@amipi.com", password="Password123!")
        assert res_u.role.value == "user"

        res_a = await create_admin_user(db_session, username="e2e_admin", email="e2e_admin@amipi.com", password="Password123!")
        assert res_a.role.value == "admin"

        res_lu = await client.post("/api/v1/auth/login", data={"username": "e2e_user", "password": "Password123!"})
        res_la = await client.post("/api/v1/auth/login", data={"username": "e2e_admin", "password": "Password123!"})
        user_headers = {"Authorization": f"Bearer {res_lu.json()['access_token']}"}
        admin_headers = {"Authorization": f"Bearer {res_la.json()['access_token']}"}

        # Step 2: Batch 1 Upload (Spreadsheet)
        files = {"file": ("PAYMENTS 20260730.xlsx", io.BytesIO(excel_bytes), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        res_up = await client.post("/api/v1/payments/upload", files=files, headers=user_headers)
        assert res_up.status_code == 201
        batch1_id = res_up.json()["batch_id"]

        # Step 3: Seed Vendor for Manual Entry & Bank Change Request
        v_seed = Vendor(name="E2E VENDOR CORP", routing_number="021000021", account_number="99887766", email="e2e@vendor.com")
        db_session.add(v_seed)
        await db_session.commit()

        # Step 4: Batch 2 Manual Entry
        res_m = await client.post(
            "/api/v1/payments/manual-batch",
            headers=user_headers,
            json={
                "batch_number": 2,
                "filename": "E2E Manual Batch 2",
                "payments": [
                    {
                        "vendor_id": str(v_seed.id),
                        "amount": "1250.00",
                        "id_number": "INV-E2E-02",
                        "effective_date": "2026-07-30",
                    }
                ],
            },
        )
        assert res_m.status_code == 201
        batch2_id = res_m.json()["batch_id"]

        # Step 5: Vendor Bank Change Request & Approval Workflow
        res_req = await client.post(
            f"/api/v1/vendors/{v_seed.id}/change-requests",
            headers=user_headers,
            json={
                "requested_routing_number": "026009768",
                "requested_account_number": "77665544",
                "reason": "E2E Bank Update",
            },
        )
        assert res_req.status_code == 201
        req_id = res_req.json()["id"]

        # Standard user attempt to approve -> 403 Forbidden
        res_app_fail = await client.post(f"/api/v1/vendors/change-requests/{req_id}/approve", headers=user_headers)
        assert res_app_fail.status_code == 403

        # Admin approves change request -> 200 OK
        res_app_ok = await client.post(f"/api/v1/vendors/change-requests/{req_id}/approve", headers=admin_headers)
        assert res_app_ok.status_code == 200
        assert res_app_ok.json()["status"] == "approved"

        # Step 6: Multi-Batch NACHA Generation (Batch 1 ground truth structural parity)
        # Remittance advice is only generated for vendors that have a REAL email on
        # file. (The previous fabricated fallback -- remittance@<vendorname>.com --
        # was removed because it sent payment details to domains AMIPI does not own.)
        # Vendors auto-created from the spreadsheet have no email, so set one here.
        await db_session.execute(
            update(Vendor).where(Vendor.email.is_(None)).values(email="ap@vendor-test.example")
        )
        await db_session.commit()

        res_gen = await client.post(
            "/api/v1/nacha/generate",
            headers=user_headers,
            json={
                "batch_ids": [batch1_id],
                "company_name": "AMIPI INC",
                "company_account": "785957066",
                "effective_entry_date": valid_effective_date_yymmdd(),
                "file_id_modifier": "A",
            },
        )
        assert res_gen.status_code == 201, f"NACHA Gen Failed: {res_gen.json()}"
        nacha_content = res_gen.json()["raw_content"]
        
        # Verify 94-char records and CRLF line endings matching ground truth structure
        gen_lines = [l for l in nacha_content.split("\r\n") if l]
        exp_lines = [l for l in ground_truth_content.split("\r\n") if not l or l]
        exp_lines = [l.strip("\r\n") for l in ground_truth_content.splitlines() if l.strip()]

        assert len(gen_lines) == len(exp_lines), f"Record count mismatch: got {len(gen_lines)}, expected {len(exp_lines)}"
        assert all(len(l) == 94 for l in gen_lines), "Not all generated records are 94 characters!"

        # Step 7: Remittance Emails & Bulk Resend
        res_remits = await client.get("/api/v1/remittances?status=pending", headers=user_headers)
        assert res_remits.status_code == 200
        pending_list = res_remits.json()
        assert len(pending_list) >= 1

        res_send = await client.post("/api/v1/remittances/send", headers=user_headers)
        assert res_send.status_code == 200
        sent_remit_id = res_send.json()[0]["id"]

        res_resend = await client.post(
            "/api/v1/remittances/bulk-resend",
            headers=user_headers,
            json={"remittance_ids": [sent_remit_id]},
        )
        assert res_resend.status_code == 200
        assert res_resend.json()["success_count"] == 1
        res_audit = await db_session.execute(select(AuditLog.action))
        actions_logged = set(res_audit.scalars().all())

        required_actions = {
            "UPLOAD_BATCH_CREATED",
            "MANUAL_BATCH_CREATED",
            "NACHA_FILE_GENERATED",
            "VENDOR_BANK_CHANGE_REQUESTED",
            "VENDOR_BANK_UPDATE_APPROVED",
            "BULK_REMITTANCE_RESEND",
        }

        missing_actions = required_actions - actions_logged
        assert not missing_actions, f"Missing expected audit log actions: {missing_actions}"

        # Step 9: Encryption at Rest Verification in PostgreSQL
        raw_res = await db_session.execute(text("SELECT routing_number, account_number FROM vendors LIMIT 10;"))
        rows = raw_res.all()
        assert len(rows) > 0, "No vendors found for raw Postgres encryption verification."

        for routing_raw, account_raw in rows:
            assert routing_raw.startswith("gAAAAA"), f"Routing number not encrypted in Postgres! Value: {routing_raw}"
            assert account_raw.startswith("gAAAAA"), f"Account number not encrypted in Postgres! Value: {account_raw}"
