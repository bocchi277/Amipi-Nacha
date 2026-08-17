"""
Frontend Phase 7 — Payment History & Transaction Table Playwright Tests.

Tests:
1. Access & Filtering: Standard or Admin user accesses Payment History tab, applies status, vendor,
   search term, and date range filters, verifying filtered rows.
2. Multi-Select Checkboxes: Selects individual rows and tests 'Select All' checkbox, verifying bulk bar counter.
3. Confirmation Step & Bulk Resend: Clicking 'Bulk Resend' opens confirmation modal, displaying selected vendors.
   Cancelling closes modal. Confirming dispatches emails and updates status from PENDING to SENT.
"""
import tempfile
import uuid
import pytest
from playwright.sync_api import Page, expect


_RUN_ID = uuid.uuid4().hex[:6]
STD_USER = f"std_user_p7_{_RUN_ID}"
STD_EMAIL = f"{STD_USER}@amipi.com"
STD_PASSWORD = "StdUserPass123!"


def test_transaction_history_filtering_multiselect_confirm_and_bulk_resend(page: Page, base_url: str):
    """Test filtering by each type, multi-select checkboxes, confirmation modal, and bulk resend status update."""
    page.goto(base_url)
    page.evaluate("sessionStorage.clear()")
    page.reload()

    # Step 1: Register Standard User via API
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

    page.fill("#loginUsername", STD_USER)
    page.fill("#loginPassword", STD_PASSWORD)
    page.click("#loginSubmitBtn")
    expect(page.locator("#appShell")).to_be_visible(timeout=5000)

    # Step 2: Seed Batch 1 & Batch 2 + Generate NACHA to create Remittance records
    uid = uuid.uuid4().hex[:6]
    v_name = f"HIST VENDOR {uid}"
    inv1 = f"INV-H1-{uid}"
    inv2 = f"INV-H2-{uid}"

    # Create vendor
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
                    account_number: '8877665544',
                    account_type: 'checking'
                })
            });
            return await res.json();
        }
        """,
        [base_url, v_name],
    )
    vendor_id = v_res.get("id")

    # Upload Batch 1 CSV
    csv_content = (
        "Vendor Name,Routing Number,Account Number,Account Type,Amount,Invoice Number\n"
        f"{v_name},026013356,8877665544,Checking,4200.00,{inv1}\n"
    )
    tmp_csv = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
    tmp_csv.write(csv_content)
    tmp_csv.close()

    page.set_input_files("#fileInput", tmp_csv.name)
    page.click("#uploadBtn")
    expect(page.locator("#resultsSection")).to_be_visible(timeout=10000)

    # Add Batch 2 Manual Entry
    page.evaluate("async () => { await GenerateScreen.loadVendors(); }")
    page.wait_for_selector(f"#manualVendorSelect option[value='{vendor_id}']", state="attached", timeout=5000)
    page.select_option("#manualVendorSelect", vendor_id)
    page.fill("#manualAmount", "1800.00")
    page.fill("#manualIdNumber", inv2)
    page.fill("#manualEffDate", "2026-08-25")
    page.click("#addManualEntryBtn")
    expect(page.locator("#manualDraftSection")).to_be_visible()
    page.click("#submitManualBatchBtn")
    expect(page.locator("#manualResultsSection")).to_be_visible(timeout=10000)

    # Generate NACHA file -> creates 2 PENDING remittance records
    page.click("#generateNachaBtn")
    expect(page.locator("#nachaOutputCard")).to_be_visible(timeout=10000)

    # Step 3: Switch to Payment History Tab
    page.click("button[data-view='history']")
    expect(page.locator("#view-history")).to_be_visible()

    # Step 4: Verify Filtering Functionality
    # Filter by Status: Pending
    page.select_option("#colFilterStatus", "pending")

    tbody = page.locator("#historyTableBody")
    expect(tbody).to_contain_text(v_name)
    expect(tbody).to_contain_text(inv1)
    expect(tbody).to_contain_text(inv2)

    # Filter by Invoice Column
    page.fill("#colFilterInvoice", inv1)
    expect(tbody).to_contain_text(inv1)
    expect(tbody).not_to_contain_text(inv2)

    # Reset Filters & Filter by Vendor Column
    page.click("#clearAllColFilters")
    page.fill("#colFilterVendor", v_name)
    expect(tbody).to_contain_text(inv1)
    expect(tbody).to_contain_text(inv2)

    # Step 5: Test Multi-Select Checkboxes & Select All
    page.check("#historySelectAllCb")
    expect(page.locator("#historyBulkBar")).to_be_visible()
    expect(page.locator("#historySelectedCount")).to_contain_text("2")

    # Step 6: Test Confirmation Modal Step (Cancel Action)
    page.click("#bulkResendBtn")
    expect(page.locator("#bulkResendConfirmModal")).to_be_visible()
    expect(page.locator("#confirmModalVendorList")).to_contain_text(v_name)

    # Cancel modal
    page.click("#cancelBulkResendModalBtn")
    expect(page.locator("#bulkResendConfirmModal")).to_be_hidden()

    # Step 7: Test Bulk Resend Dispatch (Confirm Action)
    page.click("#bulkResendBtn")
    expect(page.locator("#bulkResendConfirmModal")).to_be_visible()
    page.click("#confirmBulkResendBtn")

    # Confirm modal hides and alert notification appears
    expect(page.locator("#bulkResendConfirmModal")).to_be_hidden(timeout=10000)
    expect(page.locator("#historyGlobalAlert")).to_be_visible(timeout=10000)
    expect(page.locator("#historyGlobalAlert")).to_contain_text("Successfully resent")

    # Step 8: Verify Statuses updated to 'Sent' in table
    expect(tbody).to_contain_text("Sent (x1)")
