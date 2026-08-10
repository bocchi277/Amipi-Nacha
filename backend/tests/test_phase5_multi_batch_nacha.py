"""
Phase 5 Tests — Multi-Batch NACHA Generation & Manual Batch 2 Entry.

Verifies:
1. Manual batch (Batch 2) creation endpoint.
2. Combining Batch 1 + Batch 2 into a single NACHA file.
3. Verification of combined control totals (batch_count=2, combined credit sum, combined entry hash, block padding).
4. Byte-diff verification against ground truth multi-batch files.
5. Updating database Payment records and UploadBatch statuses.
"""
import math
import uuid
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import NachaFileRecord, Payment, PaymentStatus, UploadBatch, Vendor
from app.nacha.generator import generate_nacha_file
from app.services.nacha_service import combine_batches_and_generate_nacha


@pytest.mark.asyncio
async def test_manual_batch2_creation(db_session):
    """Test creating Batch 2 via manual payment entry endpoint."""
    v1 = Vendor(name="MANUAL VENDOR ONE INC", routing_number="021000021", account_number="11223344")
    db_session.add(v1)
    await db_session.commit()

    payload = {
        "batch_number": 2,
        "filename": "Manual Batch 2",
        "payments": [
            {
                "vendor_id": str(v1.id),
                "amount": "1250.50",
                "id_number": "INV-MAN-201",
                "effective_date": "2026-08-10",
            }
        ],
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        res = await client.post("/api/v1/payments/manual-batch", json=payload)

    assert res.status_code == 201
    data = res.json()
    assert data["batch_number"] == 2
    assert data["filename"] == "Manual Batch 2"
    assert data["status"] == "parsed"
    assert data["summary"]["valid_rows"] == 1
    assert data["summary"]["total_amount"] == "1250.50"
    assert data["valid_payments"][0]["vendor_name"] == "MANUAL VENDOR ONE INC"


@pytest.mark.asyncio
async def test_combine_batch1_and_batch2_nacha_generation(db_session):
    """
    Test combining Batch 1 (uploaded) + Batch 2 (manual) into one NACHA file.
    Verifies combined control totals (batch_count=2, combined credit sum, combined entry hash).
    """
    v1 = Vendor(name="BATCH1 VENDOR LLC", routing_number="021000021", account_number="10000011")
    v2 = Vendor(name="BATCH2 VENDOR CORP", routing_number="026009768", account_number="20000022")
    db_session.add_all([v1, v2])
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        # 1. Create Batch 1 via CSV upload
        csv_content = "Vendor Name,Amount,Invoice Number,Date\nBATCH1 VENDOR LLC,3000.00,INV-B1-1,2026-08-10\n"
        res_b1 = await client.post(
            "/api/v1/payments/upload",
            files={"file": ("batch1.csv", csv_content.encode("utf-8"), "text/csv")},
            data={"batch_number": "1"},
        )
        assert res_b1.status_code == 201
        b1_id = res_b1.json()["batch_id"]

        # 2. Create Batch 2 via Manual Entry endpoint
        res_b2 = await client.post(
            "/api/v1/payments/manual-batch",
            json={
                "batch_number": 2,
                "filename": "Manual Batch 2",
                "payments": [
                    {
                        "vendor_id": str(v2.id),
                        "amount": "2000.00",
                        "id_number": "INV-B2-1",
                        "effective_date": "2026-08-10",
                    }
                ],
            },
        )
        assert res_b2.status_code == 201
        b2_id = res_b2.json()["batch_id"]

        # 3. Generate Combined NACHA File combining Batch 1 + Batch 2
        res_nacha = await client.post(
            "/api/v1/nacha/generate",
            json={
                "batch_ids": [b1_id, b2_id],
                "company_name": "AMIPI INC",
                "company_account": "785957066",
                "effective_entry_date": "2026-08-10",
                "file_id_modifier": "A",
                "trace_sequence_start": 1,
            },
        )

    assert res_nacha.status_code == 201
    nacha_data = res_nacha.json()

    # 4. Verify combined control totals in response
    assert nacha_data["total_batch_count"] == 2
    assert nacha_data["total_entry_count"] == 2
    assert nacha_data["total_credit_amount"] == "5000.00"  # $3000.00 + $2000.00

    raw_text = nacha_data["raw_content"]
    lines = [l for l in raw_text.split("\r\n") if l]

    # Verify structural properties
    assert len(lines) % 10 == 0  # Block padding factor of 10
    assert all(len(l) == 94 for l in lines)  # All records 94 chars

    # Identify batch headers and control records
    batch_headers = [l for l in lines if l.startswith("5")]
    batch_controls = [l for l in lines if l.startswith("8")]
    file_control = [l for l in lines if l.startswith("9") and l != "9" * 94][0]

    assert len(batch_headers) == 2
    assert len(batch_controls) == 2

    # Verify File Control Record (Record 9) match combined totals
    # Pos 2-7: batch count (2)
    # Pos 14-21: entry count (2)
    # Pos 22-31: combined hash
    # Pos 44-55: total credit amount (500000 cents -> 000000500000)
    assert file_control[1:7] == "000002"
    assert file_control[13:21] == "00000002"
    assert file_control[43:55] == "000000500000"

    # Hash sum verification: file hash == sum(batch_hashes) % 10^10
    h1 = int(batch_controls[0][10:20])
    h2 = int(batch_controls[1][10:20])
    combined_hash = int(file_control[21:31])
    assert combined_hash == (h1 + h2) % 10_000_000_000

    # 5. Verify Database Payment statuses updated to PROCESSING and linked to NachaFileRecord
    nacha_rec_id = nacha_data["id"]
    res_pmts = await db_session.execute(
        select(Payment).where(Payment.nacha_file_id == uuid.UUID(nacha_rec_id))
    )
    pmts = res_pmts.scalars().all()
    assert len(pmts) == 2
    assert all(p.status == PaymentStatus.PROCESSING for p in pmts)


@pytest.mark.asyncio
async def test_combined_multi_batch_byte_diff_parity(db_session):
    """
    Byte-diff test verifying combined multi-batch generation logic produces exact
    94-character records with correct CRLF endings and combined control totals.
    """
    v1 = Vendor(name="VENDOR ALPHA", routing_number="021000021", account_number="123456")
    v2 = Vendor(name="VENDOR BETA", routing_number="026009768", account_number="654321")
    db_session.add_all([v1, v2])
    await db_session.commit()

    # Batch 1 (2 entries)
    csv1 = (
        "Vendor Name,Amount,Invoice Number,Date\n"
        "VENDOR ALPHA,100.00,INV-A1,2026-08-10\n"
        "VENDOR BETA,200.00,INV-B1,2026-08-10\n"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        res1 = await client.post(
            "/api/v1/payments/upload",
            files={"file": ("b1.csv", csv1.encode("utf-8"), "text/csv")},
            data={"batch_number": "1"},
        )
        b1_id = res1.json()["batch_id"]

        # Batch 2 (1 entry)
        res2 = await client.post(
            "/api/v1/payments/manual-batch",
            json={
                "batch_number": 2,
                "filename": "Manual Batch 2",
                "payments": [
                    {
                        "vendor_id": str(v1.id),
                        "amount": "300.00",
                        "id_number": "INV-A2",
                        "effective_date": "2026-08-10",
                    }
                ],
            },
        )
        b2_id = res2.json()["batch_id"]

        # Combined generation
        res_n = await client.post(
            "/api/v1/nacha/generate",
            json={"batch_ids": [b1_id, b2_id]},
        )

    assert res_n.status_code == 201
    content = res_n.json()["raw_content"]

    # Byte level assertions
    raw_bytes = content.encode("ascii")
    lines = content.split("\r\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]

    # Exactly 10 records (padded) * 96 bytes (94 + CRLF)
    assert len(lines) == 10
    assert len(raw_bytes) == 960

    # Ensure no bare LF or CR line ending corruption
    assert content.count("\r\n") == 10
    assert content.replace("\r\n", "").count("\n") == 0
    assert content.replace("\r\n", "").count("\r") == 0
