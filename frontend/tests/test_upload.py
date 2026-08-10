"""
Frontend Phase 2 — Spreadsheet Upload Playwright Tests.

Tests:
1. Clean upload case: valid spreadsheet upload renders summary stats and valid payments table.
2. Malformed-row upload case: spreadsheet with invalid rows displays error panel with row-level error details.
3. Duplicate detection with explicit override case: uploading duplicate payments shows duplicate warning banner,
   checking 'Allow Duplicate Override' and clicking re-upload forces successful override.
"""
import tempfile
import uuid
import pytest
from playwright.sync_api import Page, expect


_RUN_ID = uuid.uuid4().hex[:6]
TEST_USER = f"upload_user_{_RUN_ID}"
TEST_EMAIL = f"{TEST_USER}@amipi.com"
TEST_PASSWORD = "TestUploadPass123!"


def _register_and_login(page: Page, base_url: str):
    """Helper: register user via API and log in through UI."""
    page.goto(base_url)
    page.evaluate("sessionStorage.clear()")
    page.reload()
    page.wait_for_load_state("networkidle")

    # Register user via API
    page.evaluate(
        """
        async ([url, email, username, password]) => {
            await fetch(url + '/api/v1/auth/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, username, password, role: 'user' })
            });
        }
        """,
        [base_url, TEST_EMAIL, TEST_USER, TEST_PASSWORD],
    )

    # Login via UI
    page.fill("#loginUsername", TEST_USER)
    page.fill("#loginPassword", TEST_PASSWORD)
    page.click("#loginSubmitBtn")

    # Wait for app shell
    expect(page.locator("#appShell")).to_be_visible(timeout=5000)


def create_temp_csv(content: str) -> str:
    """Create a temporary CSV file with given content."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
    tmp.write(content)
    tmp.close()
    return tmp.name


def test_clean_spreadsheet_upload(page: Page, base_url: str):
    """Test uploading a clean valid CSV spreadsheet renders stats and payments table."""
    _register_and_login(page, base_url)

    uid = uuid.uuid4().hex[:6]
    v1_name = f"ALPHA CORP {uid}"
    v2_name = f"BETA LLC {uid}"
    inv1 = f"INV-1001-{uid}"
    inv2 = f"INV-1002-{uid}"

    # Prepare valid CSV file with standard headers
    csv_content = (
        "Vendor Name,Routing Number,Account Number,Account Type,Amount,Invoice Number\n"
        f"{v1_name},026013356,0399022538,Checking,1250.50,{inv1}\n"
        f"{v2_name},021000021,9876543210,Checking,850.00,{inv2}\n"
    )
    tmp_file = create_temp_csv(csv_content)

    # Select file via file input
    page.set_input_files("#fileInput", tmp_file)

    # Selected file info should show
    expect(page.locator("#uploadFileInfo")).to_be_visible()
    expect(page.locator("#uploadBtn")).to_be_enabled()

    # Click Upload & Parse
    page.click("#uploadBtn")

    # Results section should become visible
    expect(page.locator("#resultsSection")).to_be_visible(timeout=10000)

    # Stat values check
    expect(page.locator("#statTotalRows")).to_contain_text("2")
    expect(page.locator("#statValidRows")).to_contain_text("2")
    expect(page.locator("#statErrorRows")).to_contain_text("0")
    expect(page.locator("#statTotalAmount")).to_contain_text("$2,100.50")

    # Valid payments table should contain vendor names
    tbody = page.locator("#validPaymentsTableBody")
    expect(tbody).to_contain_text(v1_name)
    expect(tbody).to_contain_text(v2_name)

    # No duplicate banner or error panel
    expect(page.locator("#duplicateBanner")).to_be_hidden()
    expect(page.locator("#errorPanel")).to_be_hidden()


def test_malformed_row_upload_shows_errors(page: Page, base_url: str):
    """Test uploading a CSV with malformed rows displays error panel with details."""
    _register_and_login(page, base_url)

    uid = uuid.uuid4().hex[:6]
    valid_name = f"VALID VENDOR {uid}"
    inv1 = f"INV-2001-{uid}"
    inv2 = f"INV-2002-{uid}"
    inv3 = f"INV-2003-{uid}"

    # CSV with 1 valid row, 1 invalid routing checksum row, 1 negative amount row
    csv_content = (
        "Vendor Name,Routing Number,Account Number,Account Type,Amount,Invoice Number\n"
        f"{valid_name},026013356,11112222,Checking,500.00,{inv1}\n"
        f"INVALID ROUTING {uid},123456789,33334444,Checking,300.00,{inv2}\n"
        f"BAD AMOUNT {uid},021000021,55556666,Checking,-50.00,{inv3}\n"
    )
    tmp_file = create_temp_csv(csv_content)

    page.set_input_files("#fileInput", tmp_file)
    page.click("#uploadBtn")

    expect(page.locator("#resultsSection")).to_be_visible(timeout=10000)

    # Stats: 3 total, 1 valid, 2 error
    expect(page.locator("#statTotalRows")).to_contain_text("3")
    expect(page.locator("#statValidRows")).to_contain_text("1")
    expect(page.locator("#statErrorRows")).to_contain_text("2")

    # Error panel must be visible
    expect(page.locator("#errorPanel")).to_be_visible()
    expect(page.locator("#errorTableBody")).to_contain_text("Row 3")
    expect(page.locator("#errorTableBody")).to_contain_text("Row 4")

    # Valid table shows only 1 valid row
    tbody = page.locator("#validPaymentsTableBody")
    expect(tbody).to_contain_text(valid_name)
    expect(tbody).not_to_contain_text("INVALID ROUTING")


def test_duplicate_detection_and_explicit_override(page: Page, base_url: str):
    """Test duplicate detection warning banner and explicit override functionality."""
    _register_and_login(page, base_url)

    uid = uuid.uuid4().hex[:6]
    dup_vendor = f"DUP VENDOR {uid}"
    unique_inv = f"DUP-{uid}"
    csv_content = (
        f"Vendor Name,Routing Number,Account Number,Account Type,Amount,Invoice Number\n"
        f"{dup_vendor},026013356,77778888,Checking,999.00,{unique_inv}\n"
    )
    tmp_file = create_temp_csv(csv_content)

    # First upload — clean upload
    page.set_input_files("#fileInput", tmp_file)
    page.click("#uploadBtn")
    expect(page.locator("#resultsSection")).to_be_visible(timeout=10000)
    expect(page.locator("#duplicateBanner")).to_be_hidden()

    # Second upload of the EXACT same file -> triggers duplicate detection
    page.set_input_files("#fileInput", tmp_file)
    page.click("#uploadBtn")

    # Duplicate warning banner must appear
    expect(page.locator("#duplicateBanner")).to_be_visible(timeout=10000)
    expect(page.locator("#duplicateBanner")).to_contain_text("Duplicate Transactions Detected")

    # Check override checkbox and click Re-upload with Override
    page.check("#overrideCheckbox")
    page.click("#retryOverrideBtn")

    # Results section should update with override status
    expect(page.locator("#resultsSection")).to_be_visible(timeout=10000)
    expect(page.locator("#duplicateBanner")).to_be_hidden()

    # Valid table displays Override Duplicate badge and upper-cased vendor name
    tbody = page.locator("#validPaymentsTableBody")
    expect(tbody).to_contain_text(dup_vendor.upper())
    expect(tbody).to_contain_text("Override Duplicate")
