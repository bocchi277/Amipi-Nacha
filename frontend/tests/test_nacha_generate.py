"""
Frontend Phase 4 — Combined NACHA File Generation & File Download Playwright Tests.

Tests:
1. Combined NACHA file generation: uploads Batch 1 CSV + submits Batch 2 manual entry,
   triggers combined NACHA generation, verifies control totals and 94-char fixed width raw content preview.
2. File download confirmation: clicks 'Download NACHA File (.txt)', catches the Playwright download event,
   saves the file, and validates that every line in the downloaded text file is exactly 94 characters long.
"""
import tempfile
import uuid
import pytest
from playwright.sync_api import Page, expect


_RUN_ID = uuid.uuid4().hex[:6]
TEST_USER = f"nacha_user_{_RUN_ID}"
TEST_EMAIL = f"{TEST_USER}@amipi.com"
TEST_PASSWORD = "TestNachaPass123!"


def _register_login_and_create_vendor(page: Page, base_url: str):
    """Helper: register user, log in through UI, and create a test vendor via API."""
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
                body: JSON.stringify({ email, username, password, role: 'admin' })
            });
        }
        """,
        [base_url, TEST_EMAIL, TEST_USER, TEST_PASSWORD],
    )

    # Login via UI
    page.fill("#loginUsername", TEST_USER)
    page.fill("#loginPassword", TEST_PASSWORD)
    page.click("#loginSubmitBtn")
    expect(page.locator("#appShell")).to_be_visible(timeout=5000)

    # Create a test vendor via API
    v_uid = uuid.uuid4().hex[:6]
    v_name = f"NACHA VENDOR {v_uid}"
    v_res = page.evaluate(
        """
        async ([url, name]) => {
            const token = sessionStorage.getItem('amipi_token');
            const res = await fetch(url + '/api/v1/vendors', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + token
                },
                body: JSON.stringify({
                    name: name,
                    routing_number: '026013356',
                    account_number: '9988776655',
                    account_type: 'checking'
                })
            });
            return await res.json();
        }
        """,
        [base_url, v_name],
    )

    page.evaluate("async () => { await GenerateScreen.loadVendors(); }")
    page.wait_for_selector(f"#manualVendorSelect option[value='{v_res.get('id')}']", state="attached", timeout=5000)

    return v_name, v_res.get("id")


def create_temp_csv(content: str) -> str:
    """Create a temporary CSV file."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
    tmp.write(content)
    tmp.close()
    return tmp.name


def test_combined_nacha_file_generation_and_download(page: Page, base_url: str):
    """Test generating a combined NACHA file from Batch 1 + Batch 2 and retrieving the downloaded file."""
    v_name, v_id = _register_login_and_create_vendor(page, base_url)

    uid = uuid.uuid4().hex[:6]
    batch1_vendor = f"SPREADSHEET VENDOR {uid}"
    batch1_inv = f"INV-B1-{uid}"

    # Step 1: Upload Batch 1 Spreadsheet
    csv_content = (
        "Vendor Name,Routing Number,Account Number,Account Type,Amount,Invoice Number\n"
        f"{batch1_vendor},026013356,1234567890,Checking,5000.00,{batch1_inv}\n"
    )
    tmp_file = create_temp_csv(csv_content)
    page.set_input_files("#fileInput", tmp_file)
    page.click("#uploadBtn")
    expect(page.locator("#resultsSection")).to_be_visible(timeout=10000)

    # Step 2: Submit Batch 2 Manual Entry
    batch2_inv = f"INV-B2-{uid}"
    page.select_option("#manualVendorSelect", v_id)
    page.fill("#manualAmount", "2500.50")
    page.fill("#manualIdNumber", batch2_inv)
    page.fill("#manualEffDate", "2026-08-20")
    page.click("#addManualEntryBtn")
    expect(page.locator("#manualDraftSection")).to_be_visible()
    page.click("#submitManualBatchBtn")
    expect(page.locator("#manualResultsSection")).to_be_visible(timeout=10000)

    # Step 3: Trigger Combined NACHA Generation
    generate_btn = page.locator("#generateNachaBtn")
    expect(generate_btn).to_be_enabled()
    generate_btn.click()

    # Step 4: Confirm Output Card renders with metadata
    expect(page.locator("#nachaOutputCard")).to_be_visible(timeout=10000)

    expect(page.locator("#nachaEntryCount")).to_contain_text("2")
    expect(page.locator("#nachaBatchCount")).to_contain_text("2")
    expect(page.locator("#nachaCreditTotal")).to_contain_text("$7,500.50")

    raw_preview = page.locator("#nachaRawPreview").text_content()
    assert raw_preview is not None
    lines = [line.strip("\r") for line in raw_preview.split("\n") if line.strip("\r")]

    # Validate 94-character fixed-width rule for all NACHA records
    for idx, line in enumerate(lines):
        assert len(line) == 94, f"Line {idx + 1} length is {len(line)}, expected 94."

    # Validate NACHA record hierarchy (1 Header, 5 Batch Header, 6 Entry Detail, 8 Batch Control, 9 File Control)
    assert lines[0].startswith("1"), "First record must be File Header Record (type 1)"
    assert any(l.startswith("5") for l in lines), "Must contain Batch Header Record (type 5)"
    assert any(l.startswith("6") for l in lines), "Must contain Entry Detail Record (type 6)"
    assert any(l.startswith("8") for l in lines), "Must contain Batch Control Record (type 8)"
    assert lines[-1].startswith("9"), "Last record must be File Control Record (type 9)"

    # Step 5: Test Download Action and retrieve downloaded text file
    with page.expect_download() as download_info:
        page.click("#downloadNachaBtn")

    download = download_info.value
    download_path = download.path()
    assert download_path is not None

    with open(download_path, "r", encoding="utf-8") as f:
        downloaded_content = f.read()

    downloaded_lines = [l.strip("\r") for l in downloaded_content.split("\n") if l.strip("\r")]
    assert len(downloaded_lines) > 0
    for l in downloaded_lines:
        assert len(l) == 94, "Downloaded NACHA file line length must be exactly 94 characters."
