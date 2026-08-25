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
    """Test adding a valid manual entry inline and submitting — results + auto NACHA generation."""
    v_name, v_id = _register_login_and_create_vendor(page, base_url)

    inv_ref = f"MAN-{uuid.uuid4().hex[:6]}"

    # Fill shared effective date
    page.fill("#manualEffDate", "2026-08-15")

    # Fill inline row 1
    row1 = page.locator("#manualInlineTableBody tr").first
    row1.locator(".manual-row-vendor").select_option(v_id)
    row1.locator(".manual-row-amount").fill("3450.75")
    row1.locator(".manual-row-ref").fill(inv_ref)

    # Click Validate & Generate NACHA (single button)
    page.click("#submitManualBatchBtn")

    # Results section should display
    expect(page.locator("#manualResultsSection")).to_be_visible(timeout=10000)

    # Stat values check
    expect(page.locator("#manualStatTotalRows")).to_contain_text("1")
    expect(page.locator("#manualStatValidRows")).to_contain_text("1")
    expect(page.locator("#manualStatErrorRows")).to_contain_text("0")
    expect(page.locator("#manualStatTotalAmount")).to_contain_text("$3,450.75")

    # Valid payments table check
    tbody = page.locator("#manualValidPaymentsTableBody")
    expect(tbody).to_contain_text(v_name)
    expect(tbody).to_contain_text(inv_ref)
    expect(tbody).to_contain_text("Valid")
    expect(tbody.locator("button:has-text('Edit')")).to_be_visible()
    expect(tbody.locator("button:has-text('Remove')")).to_be_visible()

    # No duplicate warning banner
    expect(page.locator("#manualDuplicateBanner")).to_be_hidden()

    # NACHA file should be auto-generated (no need to click Generate separately)
    expect(page.locator("#nachaOutputCard")).to_be_visible(timeout=10000)


def test_multi_row_manual_batch_entry(page: Page, base_url: str):
    """Test adding multiple rows inline and submitting all in one click."""
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

    # Single click validates + generates
    page.click("#submitManualBatchBtn")

    # Results appear
    expect(page.locator("#manualResultsSection")).to_be_visible(timeout=10000)
    expect(page.locator("#manualStatTotalRows")).to_contain_text("2")
    expect(page.locator("#manualStatValidRows")).to_contain_text("2")
    expect(page.locator("#manualStatTotalAmount")).to_contain_text("$3,000.00")

    # NACHA auto-generated
    expect(page.locator("#nachaOutputCard")).to_be_visible(timeout=10000)


def test_flagged_duplicate_manual_entry_override(page: Page, base_url: str):
    """Test flagged duplicate manual entry triggers duplicate warning banner and allows override."""
    v_name, v_id = _register_login_and_create_vendor(page, base_url)

    inv_ref = f"DUP-{uuid.uuid4().hex[:6]}"

    # First manual entry submission
    page.fill("#manualEffDate", "2026-08-15")
    row1 = page.locator("#manualInlineTableBody tr").first
    row1.locator(".manual-row-vendor").select_option(v_id)
    row1.locator(".manual-row-amount").fill("1999.00")
    row1.locator(".manual-row-ref").fill(inv_ref)

    page.click("#submitManualBatchBtn")
    expect(page.locator("#manualResultsSection")).to_be_visible(timeout=10000)
    expect(page.locator("#manualDuplicateBanner")).to_be_hidden()

    # Second submission with EXACT SAME parameters -> duplicate
    # Inline table still has the same values, so just re-submit
    page.click("#submitManualBatchBtn")

    # Duplicate warning banner must appear
    expect(page.locator("#manualDuplicateBanner")).to_be_visible(timeout=10000)
    expect(page.locator("#manualDuplicateBanner")).to_contain_text("Duplicate Transactions Detected in Batch 2")

    # Check override checkbox and click Re-upload with Override
    page.check("#manualOverrideCheckbox")
    page.click("#manualRetryOverrideBtn")

    # Results section should update with override status
    expect(page.locator("#manualResultsSection")).to_be_visible(timeout=10000)
    expect(page.locator("#manualDuplicateBanner")).to_be_hidden()

    # Valid table displays Override Duplicate badge
    tbody = page.locator("#manualValidPaymentsTableBody")
    expect(tbody).to_contain_text(v_name)
    expect(tbody).to_contain_text("Override Duplicate")


def test_edit_batch2_saved_payment(page: Page, base_url: str):
    """Test editing a saved Batch 2 payment row."""
    v_name, v_id = _register_login_and_create_vendor(page, base_url)

    inv_ref = f"ED-{uuid.uuid4().hex[:4]}"
    updated_ref = f"ED2-{uuid.uuid4().hex[:4]}"

    # Fill and submit
    page.fill("#manualEffDate", "2026-08-15")
    row1 = page.locator("#manualInlineTableBody tr").first
    row1.locator(".manual-row-vendor").select_option(v_id)
    row1.locator(".manual-row-amount").fill("1000.00")
    row1.locator(".manual-row-ref").fill(inv_ref)

    page.click("#submitManualBatchBtn")
    expect(page.locator("#manualResultsSection")).to_be_visible(timeout=10000)

    # Click Edit button on the saved row
    page.locator("#manualValidPaymentsTableBody button:has-text('Edit')").click()
    expect(page.locator("#editPaymentRowModal")).to_be_visible()
    expect(page.locator("#editPaymentAmount")).to_have_value("1000.00")
    expect(page.locator("#editPaymentRef")).to_have_value(inv_ref)

    # Modify amount and invoice ref (within NACHA 15 chars limit)
    page.fill("#editPaymentAmount", "1500.00")
    page.fill("#editPaymentRef", updated_ref)
    page.click("#saveEditPaymentBtn")

    # Modal should close and table/stats should update
    expect(page.locator("#editPaymentRowModal")).to_be_hidden()
    expect(page.locator("#manualStatTotalAmount")).to_contain_text("$1,500.00")
    expect(page.locator("#manualValidPaymentsTableBody")).to_contain_text("$1,500.00")
    expect(page.locator("#manualValidPaymentsTableBody")).to_contain_text(updated_ref)
