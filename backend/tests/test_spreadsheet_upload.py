"""
Tests for Phase 3 — Spreadsheet Upload & Parsing Endpoint.

Verifies:
1. Parsing real production spreadsheet 'PAYMENTS 20260730.xlsx' (19 vendors).
2. Malformed row detection & explicit per-row error reporting (negative amounts, missing vendor, bad routing).
3. Persistence of valid payment transactions tied to new UploadBatch in PostgreSQL.
4. CSV spreadsheet upload.
"""
import io
from datetime import date
from decimal import Decimal

import openpyxl
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import AccountType, BatchStatus, Payment, UploadBatch, Vendor


# List of vendors from PAYMENTS 20260730.xlsx for database seeding
SAMPLE_VENDORS = [
    ("ARTN DESIGN INC", "021000021", "1110001"),
    ("B. H. C. DIAMONDS ( U.S.A. ) INC.", "026013356", "1110002"),
    ("BRINKS GLOBLE SERVICES USA INC", "011900254", "1110003"),
    ("DHARM INTERNATIONAL LLC", "021000322", "1110004"),
    ("DIAMEX INC", "021202337", "1110005"),
    ("DIAMOND DAYS PROMOTION INC", "121042882", "1110006"),
    ("DISONS GEMS INC", "021000089", "1110007"),
    ("FENIX DIAMONDS LLC", "021000089", "1110008"),
    ("FOREVER GROWN DIAMONDS", "021000322", "1110009"),
    ("KGK DIAMONDS USA", "026013576", "1110010"),
    ("KIRA JEWELS INC", "231372691", "1110011"),
    ("KIRAN GEMS USA INC", "026013356", "1110012"),
    ("MC PRODUCTION US LLC", "021202337", "1110013"),
    ("MR. F JEWELRY INC.", "021001486", "1110014"),
    ("SHIVAM JEWELS INC", "091310592", "1110015"),
    ("SIGNOVA INC", "072000805", "1110016"),
    ("SUNSHINE DIAMOND CUTTER INC", "021000322", "1110017"),
    ("TWINKLEDIAM INC.", "111906161", "1110018"),
    ("UNITED COLOR GEMS INC. DBA UCG", "021202337", "1110019"),
]


async def _seed_sample_vendors(db_session):
    """Seed the test database with the vendors from the sample spreadsheet."""
    for name, routing, acct in SAMPLE_VENDORS:
        v = Vendor(
            name=name[:22],
            routing_number=routing,
            account_number=acct,
            account_type=AccountType.CHECKING,
            is_active=True,
        )
        db_session.add(v)
    await db_session.commit()


@pytest.mark.asyncio
async def test_upload_sample_excel_payments(db_session):
    """
    Test uploading the real sample payments spreadsheet 'PAYMENTS 20260730.xlsx'.
    Should parse all 19 vendor entries cleanly and persist 19 Payment records in PostgreSQL.
    """
    await _seed_sample_vendors(db_session)

    # Read sample excel file
    file_path = "/home/bocchi_277/Programming_files/AmipiWork/FirstProject/PAYMENTS 20260730.xlsx"
    with open(file_path, "rb") as f:
        file_bytes = f.read()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/v1/payments/upload",
            files={"file": ("PAYMENTS 20260730.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"batch_number": "1", "effective_date": "2026-07-30"},
        )

    assert response.status_code == 201, f"Response: {response.text}"
    data = response.json()

    assert data["filename"] == "PAYMENTS 20260730.xlsx"
    assert data["batch_number"] == 1
    assert data["status"] == "parsed"
    assert data["summary"]["valid_rows"] == 19
    assert data["summary"]["error_rows"] == 0
    assert len(data["valid_payments"]) == 19
    assert len(data["errors"]) == 0

    # Total amount check ($154,006.57)
    total_parsed = sum(Decimal(p["amount"]) for p in data["valid_payments"])
    assert total_parsed == Decimal("154006.57")

    # Verify DB persistence
    batch_id = data["batch_id"]
    res_batch = await db_session.execute(select(UploadBatch).where(UploadBatch.id == batch_id))
    batch_in_db = res_batch.scalar_one_or_none()
    assert batch_in_db is not None
    assert batch_in_db.valid_rows_count == 19
    assert batch_in_db.total_amount == Decimal("154006.57")

    # Verify 19 Payment rows tied to batch_id
    res_pmts = await db_session.execute(select(Payment).where(Payment.batch_id == batch_id))
    db_pmts = res_pmts.scalars().all()
    assert len(db_pmts) == 19
    assert all(p.batch_id == batch_in_db.id for p in db_pmts)


@pytest.mark.asyncio
async def test_upload_malformed_spreadsheet_per_row_errors(db_session):
    """
    Test uploading a CSV with malformed rows (negative amount, missing vendor, unknown vendor).
    Must produce explicit per-row errors instead of silent skipping.
    Valid rows must still be saved.
    """
    # Seed 1 valid vendor
    v = Vendor(name="VALID VENDOR CORP", routing_number="021000021", account_number="999888")
    db_session.add(v)
    await db_session.commit()

    # Create CSV content with intentional errors:
    # Row 2 (data row 1): Valid payment
    # Row 3 (data row 2): Missing vendor name
    # Row 4 (data row 3): Negative amount
    # Row 5 (data row 4): Unknown vendor not in DB with no routing/account
    # Row 6 (data row 5): Invalid routing number
    csv_content = (
        "Vendor Name,Amount,Invoice Number,Routing Number,Account Number\n"
        "VALID VENDOR CORP,500.00,INV-101,,\n"
        ",250.00,INV-102,,\n"
        "VALID VENDOR CORP,-150.00,INV-103,,\n"
        "UNKNOWN VENDOR INC,300.00,INV-104,,\n"
        "UNKNOWN VENDOR INC,400.00,INV-105,12345,9999\n"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/v1/payments/upload",
            files={"file": ("malformed_payments.csv", csv_content.encode("utf-8"), "text/csv")},
            data={"batch_number": "2", "effective_date": "2026-08-01"},
        )

    assert response.status_code == 201
    data = response.json()

    assert data["status"] == "partially_failed"
    assert data["summary"]["total_rows"] == 5
    assert data["summary"]["valid_rows"] == 1
    assert data["summary"]["error_rows"] == 4

    # Verify per-row errors
    errors = data["errors"]
    assert len(errors) == 4

    # Check row error details
    row_nums = [e["row_number"] for e in errors]
    assert 3 in row_nums  # Row 3: Missing vendor
    assert 4 in row_nums  # Row 4: Negative amount
    assert 5 in row_nums  # Row 5: Unknown vendor
    assert 6 in row_nums  # Row 6: Invalid routing

    # Verify valid row 1 IS saved to DB
    batch_id = data["batch_id"]
    res_pmts = await db_session.execute(select(Payment).where(Payment.batch_id == batch_id))
    saved_pmts = res_pmts.scalars().all()
    assert len(saved_pmts) == 1
    assert saved_pmts[0].amount == Decimal("500.00")
    assert saved_pmts[0].id_number == "INV-101"


@pytest.mark.asyncio
async def test_upload_valid_csv_spreadsheet(db_session):
    """Test uploading a valid flat CSV payment spreadsheet."""
    v1 = Vendor(name="ALPHA JEWELS LLC", routing_number="021000021", account_number="123456")
    v2 = Vendor(name="BETA GEMS CORP", routing_number="026013356", account_number="654321")
    db_session.add_all([v1, v2])
    await db_session.commit()

    csv_content = (
        "Vendor Name,Amount,Invoice Number,Date\n"
        "ALPHA JEWELS LLC,1250.50,INV-2026-01,2026-08-05\n"
        "BETA GEMS CORP,3400.00,INV-2026-02,2026-08-05\n"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/v1/payments/upload",
            files={"file": ("batch_csv.csv", csv_content.encode("utf-8"), "text/csv")},
            data={"batch_number": "1"},
        )

    assert response.status_code == 201
    data = response.json()

    assert data["status"] == "parsed"
    assert data["summary"]["valid_rows"] == 2
    assert data["summary"]["error_rows"] == 0
    assert data["summary"]["total_amount"] == "4650.50"


@pytest.mark.asyncio
async def test_get_upload_batch_by_id(db_session):
    """Test retrieving an uploaded batch by ID via GET /api/v1/payments/batches/{batch_id}."""
    v = Vendor(name="GAMMA INC", routing_number="021000021", account_number="111222")
    db_session.add(v)
    await db_session.commit()

    csv_content = "Vendor Name,Amount,Invoice Number\nGAMMA INC,800.00,INV-888\n"

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        res_upload = await client.post(
            "/api/v1/payments/upload",
            files={"file": ("batch_get.csv", csv_content.encode("utf-8"), "text/csv")},
        )
        batch_id = res_upload.json()["batch_id"]

        # Fetch batch by ID
        res_get = await client.get(f"/api/v1/payments/batches/{batch_id}")

    assert res_get.status_code == 200
    bdata = res_get.json()
    assert bdata["batch_id"] == batch_id
    assert bdata["summary"]["total_amount"] == "800.00"
    assert len(bdata["payments"]) == 1
    assert bdata["payments"][0]["amount"] == "800.00"
    assert bdata["payments"][0]["id_number"] == "INV-888"
