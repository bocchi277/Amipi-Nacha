"""
Frontend Phase 3 — Manual Batch 2 Entry Playwright Tests.

Tests:
1. Valid manual entry test: select vendor, enter amount/ref/date, stage entry, submit batch -> valid payments rendered.
2. Flagged duplicate entry test: submitting identical manual transaction triggers duplicate warning banner,
   checking 'Allow Duplicate Override' and re-submitting forces successful override.
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

    # Reload vendors dropdown in UI and await option attached in DOM
    page.evaluate("async () => { await GenerateScreen.loadVendors(); }")
    page.wait_for_selector(f"#manualVendorSelect option[value='{v_res.get('id')}']", state="attached", timeout=5000)

    return v_name, v_res.get("id")


def test_valid_manual_batch_entry(page: Page, base_url: str):
    """Test adding a valid manual entry to Batch 2 and submitting the batch."""
    v_name, v_id = _register_login_and_create_vendor(page, base_url)

    # Select vendor in dropdown
    page.select_option("#manualVendorSelect", v_id)

    inv_ref = f"MAN-{uuid.uuid4().hex[:6]}"
    page.fill("#manualAmount", "3450.75")
    page.fill("#manualIdNumber", inv_ref)
    page.fill("#manualEffDate", "2026-08-15")

    # Click Add Entry to Batch 2 List
    page.click("#addManualEntryBtn")

    # Staged table should appear
    expect(page.locator("#manualDraftSection")).to_be_visible()
    expect(page.locator("#manualDraftTableBody")).to_contain_text(v_name)
    expect(page.locator("#manualDraftTableBody")).to_contain_text("3450.75")
    expect(page.locator("#manualDraftTableBody")).to_contain_text(inv_ref)

    # Click Submit & Save Manual Batch 2
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

    # No duplicate warning banner
    expect(page.locator("#manualDuplicateBanner")).to_be_hidden()


def test_flagged_duplicate_manual_entry_override(page: Page, base_url: str):
    """Test flagged duplicate manual entry triggers duplicate warning banner and allows override."""
    v_name, v_id = _register_login_and_create_vendor(page, base_url)

    inv_ref = f"DUPMAN-{uuid.uuid4().hex[:6]}"

    # First manual entry submission
    page.select_option("#manualVendorSelect", v_id)
    page.fill("#manualAmount", "1999.00")
    page.fill("#manualIdNumber", inv_ref)
    page.fill("#manualEffDate", "2026-08-15")
    page.click("#addManualEntryBtn")
    expect(page.locator("#manualDraftSection")).to_be_visible()
    page.click("#submitManualBatchBtn")

    expect(page.locator("#manualResultsSection")).to_be_visible(timeout=10000)
    expect(page.locator("#manualDuplicateBanner")).to_be_hidden()

    # Second manual entry with EXACT SAME parameters -> duplicate
    page.select_option("#manualVendorSelect", v_id)
    page.fill("#manualAmount", "1999.00")
    page.fill("#manualIdNumber", inv_ref)
    page.fill("#manualEffDate", "2026-08-15")
    page.click("#addManualEntryBtn")
    expect(page.locator("#manualDraftSection")).to_be_visible()
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
