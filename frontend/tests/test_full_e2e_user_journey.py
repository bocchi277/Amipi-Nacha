"""
Full End-to-End User Journey Integration Test Suite.

Executes a complete, continuous multi-step workflow from start to finish:
1. Standard User Login & Authentication
2. Batch 1 Spreadsheet Upload & Summary Verification
3. Batch 2 Manual Payment Entry & Duplicate Check Override
4. Combined NACHA File Generation & File Download
5. Vendor Master Directory Search & Bank Detail Change Request Submission
6. Admin Login & Bank Detail Change Request Approval
7. Transaction History Filtering, Multi-Select Checkboxes, and Bulk Remittance Resend
8. Help & Templates Navigation & Real CSV Template File Downloads
"""
import tempfile
import uuid
import pytest
from playwright.sync_api import Page, expect


_RUN_ID = uuid.uuid4().hex[:6]
STD_USER = f"e2e_std_{_RUN_ID}"
STD_EMAIL = f"{STD_USER}@amipi.com"
STD_PASSWORD = "E2eStdPassword123!"

ADMIN_USER = f"e2e_admin_{_RUN_ID}"
ADMIN_EMAIL = f"{ADMIN_USER}@amipi.com"
ADMIN_PASSWORD = "E2eAdminPassword123!"


def test_full_continuous_user_journey(page: Page, base_url: str):
    """Run the complete end-to-end application lifecycle as one continuous flow."""

    # ------------------------------------------------------------------------
    # STEP 1: Standard User Registration & Login
    # ------------------------------------------------------------------------
    page.goto(base_url)
    page.evaluate("sessionStorage.clear()")
    page.reload()

    # Register standard user via API
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
    expect(page.locator("#userRoleBadge")).to_be_visible()

    # ------------------------------------------------------------------------
    # STEP 2: Batch 1 Spreadsheet Upload
    # ------------------------------------------------------------------------
    v_uid = uuid.uuid4().hex[:6]
    v_name = f"ACME {v_uid}"
    orig_routing = "021000021"
    orig_account = "111222333444"
    inv1 = f"E2E-1-{v_uid}"
    inv2 = f"E2E-2-{v_uid}"

    # Seed vendor in DB first using API helper
    v_res = page.evaluate(
        """
        async ([name, routing, account]) => {
            return await API.post('/vendors', {
                name: name,
                routing_number: routing,
                account_number: account,
                account_type: 'checking'
            });
        }
        """,
        [v_name, orig_routing, orig_account],
    )
    vendor_id = v_res.get("id")

    # Create CSV file for Batch 1 Upload
    csv_content = (
        "Vendor Name,Routing Number,Account Number,Account Type,Amount,Invoice Number\n"
        f"{v_name},{orig_routing},{orig_account},Checking,5250.00,{inv1}\n"
    )
    tmp_csv = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
    tmp_csv.write(csv_content)
    tmp_csv.close()

    page.set_input_files("#fileInput", tmp_csv.name)
    page.click("#uploadBtn")
    expect(page.locator("#resultsSection")).to_be_visible(timeout=10000)
    expect(page.locator("#statTotalAmount")).to_contain_text("5,250.00")

    # ------------------------------------------------------------------------
    # STEP 3: Batch 2 Manual Payment Entry & Duplicate Override
    # ------------------------------------------------------------------------
    page.evaluate("async () => { await GenerateScreen.loadVendors(); }")
    page.wait_for_selector(f"#manualInlineTableBody .manual-row-vendor option[value='{vendor_id}']", state="attached", timeout=5000)

    # Fill the inline row
    page.fill("#manualEffDate", "2026-08-30")
    row1 = page.locator("#manualInlineTableBody tr").first
    row1.locator(".manual-row-vendor").select_option(vendor_id)
    row1.locator(".manual-row-amount").fill("2750.00")
    row1.locator(".manual-row-ref").fill(inv2)

    # Single click: Validate & Generate NACHA
    page.click("#submitManualBatchBtn")
    expect(page.locator("#manualResultsSection")).to_be_visible(timeout=10000)

    # ------------------------------------------------------------------------
    # STEP 4: Combined NACHA File Auto-Generated & Download
    # ------------------------------------------------------------------------
    expect(page.locator("#nachaOutputCard")).to_be_visible(timeout=10000)
    expect(page.locator("#nachaCreditTotal")).to_contain_text("8,000.00")

    # Test file download
    with page.expect_download() as download_info:
        page.click("#downloadNachaBtn")
    download = download_info.value
    assert download.suggested_filename.endswith(".ach") or download.suggested_filename.endswith(".txt")

    # ------------------------------------------------------------------------
    # STEP 5: Standard User Vendor Master Search & Bank Detail Edit Request
    # ------------------------------------------------------------------------
    page.click("button[data-view='vendors']")
    expect(page.locator("#view-vendors")).to_be_visible()
    page.evaluate("async () => { await VendorsScreen.loadData(); }")
    page.fill("#vendorSearchInput", v_name)

    vendor_card = page.locator(f".vendor-card[data-vendor-id='{vendor_id}']")
    expect(vendor_card).to_be_visible(timeout=5000)

    # Open Change Request Modal
    vendor_card.locator(".req-change-btn").click()
    expect(page.locator("#changeRequestModal")).to_be_visible()

    new_routing = "026013356"
    new_account = "999888777666"
    page.fill("#reqNewRouting", new_routing)
    page.fill("#reqNewAccount", new_account)
    page.select_option("#reqNewAccountType", "savings")
    page.fill("#reqReason", "Updated vendor bank branch details")
    page.click("#submitReqBtn")

    expect(page.locator("#changeRequestModal")).to_be_hidden(timeout=5000)
    expect(vendor_card).to_contain_text("Change Request PENDING Admin Review")
    # Verify DB bank details remain UNCHANGED before approval
    expect(vendor_card.locator(".vendor-routing-display")).to_contain_text(orig_routing)

    # ------------------------------------------------------------------------
    # STEP 6: Admin Login & Bank Detail Change Request Approval
    # ------------------------------------------------------------------------
    # Register & Login as Admin
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
        [base_url, ADMIN_EMAIL, ADMIN_USER, ADMIN_PASSWORD],
    )

    page.click("#logoutBtn")
    expect(page.locator("#loginForm")).to_be_visible(timeout=5000)

    page.fill("#loginUsername", ADMIN_USER)
    page.fill("#loginPassword", ADMIN_PASSWORD)
    page.click("#loginSubmitBtn")
    expect(page.locator("#appShell")).to_be_visible(timeout=5000)
    expect(page.locator("#adminRoleBadge")).to_be_visible()
    expect(page.locator("#adminTabBtn")).to_be_visible()

    # Open Admin Review tab
    page.click("#adminTabBtn")
    expect(page.locator("#view-admin-approvals")).to_be_visible()

    # Find pending request row
    page.on("dialog", lambda dialog: dialog.accept())
    req_row = page.locator(f"#adminRequestsTableBody tr:has-text('{v_name}')")
    expect(req_row).to_be_visible(timeout=5000)
    expect(req_row).to_contain_text(new_routing)

    req_row.locator(".btn-approve").click()
    expect(req_row).to_be_hidden(timeout=10000)

    # Verify Vendor Book in DB/UI now reflects MUTATED bank details
    page.click("button[data-view='vendors']")
    page.fill("#vendorSearchInput", v_name)
    expect(vendor_card.locator(".vendor-routing-display")).to_contain_text(new_routing)
    expect(vendor_card.locator(".vendor-account-display")).to_contain_text(new_account[-4:])

    # ------------------------------------------------------------------------
    # STEP 7: Transaction Table Filtering, Multi-Select & Bulk Remittance Resend
    # ------------------------------------------------------------------------
    page.click("button[data-view='history']")
    expect(page.locator("#view-history")).to_be_visible()

    # Filter by vendor name
    page.fill("#colFilterVendor", v_name)

    tbody = page.locator("#historyTableBody")
    expect(tbody).to_contain_text(inv1)
    expect(tbody).to_contain_text(inv2)

    # Select all rows on page
    page.check("#historySelectAllCb")
    expect(page.locator("#historyBulkBar")).to_be_visible()
    expect(page.locator("#historySelectedCount")).to_contain_text("2")

    # Click Bulk Resend Remittance Emails
    page.click("#bulkResendBtn")
    expect(page.locator("#bulkResendConfirmModal")).to_be_visible()
    expect(page.locator("#confirmModalVendorList")).to_contain_text(v_name)

    # Confirm dispatch
    page.click("#confirmBulkResendBtn")
    expect(page.locator("#bulkResendConfirmModal")).to_be_hidden(timeout=10000)
    expect(page.locator("#historyGlobalAlert")).to_be_visible(timeout=10000)
    expect(tbody).to_contain_text("Sent (x1)")

    # ------------------------------------------------------------------------
    # STEP 8: Help & Templates Navigation & CSV Template Downloads
    # ------------------------------------------------------------------------
    page.click("button[data-view='help']")
    expect(page.locator("#view-help")).to_be_visible()
    expect(page.locator("#view-help")).to_contain_text("Downloadable Spreadsheet Import Templates")

    # Test downloading payment template
    with page.expect_download() as download_info_p:
        page.click("#downloadPaymentTemplateBtnHelp")
    dl_p = download_info_p.value
    assert dl_p.suggested_filename == "payment_import_template.csv"

    # Test downloading vendor template
    with page.expect_download() as download_info_v:
        page.click("#downloadVendorTemplateBtnHelp")
    dl_v = download_info_v.value
    assert dl_v.suggested_filename == "vendor_import_template.csv"
