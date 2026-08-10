"""
Phase 4 Tests — Payment Duplicate Detection & Override Logic.

Verifies:
1. Deterministic SHA-256 fingerprint generation.
2. Known-duplicate detection blocking re-upload when allow_override=False.
3. Explicit override option (allow_override=True) committing duplicate with is_duplicate_override=True.
4. Intra-batch duplicate detection within the same spreadsheet.
"""
from datetime import date
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import AccountType, Payment, UploadBatch, Vendor
from app.services.duplicate_detector import compute_payment_fingerprint


@pytest.mark.asyncio
async def test_fingerprint_deterministic(db_session):
    """Verify SHA-256 fingerprint is deterministic and normalizes spacing/case."""
    vendor_id = "12345678-1234-5678-1234-567812345678"
    fp1 = compute_payment_fingerprint(vendor_id, Decimal("1500.00"), "inv-100", date(2026, 8, 10))
    fp2 = compute_payment_fingerprint(vendor_id, Decimal("1500.00"), " INV-100 ", date(2026, 8, 10))

    assert len(fp1) == 64
    assert fp1 == fp2  # Normalized case and spacing produce identical hash


@pytest.mark.asyncio
async def test_known_duplicate_detection_blocked(db_session):
    """
    Test uploading a known duplicate transaction (allow_override=False).
    - Batch 1 uploads payment P1.
    - Batch 2 uploads identical payment P1.
    - Batch 2 must detect P1 as a duplicate and flag a clear error.
    """
    v = Vendor(name="DUP TEST VENDOR", routing_number="021000021", account_number="998877")
    db_session.add(v)
    await db_session.commit()

    csv_content = "Vendor Name,Amount,Invoice Number,Date\nDUP TEST VENDOR,1500.00,INV-DUP-1,2026-08-10\n"

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        # Upload Batch 1
        res1 = await client.post(
            "/api/v1/payments/upload",
            files={"file": ("batch1.csv", csv_content.encode("utf-8"), "text/csv")},
            data={"batch_number": "1"},
        )
        assert res1.status_code == 201
        data1 = res1.json()
        assert data1["status"] == "parsed"
        assert data1["summary"]["valid_rows"] == 1
        assert data1["valid_payments"][0]["is_duplicate_override"] is False

        # Attempt to upload Batch 2 with exact same payment (allow_override=False default)
        res2 = await client.post(
            "/api/v1/payments/upload",
            files={"file": ("batch2_dup.csv", csv_content.encode("utf-8"), "text/csv")},
            data={"batch_number": "2"},
        )

    assert res2.status_code == 201
    data2 = res2.json()
    assert data2["status"] == "failed"
    assert data2["summary"]["valid_rows"] == 0
    assert data2["summary"]["error_rows"] == 1

    # Verify clear error message
    err_msg = data2["errors"][0]["errors"][0]
    assert "Duplicate payment detected" in err_msg
    assert "matches database" in err_msg
    assert "DUP TEST VENDOR" in err_msg


@pytest.mark.asyncio
async def test_known_duplicate_explicit_override(db_session):
    """
    Test uploading a known duplicate with explicit override (allow_override=True).
    - Batch 1 uploads payment P1.
    - Batch 2 uploads identical payment P1 with allow_override=True.
    - Batch 2 MUST commit P1 with is_duplicate_override=True.
    """
    v = Vendor(name="OVERRIDE VENDOR", routing_number="021000021", account_number="887766")
    db_session.add(v)
    await db_session.commit()

    csv_content = "Vendor Name,Amount,Invoice Number,Date\nOVERRIDE VENDOR,2750.00,INV-OVR-1,2026-08-10\n"

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        # Batch 1
        res1 = await client.post(
            "/api/v1/payments/upload",
            files={"file": ("batch1.csv", csv_content.encode("utf-8"), "text/csv")},
        )
        assert res1.status_code == 201

        # Batch 2 with allow_override=True
        res2 = await client.post(
            "/api/v1/payments/upload",
            files={"file": ("batch2_override.csv", csv_content.encode("utf-8"), "text/csv")},
            data={"allow_override": "true"},
        )

    assert res2.status_code == 201
    data2 = res2.json()
    assert data2["status"] == "parsed"
    assert data2["summary"]["valid_rows"] == 1
    assert data2["summary"]["error_rows"] == 0

    # Verify is_duplicate_override is True
    override_payment = data2["valid_payments"][0]
    assert override_payment["is_duplicate_override"] is True

    # Verify DB state
    batch2_id = data2["batch_id"]
    res_pmt = await db_session.execute(select(Payment).where(Payment.batch_id == batch2_id))
    db_pmt = res_pmt.scalar_one()
    assert db_pmt.is_duplicate_override is True
    assert db_pmt.fingerprint is not None


@pytest.mark.asyncio
async def test_intra_batch_duplicate_detection(db_session):
    """
    Test uploading a single file containing intra-batch duplicate rows.
    Row 1: Accepted.
    Row 2: Flagged as intra-batch duplicate error.
    """
    v = Vendor(name="INTRA VENDOR", routing_number="021000021", account_number="554433")
    db_session.add(v)
    await db_session.commit()

    # Two identical rows in the same CSV file
    csv_content = (
        "Vendor Name,Amount,Invoice Number,Date\n"
        "INTRA VENDOR,450.00,INV-INTRA-1,2026-08-10\n"
        "INTRA VENDOR,450.00,INV-INTRA-1,2026-08-10\n"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        res = await client.post(
            "/api/v1/payments/upload",
            files={"file": ("intra_dup.csv", csv_content.encode("utf-8"), "text/csv")},
        )

    assert res.status_code == 201
    data = res.json()
    assert data["status"] == "partially_failed"
    assert data["summary"]["total_rows"] == 2
    assert data["summary"]["valid_rows"] == 1
    assert data["summary"]["error_rows"] == 1

    err_msg = data["errors"][0]["errors"][0]
    assert "Duplicate payment detected" in err_msg
    assert "matches current batch upload" in err_msg
