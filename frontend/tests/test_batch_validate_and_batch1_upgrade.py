"""
Comprehensive Test Suite for:
1. Validate Batch button (informational inline summary, non-blocking editing).
2. Batch 1 Manual Payment Entry upgrade to multi-row inline table with live bank details.
3. Multi-batch combined NACHA generation using Batch 1 Manual + Batch 2 + dynamic Batch 3.
"""
import uuid
import pytest
from playwright.sync_api import Page, expect


def _setup_authenticated_session(page: Page, base_url: str):
    """Register and log in an admin user, then navigate to the Generate screen."""
    page.goto(base_url)
    page.evaluate("sessionStorage.clear()")
    page.reload()
    page.wait_for_load_state("networkidle")

    admin_user = f"val_admin_{uuid.uuid4().hex[:6]}"
    admin_email = f"{admin_user}@amipi.com"
    admin_password = "ValidatePass123!"

    # Register admin user via API
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
        [base_url, admin_email, admin_user, admin_password],
    )

    # Log in via UI
    page.fill("#loginUsername", admin_user)
    page.fill("#loginPassword", admin_password)
    page.click("#loginSubmitBtn")
    expect(page.locator("#appShell")).to_be_visible(timeout=5000)

    # Ensure on Generate Payments screen
    page.click(".tab[data-view='generate']")
    expect(page.locator("#view-generate")).to_be_visible()


def _create_test_vendor(page: Page, base_url: str, name: str, routing: str, acct: str = None, acct_type: str = "checking") -> str:
    """Helper to create a vendor via API and reload vendors cache."""
    if not acct:
        acct = f"88{uuid.uuid4().int % 100000000:08d}"

    res = page.evaluate(
        """
        async ([url, name, routing, acct, acct_type]) => {
            const token = sessionStorage.getItem('amipi_token');
            const response = await fetch(url + '/api/v1/vendors', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + token
                },
                body: JSON.stringify({
                    name: name,
                    routing_number: routing,
                    account_number: acct,
                    account_type: acct_type,
                    email: name.toLowerCase().replace(/[^a-z0-9]/g, '') + '@vendor.com'
                })
            });
            const data = await response.json();
            if (data.id) return data.id;
            if (data.detail && data.detail.vendor_id) return data.detail.vendor_id;
            throw new Error('Vendor creation failed: ' + JSON.stringify(data));
        }
        """,
        [base_url, name, routing, acct, acct_type],
    )
    vendor_id = str(res)
    assert vendor_id and vendor_id != "None", f"Invalid vendor ID returned: {vendor_id}"

    # Refresh vendors in frontend
    page.evaluate("async () => { await GenerateScreen.loadVendors(); }")
    page.wait_for_selector(f"#manualInlineTableBody .manual-row-vendor option[value='{vendor_id}']", state="attached", timeout=5000)
    return vendor_id


def test_batch1_manual_mode_ui_and_row_management(page: Page, base_url: str):
    """Verify Batch 1 Manual Payment Entry tab has the updated multi-row inline table, +Add Row, and x Remove Row."""
    _setup_authenticated_session(page, base_url)

    v1_id = _create_test_vendor(page, base_url, f"B1 Vendor Alpha {uuid.uuid4().hex[:4]}", "021000021", "111222333444", "checking")
    v2_id = _create_test_vendor(page, base_url, f"B1 Vendor Beta {uuid.uuid4().hex[:4]}", "026013356", "555666777888", "savings")

    # Switch Batch 1 to Manual Payment Entry tab
    page.click("#batch1TabManualBtn")
    expect(page.locator("#batch1ManualPanel")).to_be_visible()
    expect(page.locator("#batch1UploadPanel")).to_be_hidden()

    # Table is present with initial 1 row
    expect(page.locator("#b1ManualInlineTable")).to_be_visible()
    rows = page.locator("#b1ManualInlineTableBody tr")
    expect(rows).to_have_count(1)

    # Select vendor in Row 1 -> verify auto-populated bank details
    row1 = rows.first
    row1.locator(".manual-row-vendor").select_option(v1_id)
    expect(row1.locator(".manual-row-routing")).to_contain_text("021000021")
    expect(row1.locator(".manual-row-account")).to_contain_text("111222333444")
    expect(row1.locator(".manual-row-type")).to_contain_text("checking", ignore_case=True)

    # Add a second row
    page.click("#addB1ManualRowBtn")
    expect(page.locator("#b1ManualInlineTableBody tr")).to_have_count(2)

    # Select vendor 2 in Row 2 -> verify savings badge
    row2 = page.locator("#b1ManualInlineTableBody tr").nth(1)
    row2.locator(".manual-row-vendor").select_option(v2_id)
    expect(row2.locator(".manual-row-routing")).to_contain_text("026013356")
    expect(row2.locator(".manual-row-account")).to_contain_text("555666777888")
    expect(row2.locator(".manual-row-type")).to_contain_text("savings", ignore_case=True)

    # Remove Row 2
    row2.locator("button.btn-danger").click()
    expect(page.locator("#b1ManualInlineTableBody tr")).to_have_count(1)
    # Row 1 values preserved
    expect(row1.locator(".manual-row-vendor")).to_have_value(v1_id)


def test_batch_validate_button_summary_and_non_blocking(page: Page, base_url: str):
    """Verify Validate Batch button shows inline summary bar without locking or disabling inputs."""
    _setup_authenticated_session(page, base_url)

    v_id = _create_test_vendor(page, base_url, f"Val Vendor {uuid.uuid4().hex[:4]}", "021000021", "998877665544", "checking")

    # Switch Batch 1 to Manual Payment Entry
    page.click("#batch1TabManualBtn")
    expect(page.locator("#batch1ManualPanel")).to_be_visible()

    # Step 1: Click Validate on Batch 1 with incomplete row
    page.click("#validateB1ManualBtn")
    expect(page.locator("#b1ManualValidateSummary")).to_be_visible()
    expect(page.locator("#b1ManualStatTotalRows")).to_have_text("1")
    expect(page.locator("#b1ManualStatValidRows")).to_have_text("0")
    expect(page.locator("#b1ManualStatErrorRows")).to_have_text("1")
    expect(page.locator("#b1ManualFormError")).to_be_visible()

    # Step 2: Verify inputs are NOT locked/disabled
    b1_row = page.locator("#b1ManualInlineTableBody tr").first
    expect(b1_row.locator(".manual-row-vendor")).to_be_enabled()
    expect(b1_row.locator(".manual-row-amount")).to_be_enabled()
    expect(b1_row.locator(".manual-row-ref")).to_be_enabled()

    # Step 3: Fill in row and re-validate
    b1_row.locator(".manual-row-vendor").select_option(v_id)
    b1_row.locator(".manual-row-amount").fill("1500.50")
    b1_row.locator(".manual-row-ref").fill("INV-B1-001")
    page.fill("#b1ManualEffDate", "2026-08-30")

    page.click("#validateB1ManualBtn")
    expect(page.locator("#b1ManualValidateSummary")).to_be_visible()
    expect(page.locator("#b1ManualStatTotalRows")).to_have_text("1")
    expect(page.locator("#b1ManualStatValidRows")).to_have_text("1")
    expect(page.locator("#b1ManualStatErrorRows")).to_have_text("0")
    expect(page.locator("#b1ManualStatTotalAmount")).to_contain_text("1,500.50")
    expect(page.locator("#b1ManualFormError")).to_be_hidden()

    # Step 4: Validate Batch 2
    page.fill("#manualEffDate", "2026-08-30")
    b2_row = page.locator("#manualInlineTableBody tr").first
    b2_row.locator(".manual-row-vendor").select_option(v_id)
    b2_row.locator(".manual-row-amount").fill("2500.00")
    b2_row.locator(".manual-row-ref").fill("INV-B2-001")

    page.click("#validateBatch2Btn")
    expect(page.locator("#batch2ValidateSummary")).to_be_visible()
    expect(page.locator("#batch2StatTotalRows")).to_have_text("1")
    expect(page.locator("#batch2StatValidRows")).to_have_text("1")
    expect(page.locator("#batch2StatErrorRows")).to_have_text("0")
    expect(page.locator("#batch2StatTotalAmount")).to_contain_text("2,500.00")


def test_dynamic_batch3_validate_and_combined_nacha(page: Page, base_url: str):
    """Verify dynamic Batch 3 has Validate button, and combined NACHA generation works with Batch 1 Manual + Batch 2 + Batch 3."""
    _setup_authenticated_session(page, base_url)

    v1_id = _create_test_vendor(page, base_url, f"Combined V1 {uuid.uuid4().hex[:4]}", "021000021", "111122223333", "checking")
    v2_id = _create_test_vendor(page, base_url, f"Combined V2 {uuid.uuid4().hex[:4]}", "026013356", "444455556666", "checking")

    # Batch 1 (Manual Mode)
    page.click("#batch1TabManualBtn")
    page.fill("#b1ManualEffDate", "2026-08-30")
    b1_row = page.locator("#b1ManualInlineTableBody tr").first
    b1_row.locator(".manual-row-vendor").select_option(v1_id)
    b1_row.locator(".manual-row-amount").fill("1000.00")
    b1_row.locator(".manual-row-ref").fill("REF-B1")

    # Batch 2
    page.fill("#manualEffDate", "2026-08-30")
    b2_row = page.locator("#manualInlineTableBody tr").first
    b2_row.locator(".manual-row-vendor").select_option(v2_id)
    b2_row.locator(".manual-row-amount").fill("2000.00")
    b2_row.locator(".manual-row-ref").fill("REF-B2")

    # Add dynamic Batch 3
    page.click("#addBatchBtn")
    expect(page.locator("#card_batch_3")).to_be_visible()

    # Fill Batch 3
    page.fill("#manualEffDate_3", "2026-08-30")
    b3_row = page.locator("#manualInlineTableBody_3 tr").first
    b3_row.locator(".manual-row-vendor").select_option(v1_id)
    b3_row.locator(".manual-row-amount").fill("3000.00")
    b3_row.locator(".manual-row-ref").fill("REF-B3")

    # Validate Batch 3
    page.locator("#card_batch_3 button:has-text('Validate Batch')").click()
    expect(page.locator("#batch3ValidateSummary")).to_be_visible()
    expect(page.locator("#batch3StatTotalRows")).to_have_text("1")
    expect(page.locator("#batch3StatValidRows")).to_have_text("1")
    expect(page.locator("#batch3StatTotalAmount")).to_contain_text("3,000.00")

    # Generate Combined NACHA File (Batch 1 Manual + Batch 2 + Batch 3 = $6,000.00)
    page.click("#generateNachaBtn")

    expect(page.locator("#nachaOutputCard")).to_be_visible(timeout=15000)
    expect(page.locator("#nachaEntryCount")).to_have_text("3")
    expect(page.locator("#nachaBatchCount")).to_have_text("3")
    expect(page.locator("#nachaCreditTotal")).to_contain_text("6,000.00")
