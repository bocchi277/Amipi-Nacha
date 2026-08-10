"""
Frontend Phase 9 — Help Screen & Downloadable Payment Templates Playwright Tests.

Tests:
1. Help Screen Content Rendering: Asserts Help & Templates tab displays system usage guide,
   downloadable template cards, and technical validation rules table.
2. Real Payment Template File Download: Triggers download payment template button, captures real file download,
   and verifies CSV header structure matches backend parser specs (spreadsheet_parser.py).
3. Real Vendor Template File Download: Triggers download vendor template button, captures real file download,
   and verifies CSV header structure matches vendor import specs.
"""
import uuid
import pytest
from playwright.sync_api import Page, expect


_RUN_ID = uuid.uuid4().hex[:6]
STD_USER = f"std_user_p9_{_RUN_ID}"
STD_EMAIL = f"{STD_USER}@amipi.com"
STD_PASSWORD = "StdUserPass123!"


def test_help_screen_content_rendering_and_template_downloads(page: Page, base_url: str):
    """Test Help & Templates screen rendering and real downloadable CSV template files."""
    page.goto(base_url)
    page.evaluate("sessionStorage.clear()")
    page.reload()

    # Step 1: Register Standard User & Login
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
        [base_url, STD_EMAIL, STD_USER, STD_PASSWORD],
    )

    page.wait_for_selector("#loginUsername")
    page.fill("#loginUsername", STD_USER)
    page.fill("#loginPassword", STD_PASSWORD)
    page.click("#loginSubmitBtn")
    expect(page.locator("#appShell")).to_be_visible(timeout=10000)

    # Step 2: Open Help & Templates Tab
    page.click("button[data-view='help']")
    expect(page.locator("#view-help")).to_be_visible()

    # Step 3: Assert Content Sections & Tables Render
    expect(page.locator("#view-help")).to_contain_text("Downloadable Spreadsheet Import Templates")
    expect(page.locator("#view-help")).to_contain_text("System Usage Guide & NACHA Rules")
    expect(page.locator("#view-help")).to_contain_text("Field Technical Specifications & Validation Rules")
    expect(page.locator("#view-help")).to_contain_text("Modulus 10 checksum algorithm")

    # Step 4: Test Real Payment Import Template Download
    with page.expect_download() as download_info:
        page.click("#downloadPaymentTemplateBtnHelp")
    
    pay_download = download_info.value
    assert pay_download.suggested_filename == "payment_import_template.csv"
    
    pay_path = pay_download.path()
    with open(pay_path, "r", encoding="utf-8") as f:
        pay_csv_text = f.read()

    assert "Vendor Name,Routing Number,Account Number,Account Type,Amount,Invoice Number" in pay_csv_text
    assert "EXAMPLE VENDOR LLC,021000021,1234567890,Checking,1500.00,INV-1001" in pay_csv_text

    # Step 5: Test Real Vendor Import Template Download
    with page.expect_download() as download_info_v:
        page.click("#downloadVendorTemplateBtnHelp")
    
    ven_download = download_info_v.value
    assert ven_download.suggested_filename == "vendor_import_template.csv"

    ven_path = ven_download.path()
    with open(ven_path, "r", encoding="utf-8") as f:
        ven_csv_text = f.read()

    assert "name,routing,account,type,email" in ven_csv_text
    assert "ACME SUPPLIES,021000021,999888777666,Checking,ap@acmesupplies.com" in ven_csv_text
