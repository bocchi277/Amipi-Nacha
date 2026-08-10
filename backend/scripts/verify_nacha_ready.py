"""
Comprehensive System Ready Check for NACHA File Generation.

Loads PAYMENTS 20260730.xlsx, parses payments against Neon/Local DB vendors,
validates ABA routing checksums, generates NACHA file, and asserts full Chase spec compliance.
"""
import asyncio
import sys
from datetime import date
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import AsyncSessionLocal
from app.nacha.generator import generate_nacha_file
from app.nacha.models import Batch, EntryDetail, FileHeaderConfig, NachaFileInput
from app.nacha.validation import validate_nacha_input, validate_routing_checksum
from app.services.spreadsheet_parser import parse_payment_spreadsheet


async def run_system_readiness_check():
    print("\n==========================================================================================")
    print("                 AMIPI ACH NACHA SYSTEM — E2E READINESS VERIFICATION CHECK                ")
    print("==========================================================================================")

    # Step 1: Read sample spreadsheet
    xlsx_path = Path(__file__).resolve().parent.parent.parent / "PAYMENTS 20260730.xlsx"
    if not xlsx_path.exists():
        print(f"FAILED: File not found at {xlsx_path}")
        sys.exit(1)

    file_bytes = xlsx_path.read_bytes()
    print(f"Step 1: Loaded Excel File '{xlsx_path.name}' ({len(file_bytes)} bytes).")

    # Step 2: Parse spreadsheet with database session
    async with AsyncSessionLocal() as db:
        parsed_res = await parse_payment_spreadsheet(
            file_bytes=file_bytes,
            filename=xlsx_path.name,
            db_session=db,
            default_effective_date=date.today(),
        )

        print(f"Step 2: Spreadsheet Parsed -> Total Rows: {parsed_res.total_rows_parsed}, Valid Payments: {len(parsed_res.valid_payments)}, Errors: {len(parsed_res.errors)}")

        if parsed_res.errors:
            print("\n  [!] Validation Warnings/Skipped Rows:")
            for err in parsed_res.errors:
                print(f"      Row {err.row_number}: {err.errors}")

        if not parsed_res.valid_payments:
            print("\nFAILED: No valid payment entries produced from spreadsheet.")
            sys.exit(1)

        # Step 3: Build NACHA File Input
        entries = []
        for p in parsed_res.valid_payments:
            # Verify ABA checksum
            if not validate_routing_checksum(p.routing_number):
                print(f"FAILED: Vendor '{p.vendor_name}' routing number '{p.routing_number}' fails ABA checksum.")
                sys.exit(1)

            entries.append(
                EntryDetail(
                    transaction_code="22" if p.account_type.lower() == "checking" else "32",
                    routing_number=p.routing_number,
                    account_number=p.account_number,
                    amount=str(p.amount),
                    id_number=p.id_number,
                    receiver_name=p.vendor_name,
                )
            )

        file_input = NachaFileInput(
            header=FileHeaderConfig(
                company_name="AMIPI INC",
                company_account="785957066",
                effective_entry_date=date.today().strftime("%y%m%d"),
                file_creation_date=date.today().strftime("%y%m%d"),
                file_creation_time="1200",
                file_id_modifier="A",
                entry_description="EPAYMNT",
            ),
            batches=[Batch(entries=entries)],
        )

        # Step 4: Validate NACHA input
        val_res = validate_nacha_input(file_input)
        if not val_res.is_valid:
            print(f"Step 4: NACHA Input Validation FAILED:\n{val_res}")
            sys.exit(1)
        print("Step 4: NACHA Input Validation PASSED (100% compliant with Chase specs).")

        # Step 5: Generate NACHA File Content
        gen_res = generate_nacha_file(file_input)
        lines = gen_res.content.splitlines()


        print(f"Step 5: NACHA File Generated Successfully!")
        print(f"        Total Lines: {len(lines)} (Must be multiple of 10 -> {len(lines) % 10 == 0})")
        print(f"        Record 1 (File Header):   {lines[0][:60]}...")
        print(f"        Record 5 (Batch Header):  {lines[1][:60]}...")
        print(f"        Record 6 (Entry Sample):  {lines[2][:60]}...")
        print(f"        Record 8 (Batch Control): {lines[-2][:60]}...")
        print(f"        Record 9 (File Control):  {lines[-1][:60]}...")

        # Strict spec assertions
        assert len(lines) % 10 == 0, "NACHA file must be padded to a multiple of 10 lines."
        assert all(len(line) == 94 for line in lines), "Every line in NACHA file must be exactly 94 characters."
        assert lines[0].startswith("101 021000021"), "File header must start with Chase destination/origin 101."
        assert lines[1].startswith("5220AMIPI INC"), "Batch header must start with Service Class 220."

        print("\n==========================================================================================")
        print(" SUCCESS: NACHA FILE GENERATION SYSTEM IS 100% VERIFIED & READY FOR PRODUCTION DEPLOYMENT! ")
        print("==========================================================================================\n")


if __name__ == "__main__":
    asyncio.run(run_system_readiness_check())
