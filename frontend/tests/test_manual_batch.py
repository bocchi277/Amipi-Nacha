"""
Frontend Phase 3 — Manual Batch 2 Inline Multi-Row Entry Playwright Tests.

Tests:
1. Valid manual entry test: fill inline row, submit -> valid payments rendered + NACHA auto-generated.
2. Multi-row entry test: add multiple rows inline, single submit validates all + auto-generates NACHA.
3. Flagged duplicate entry test: submitting identical manual transaction triggers duplicate warning banner,
   checking 'Allow Duplicate Override' and re-submitting forces successful override.
4. Edit saved Batch 2 payment row.
"""
import uuid
import pytest
from playwright.sync_api import Page, expect


_RUN_ID = uuid.uuid4().hex[:6]
TEST_USER = f"manual_user_{_RUN_ID}"
TEST_EMAIL = f"{TEST_USER}@amipi.com"
TEST_PASSWORD = "TestManualPass123!"


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
    v_name = f"MANUAL VENDOR {v_uid}"
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
                    account_number: '5544332211',
                    account_type: 'checking'
                })
            });
            return await res.json();
        }
        """,
        [base_url, v_name],
    )

    # Reload vendors dropdown in UI and await vendor options populated in inline table
    page.evaluate("async () => { await GenerateScreen.loadVendors(); }")
    page.wait_for_selector(f"#manualInlineTableBody .manual-row-vendor option[value='{v_res.get('id')}']", state="attached", timeout=5000)

    return v_name, v_res.get("id")


def test_valid_manual_batch_entry(page: Page, base_url: str):
    """Test adding a valid manual entry inline, verifying visible bank details, and submitting."""
    v_name, v_id = _register_login_and_create_vendor(page, base_url)

    inv_ref = f"MAN-{uuid.uuid4().hex[:6]}"

    # Fill shared effective date
    page.fill("#manualEffDate", "2026-08-15")

    # Select vendor on row 1
    row1 = page.locator("#manualInlineTableBody tr").first
    row1.locator(".manual-row-vendor").select_option(v_id)

    # Verify that Routing # and Account # are immediately visible in the table row
    expect(row1.locator(".manual-row-routing")).to_contain_text("026013356")
    expect(row1.locator(".manual-row-account")).to_contain_text("5544332211")

    # Fill amount and invoice ref
    row1.locator(".manual-row-amount").fill("3450.75")
    row1.locator(".manual-row-ref").fill(inv_ref)

    # Click Validate Batch 2 to check inline summary
    page.click("#validateBatch2Btn")
    expect(page.locator("#batch2ValidateSummary")).to_be_visible(timeout=5000)
    expect(page.locator("#batch2StatTotalRows")).to_contain_text("1")
    expect(page.locator("#batch2StatValidRows")).to_contain_text("1")
    expect(page.locator("#batch2StatErrorRows")).to_contain_text("0")
    expect(page.locator("#batch2StatTotalAmount")).to_contain_text("$3,450.75")

    # Click Generate Combined NACHA File (generates file cleanly without redundant review table)
    page.click("#generateNachaBtn")

    # NACHA output card should display
    expect(page.locator("#nachaOutputCard")).to_be_visible(timeout=10000)
    expect(page.locator("#nachaCreditTotal")).to_contain_text("3,450.75")


def test_validation_error_on_generate_nacha(page: Page, base_url: str):
    """Clicking Generate Combined NACHA with invalid Batch 2 row displays error and scrolls to problem block."""
    v_name, v_id = _register_login_and_create_vendor(page, base_url)

    # Leave amount empty
    row1 = page.locator("#manualInlineTableBody tr").first
    row1.locator(".manual-row-vendor").select_option(v_id)
    row1.locator(".manual-row-ref").fill("INV-ERR-01")

    # Click master Generate NACHA File button
    page.click("#generateNachaBtn")

    # Error message should appear in Batch 2 error panel
    error_el = page.locator("#manualFormError")
    expect(error_el).to_be_visible(timeout=5000)
    expect(error_el).to_contain_text("Row 1: Amount must be > 0")


def test_multi_row_manual_batch_entry(page: Page, base_url: str):
    """Test adding multiple rows inline and generating NACHA."""
    v_name, v_id = _register_login_and_create_vendor(page, base_url)

    # Fill shared effective date
    page.fill("#manualEffDate", "2026-08-15")

    # Fill row 1
    row1 = page.locator("#manualInlineTableBody tr").first
    row1.locator(".manual-row-vendor").select_option(v_id)
    row1.locator(".manual-row-amount").fill("1000.00")
    row1.locator(".manual-row-ref").fill("INV-001")

    # Add row 2
    page.click("#addManualRowBtn")
    expect(page.locator("#manualInlineTableBody tr")).to_have_count(2)
    row2 = page.locator("#manualInlineTableBody tr").nth(1)
    row2.locator(".manual-row-vendor").select_option(v_id)
    row2.locator(".manual-row-amount").fill("2000.00")
    row2.locator(".manual-row-ref").fill("INV-002")

    # Validate Batch 2 inline
    page.click("#validateBatch2Btn")
    expect(page.locator("#batch2ValidateSummary")).to_be_visible()
    expect(page.locator("#batch2StatTotalRows")).to_contain_text("2")
    expect(page.locator("#batch2StatValidRows")).to_contain_text("2")
    expect(page.locator("#batch2StatTotalAmount")).to_contain_text("$3,000.00")

    # Click Generate Combined NACHA File (validates both rows & generates NACHA)
    page.click("#generateNachaBtn")

    # NACHA generated
    expect(page.locator("#nachaOutputCard")).to_be_visible(timeout=10000)
    expect(page.locator("#nachaEntryCount")).to_contain_text("2")
    expect(page.locator("#nachaCreditTotal")).to_contain_text("3,000.00")


def test_flagged_duplicate_manual_entry_override(page: Page, base_url: str):
    """Test flagged duplicate manual entry triggers duplicate warning banner on Batch 2 card and allows override."""
    v_name, v_id = _register_login_and_create_vendor(page, base_url)

    inv_ref = f"DUP-{uuid.uuid4().hex[:6]}"

    # First manual entry submission via master generate
    page.fill("#manualEffDate", "2026-08-15")
    row1 = page.locator("#manualInlineTableBody tr").first
    row1.locator(".manual-row-vendor").select_option(v_id)
    row1.locator(".manual-row-amount").fill("1999.00")
    row1.locator(".manual-row-ref").fill(inv_ref)

    page.click("#generateNachaBtn")
    expect(page.locator("#nachaOutputCard")).to_be_visible(timeout=10000)
    expect(page.locator("#manualDuplicateBanner")).to_be_hidden()

    # Second submission with EXACT SAME parameters -> duplicate
    page.click("#generateNachaBtn")

    # Duplicate warning banner must appear in Batch 2 card
    expect(page.locator("#manualDuplicateBanner")).to_be_visible(timeout=10000)
    expect(page.locator("#manualDuplicateBanner")).to_contain_text("Duplicate Transactions Detected in Batch 2")

    # Check override checkbox and click Re-upload with Override
    page.check("#manualOverrideCheckbox")
    page.click("#manualRetryOverrideBtn")

    # NACHA output should generate with override
    expect(page.locator("#nachaOutputCard")).to_be_visible(timeout=10000)
    expect(page.locator("#manualDuplicateBanner")).to_be_hidden()


def test_edit_batch2_saved_payment(page: Page, base_url: str):
    """Test inline editing of a Batch 2 payment row."""
    v_name, v_id = _register_login_and_create_vendor(page, base_url)

    inv_ref = f"ED-{uuid.uuid4().hex[:4]}"
    updated_ref = f"ED2-{uuid.uuid4().hex[:4]}"

    # Fill and submit
    page.fill("#manualEffDate", "2026-08-15")
    row1 = page.locator("#manualInlineTableBody tr").first
    row1.locator(".manual-row-vendor").select_option(v_id)
    row1.locator(".manual-row-amount").fill("1000.00")
    row1.locator(".manual-row-ref").fill(inv_ref)

    # Edit row directly in inline table
    row1.locator(".manual-row-amount").fill("1500.00")
    row1.locator(".manual-row-ref").fill(updated_ref)

    # Validate updated row
    page.click("#validateBatch2Btn")
    expect(page.locator("#batch2ValidateSummary")).to_be_visible()
    expect(page.locator("#batch2StatTotalAmount")).to_contain_text("$1,500.00")

    # Generate NACHA
    page.click("#generateNachaBtn")
    expect(page.locator("#nachaOutputCard")).to_be_visible(timeout=10000)
    expect(page.locator("#nachaCreditTotal")).to_contain_text("1,500.00")


def test_dynamic_add_batch_and_master_generation(page: Page, base_url: str):
    """Test clicking + Add Batch to dynamically add Batch 3, filling both, and generating NACHA."""
    v_name, v_id = _register_login_and_create_vendor(page, base_url)

    # Fill Batch 2
    page.fill("#manualEffDate", "2026-08-15")
    row1 = page.locator("#manualInlineTableBody tr").first
    row1.locator(".manual-row-vendor").select_option(v_id)
    row1.locator(".manual-row-amount").fill("1200.00")
    row1.locator(".manual-row-ref").fill("INV-B2-01")

    # Click + Add Batch to dynamically create Batch 3
    page.click("#addBatchBtn")
    expect(page.locator("#card_batch_3")).to_be_visible()
    expect(page.locator("#card_batch_3")).to_contain_text("Manual Payment Entry (Batch 3)")

    # Fill Batch 3
    page.fill("#manualEffDate_3", "2026-08-16")
    b3_row1 = page.locator("#manualInlineTableBody_3 tr").first
    b3_row1.locator(".manual-row-vendor").select_option(v_id)
    b3_row1.locator(".manual-row-amount").fill("2300.00")
    b3_row1.locator(".manual-row-ref").fill("INV-B3-01")

    # Master button Generate Combined NACHA File validates both batches and generates combined NACHA
    page.click("#generateNachaBtn")

    # NACHA output card rendered
    expect(page.locator("#nachaOutputCard")).to_be_visible(timeout=10000)
    expect(page.locator("#nachaEntryCount")).to_contain_text("2")
    expect(page.locator("#nachaCreditTotal")).to_contain_text("$3,500.00")
