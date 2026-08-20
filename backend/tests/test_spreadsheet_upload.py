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

    # Total amount check ($153,719.07 true banking paid sum)
    total_parsed = sum(Decimal(p["amount"]) for p in data["valid_payments"])
    assert total_parsed == Decimal("153719.07")

    # Check that Diamond Days Promotion Inc (partial payment) parsed paid amount $50.00 not original $337.50
    ddp_payment = next(p for p in data["valid_payments"] if "DIAMOND DAYS" in p["vendor_name"].upper())
    assert Decimal(ddp_payment["amount"]) == Decimal("50.00")
    assert ddp_payment["invoice_breakdown"] is not None
    assert len(ddp_payment["invoice_breakdown"]) == 1
    assert ddp_payment["invoice_breakdown"][0]["invoice_number"] == "25789"
    assert Decimal(str(ddp_payment["invoice_breakdown"][0]["amount"])) == Decimal("50.00")

    # Verify DB persistence
    batch_id = data["batch_id"]
    res_batch = await db_session.execute(select(UploadBatch).where(UploadBatch.id == batch_id))
    batch_in_db = res_batch.scalar_one_or_none()
    assert batch_in_db is not None
    assert batch_in_db.valid_rows_count == 19
    assert batch_in_db.total_amount == Decimal("153719.07")

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


@pytest.mark.asyncio
async def test_upload_partial_payment_qb_excel(db_session):
    """
    Test uploading a QuickBooks Excel format with partial payments where:
    - Paid Amount differs from Original Amount
    - Multiple sub-invoices exist
    - TOTAL row has a different Original Amount
    Asserts that:
    1. Transaction total strictly equals the sum of Paid Amounts.
    2. Sub-invoice breakdown amounts match the individual Paid Amounts.
    3. Original Amount never overrides the actual cash payment.
    """
    v = Vendor(
        name="ARTN DESIGN INC",
        routing_number="021000021",
        account_number="12345678",
        account_type=AccountType.CHECKING,
        is_active=True,
    )
    db_session.add(v)
    await db_session.commit()

    # Build mock QuickBooks workbook in-memory
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    # Row 1: Header
    ws.append([None, "Type", None, "Num", None, "Date", None, "Name", None, "Item", None, "Account", None, "Paid Amount", None, "Original Amount"])
    # Row 2: Empty
    ws.append([" "])
    # Row 3: Bill Pmt -Check header
    ws.append([None, "Bill Pmt -Check", None, "ACH", None, "2026-07-30", None, "ARTN DESIGN INC", None, None, None, "1002 · JPMC", None, None, None, -5000.00])
    # Row 4: Empty
    ws.append([" "])
    # Row 5: Bill 1 (Original $10,000, Paid $3,000)
    ws.append([None, "Bill", None, "INV-1001", None, "2026-05-01", None, None, None, None, None, "5012 · Diamonds", None, -3000.00, None, 10000.00])
    # Row 6: Bill 2 (Original $6,231.11, Paid $2,000)
    ws.append([None, "Bill", None, "INV-1002", None, "2026-05-02", None, None, None, None, None, "5012 · Diamonds", None, -2000.00, None, 6231.11])
    # Row 7: TOTAL row (Paid Amount = -5000, Original Amount = 16231.11)
    ws.append(["TOTAL", None, None, None, None, None, None, None, None, None, None, None, None, -5000.00, None, 16231.11])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    file_bytes = buf.getvalue()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/v1/payments/upload",
            files={"file": ("partial_pmt.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"batch_number": "1", "effective_date": "2026-07-30"},
        )

    assert response.status_code == 201, f"Response: {response.text}"
    data = response.json()

    assert data["summary"]["valid_rows"] == 1
    assert data["summary"]["error_rows"] == 0
    assert len(data["valid_payments"]) == 1

    pmt = data["valid_payments"][0]
    # Total MUST be $5000.00 (the paid sum), NOT $16,231.11 (the original amount)!
    assert pmt["amount"] == "5000.00"
    assert pmt["invoice_breakdown"] is not None
    assert len(pmt["invoice_breakdown"]) == 2

    # Check breakdown matches individual paid amounts
    inv1 = next(i for i in pmt["invoice_breakdown"] if i["invoice_number"] == "INV-1001")
    assert Decimal(str(inv1["amount"])) == Decimal("3000.00")

    inv2 = next(i for i in pmt["invoice_breakdown"] if i["invoice_number"] == "INV-1002")
    assert Decimal(str(inv2["amount"])) == Decimal("2000.00")

    # Sum of sub-invoices must equal total payment
    sub_sum = sum(Decimal(str(i["amount"])) for i in pmt["invoice_breakdown"])
    assert sub_sum == Decimal(pmt["amount"]) == Decimal("5000.00")


@pytest.mark.asyncio
async def test_upload_qb_multisplit_yellow_line_invoice(db_session):
    """
    Test uploading QuickBooks export with multi-split bill lines (yellow line scenario).
    Row 1: Bill Pmt -Check ($6,542.30)
    Row 2: Bill #129147 ($6,150.30 - Metal)
    Row 3: [Blank Type/Num] ($392.00 - Labor Setting) -> MUST BE ACCUMULATED
    Row 4: TOTAL ($6,542.30)
    """
    # Seed Sunrise vendor
    vendor = Vendor(
        name="SUNRISE JEWELRY MFG. CORP"[:22],
        routing_number="021000322",
        account_number="483028574148",
        account_type=AccountType.CHECKING,
        is_active=True,
    )
    db_session.add(vendor)
    await db_session.commit()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    # Row 1: Header
    ws.append([None, "Type", None, "Num", None, "Date", None, "Name", None, "Account", None, None, None, "Paid Amount", None, "Original Amount"])
    # Row 2: Empty
    ws.append([" "])
    # Row 3: Bill Pmt -Check header
    ws.append([None, "Bill Pmt -Check", None, "ACH", None, "08/20/2026", None, "SUNRISE JEWELRY MFG. CORP", None, "1002 · JP MORGAN CHASE BANK, N.A.", None, None, None, -6542.30, None, -6542.30])
    # Row 4: Empty
    ws.append([" "])
    # Row 5: Primary Bill Line (Metal Castings $6,150.30)
    ws.append([None, "Bill", None, "129147", None, "07/23/2026", None, None, None, "5040 · Metal (Castings)", None, None, None, 6150.30, None, -6150.30])
    # Row 6: Split Line Item without Type/Num/Date (Yellow line: Labor Setting $392.00)
    ws.append([None, "", None, "", None, "", None, None, None, "5035 · Labor (Setting)", None, None, None, 392.00, None, -392.00])
    # Row 7: TOTAL row
    ws.append(["TOTAL", None, None, None, None, None, None, None, None, None, None, None, None, 6542.30, None, -6542.30])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    file_bytes = buf.getvalue()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/v1/payments/upload",
            files={"file": ("sunrise_split.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"batch_number": "1", "effective_date": "2026-08-20"},
        )

    assert response.status_code == 201, f"Response: {response.text}"
    data = response.json()

    assert data["summary"]["valid_rows"] == 1
    assert data["summary"]["error_rows"] == 0
    assert len(data["valid_payments"]) == 1

    pmt = data["valid_payments"][0]
    # Total MUST be $6542.30, successfully accounting for the yellow line ($392.00)!
    assert pmt["vendor_name"] == "SUNRISE JEWELRY MFG. CORP"[:22]
    assert Decimal(pmt["amount"]) == Decimal("6542.30")
    assert pmt["id_number"] == "129147"
    assert pmt["invoice_breakdown"] is not None
    assert len(pmt["invoice_breakdown"]) == 1
    assert pmt["invoice_breakdown"][0]["invoice_number"] == "129147"
    assert Decimal(str(pmt["invoice_breakdown"][0]["amount"])) == Decimal("6542.30")

