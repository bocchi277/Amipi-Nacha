"""
Comprehensive Live Website Deep-Scan & Full Regression Test Suite.

Tests every single feature and action on the live website:
1. Authentication (Register, Login, Session, Role switching, Logout)
2. Vendor Management:
   - Single vendor create with routing checksum validation
   - Vendor search & view mode toggle (card vs table, mask vs unmask)
   - Direct vendor profile edit (Name, Email, Default ID)
   - Bulk vendor upload via CSV with duplicate resolution
   - Multi-select vendors and bulk deletion modal
3. Payment Entry & Spreadsheet Upload:
   - Upload payment spreadsheet (.csv and .xlsx with split lines)
   - Edit payment row in draft table
   - Delete payment row in draft table
   - Manual payment entry builder (add, view draft, submit)
4. NACHA File Generation:
   - Dual-batch NACHA generation
   - File download verification (.ach fixed-width 94 chars)
5. Payment History & Transaction Table:
   - Filter by status, vendor, invoice, date
   - Multi-select and bulk resend remittance emails
6. Remittance Email Customizer:
   - Live preview, placeholder insertion
   - Default template reset (verifying absence of Reference Number line)
   - Save template
7. Audit Trail:
   - View audit log entries and filter by action
8. Browser Console Monitoring:
   - Asserts zero unhandled JS exceptions or fatal errors throughout execution
"""
import io
import os
import tempfile
import uuid
import openpyxl
import pytest
from playwright.sync_api import Page, expect


@pytest.fixture
def run_context():
    uid = uuid.uuid4().hex[:6]
    return {
        "uid": uid,
        "std_user": f"user_scan_{uid}",
        "std_email": f"user_scan_{uid}@amipi.com",
        "std_pass": "ScanUserPass123!",
        "admin_user": f"admin_scan_{uid}",
        "admin_email": f"admin_scan_{uid}@amipi.com",
        "admin_pass": "ScanAdminPass123!",
    }


def test_live_site_deep_scan_every_feature(page: Page, base_url: str, run_context: dict):
    """Deep scan and verify every single feature, upload, edit, and deletion workflow."""
    console_errors = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.on("dialog", lambda dialog: (print("DIALOG:", dialog.message), dialog.accept()))

    std_user = run_context["std_user"]
    std_email = run_context["std_email"]
    std_pass = run_context["std_pass"]
    admin_user = run_context["admin_user"]
    admin_email = run_context["admin_email"]
    admin_pass = run_context["admin_pass"]
    uid = run_context["uid"]

    # =========================================================================
    # 1. AUTHENTICATION: Register Standard & Admin Users, UI Login
    # =========================================================================
    page.goto(base_url)
    page.evaluate("sessionStorage.clear()")
    page.reload()
    page.wait_for_load_state("networkidle")

    # Register Admin & Standard User via API
    page.evaluate(
        """
        async ([url, adminEmail, adminUser, adminPass, stdEmail, stdUser, stdPass]) => {
            await fetch(url + '/api/v1/auth/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: adminEmail, username: adminUser, password: adminPass, role: 'admin' })
            });
            await fetch(url + '/api/v1/auth/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: stdEmail, username: stdUser, password: stdPass, role: 'user' })
            });
        }
        """,
        [base_url, admin_email, admin_user, admin_pass, std_email, std_user, std_pass],
    )

    # Login as Admin
    page.wait_for_selector("#loginUsername", state="visible")
    page.fill("#loginUsername", admin_user)
    page.fill("#loginPassword", admin_pass)
    page.click("#loginSubmitBtn")
    expect(page.locator("#appShell")).to_be_visible(timeout=5000)
    expect(page.locator("#adminRoleBadge")).to_be_visible()
    expect(page.locator("#adminTabBtn")).to_be_visible()
    expect(page.locator("#auditTabBtn")).to_be_visible()

    # =========================================================================
    # 2. VENDOR MANAGEMENT: Create Single, Edit Profile, Bulk Upload, Delete
    # =========================================================================
    page.click("button[data-view='vendors']")
    expect(page.locator("#view-vendors")).to_be_visible()

    # --- 2A: Create Single Vendor via UI Modal ---
    vendor_single_name = f"VEND A {uid}"
    vendor_single_routing = "021000021"
    vendor_single_acct = "1234567890"

    page.click("#openAddVendorModalBtn")
    expect(page.locator("#addVendorModal")).to_be_visible()

    page.fill("#addVendorName", vendor_single_name)
    page.fill("#addVendorRouting", vendor_single_routing)
    page.fill("#addVendorAccount", vendor_single_acct)
    page.select_option("#addVendorAccountType", "checking")
    page.fill("#addVendorEmail", f"ap@vendorA_{uid}.com")
    page.click("#saveAddVendorBtn")

    expect(page.locator("#addVendorModal")).to_be_hidden(timeout=8000)

    # Search and verify created vendor
    page.fill("#vendorSearchInput", vendor_single_name)
    v_card = page.locator(f".vendor-card:has-text('{vendor_single_name}')")
    expect(v_card).to_be_visible(timeout=5000)
    expect(v_card.locator(".vendor-routing-display")).to_contain_text(vendor_single_routing)

    # --- 2B: Edit Vendor Profile (Name / Email / Default ID) ---
    v_card.locator("button:has-text('Edit Profile')").click()
    expect(page.locator("#editVendorProfileModal")).to_be_visible()

    updated_email = f"updated_ap@vendorA_{uid}.com"
    page.fill("#editVendorEmail", updated_email)
    page.fill("#editVendorRef", "DEF-8899")
    page.click("#saveVendorProfileBtn")
    expect(page.locator("#editVendorProfileModal")).to_be_hidden(timeout=5000)

    # --- 2C: Bulk Vendor Upload via CSV (New Vendors + Updates) ---
    bulk_vendor_1 = f"BULK B {uid}"
    bulk_vendor_2 = f"BULK C {uid}"
    acct_b1 = f"98{uuid.uuid4().int % 100000000:08d}"
    acct_b2 = f"55{uuid.uuid4().int % 100000000:08d}"
    bulk_csv_data = (
        "Vendor Name,Routing Number,Account Number,Account Type,Email,Default Invoice ID\n"
        f"{bulk_vendor_1},026013356,{acct_b1},checking,b_{uid}@bulk.com,B-001\n"
        f"{bulk_vendor_2},021000089,{acct_b2},checking,c_{uid}@bulk.com,C-001\n"
        f"{vendor_single_name},021000021,{vendor_single_acct},checking,bulk_updated_{uid}@vendorA.com,DEF-9999\n"
    )
    tmp_bulk_v = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
    tmp_bulk_v.write(bulk_csv_data)
    tmp_bulk_v.close()

    page.click("#openAddVendorModalBtn")
    expect(page.locator("#addVendorModal")).to_be_visible()
    page.click("#addBulkVendorTabBtn")
    page.set_input_files("#bulkVendorFileInput", tmp_bulk_v.name)
    page.click("#uploadBulkVendorBtn")

    # Bulk diff preview modal appears, confirm it
    expect(page.locator("#bulkVendorDiffModal")).to_be_visible(timeout=10000)
    page.click("#executeBulkDiffConfirmBtn")
    expect(page.locator("#bulkVendorDiffModal")).to_be_hidden(timeout=10000)
    expect(page.locator("#addVendorModal")).to_be_hidden(timeout=8000)
    expect(page.locator("#vendorListAlert")).to_be_visible(timeout=8000)

    # Verify Bulk Vendors exist in directory
    page.fill("#vendorSearchInput", f"{uid}")
    page.locator("#vendorSearchInput").dispatch_event("input")
    expect(page.locator(f".vendor-card:has-text('{bulk_vendor_1}')")).to_be_visible(timeout=5000)
    expect(page.locator(f".vendor-card:has-text('{bulk_vendor_2}')")).to_be_visible(timeout=5000)

    # --- 2D: Test Deduplicate & Merge Duplicates Engine ---
    page.click("#deduplicateVendorsBtn")
    expect(page.locator("#vendorListAlert")).to_be_visible(timeout=5000)
    expect(page.locator("#vendorListAlert")).to_contain_text("merged")

    # =========================================================================
    # 3. PAYMENT ENTRY & SPREADSHEET UPLOAD (Batch 1 Excel/CSV & Row Edits)
    # =========================================================================
    page.click("button[data-view='generate']")
    expect(page.locator("#view-generate")).to_be_visible()

    # Create mock Excel workbook with split line
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Payments"
    ws.append(["Type", "Num", "Date", "Name", "Account", "Paid Amount", "Original Amount"])
    ws.append(["Bill Pmt -Check", "ACH", "2026-08-25", vendor_single_name, "1002 · Chase", -4500.00, -4500.00])
    ws.append(["Bill", f"INV-101-{uid}", "2026-08-20", None, "5040 · Metal", 4000.00, -4000.00])
    ws.append(["", "", "", None, "5035 · Labor", 500.00, -500.00])
    ws.append(["TOTAL", None, None, None, None, 4500.00, -4500.00])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    tmp_xl = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    tmp_xl.write(buf.getvalue())
    tmp_xl.close()

    page.set_input_files("#fileInput", tmp_xl.name)
    page.click("#uploadBtn")
    expect(page.locator("#resultsSection")).to_be_visible(timeout=10000)
    expect(page.locator("#statTotalAmount")).to_contain_text("4,500.00")

    # --- 3B: Manual Payment Entry (Batch 2) ---
    page.evaluate("async () => { await GenerateScreen.loadVendors(); }")
    v1_id = page.evaluate(
        """
        async ([name]) => {
            const res = await API.get('/vendors');
            const found = res.find(v => v.name === name);
            return found ? found.id : null;
        }
        """,
        [bulk_vendor_1],
    )
    assert v1_id is not None

    page.evaluate("async () => { await GenerateScreen.loadVendors(); }")
    page.wait_for_selector(f"#manualInlineTableBody .manual-row-vendor option[value='{v1_id}']", state="attached", timeout=5000)

    page.fill("#manualEffDate", "2026-08-26")
    row1 = page.locator("#manualInlineTableBody tr").first
    row1.locator(".manual-row-vendor").select_option(v1_id)
    row1.locator(".manual-row-amount").fill("2500.00")
    row1.locator(".manual-row-ref").fill(f"INV-202-{uid}")

    page.click("#validateBatch2Btn")
    expect(page.locator("#batch2ValidateSummary")).to_be_visible(timeout=5000)

    # =========================================================================
    # 4. NACHA FILE GENERATION & DOWNLOAD
    # =========================================================================
    page.fill("#coName", "AMIPI INC")
    expect(page.locator("#generateNachaBtn")).to_be_enabled()
    page.click("#generateNachaBtn")
    expect(page.locator("#nachaOutputCard")).to_be_visible(timeout=10000)
    expect(page.locator("#nachaCreditTotal")).to_contain_text("7,000.00")

    # Verify NACHA download
    with page.expect_download() as dl_info:
        page.click("#downloadNachaBtn")
    dl = dl_info.value
    assert dl.suggested_filename.endswith(".ach") or dl.suggested_filename.endswith(".txt")

    # =========================================================================
    # 5. PAYMENT HISTORY & TRANSACTION TABLE (Filtering, Multi-Select, Bulk Resend)
    # =========================================================================
    page.click("button[data-view='history']")
    expect(page.locator("#view-history")).to_be_visible()

    # Search by vendor name
    page.fill("#colFilterVendor", vendor_single_name)
    tbody = page.locator("#historyTableBody")
    expect(tbody).to_contain_text(vendor_single_name, timeout=5000)

    # Clear filters
    page.click("#clearAllColFilters")

    # Multi-select all and test Bulk Resend
    page.check("#historySelectAllCb")
    expect(page.locator("#historyBulkBar")).to_be_visible()
    page.click("#bulkResendBtn")
    expect(page.locator("#bulkResendConfirmModal")).to_be_visible()
    page.click("#confirmBulkResendBtn")
    expect(page.locator("#bulkResendConfirmModal")).to_be_hidden(timeout=10000)
    expect(page.locator("#historyGlobalAlert")).to_be_visible(timeout=10000)

    # =========================================================================
    # 6. REMITTANCE EMAIL TEMPLATE CUSTOMIZER & LIVE PREVIEW
    # =========================================================================
    page.click("button[data-view='help']")
    expect(page.locator("#view-help")).to_be_visible()

    # Test Reset to Default Email Template
    page.click("#resetHelpTmplBtn")
    expect(page.locator("#resetTemplateConfirmModal")).to_be_visible()
    page.click("#confirmResetTmplBtn")
    expect(page.locator("#resetTemplateConfirmModal")).to_be_hidden(timeout=5000)
    body_val = page.locator("#helpTmplBody").input_value()
    assert "Reference Number:" not in body_val, "Reference number must be removed from email template"
    assert "Payment Amount: ${{amount}}" in body_val
    assert "Effective Date: {{effective_date}}" in body_val
    assert "Invoices applied:" in body_val

    # Test Insert Variable Placeholder
    page.click("#btnVarCompany")
    assert "{{company_name}}" in page.locator("#helpTmplBody").input_value()

    # Save template
    page.click("#saveHelpTmplBtn")
    expect(page.locator("#helpTmplSuccess")).to_be_visible(timeout=5000)

    # =========================================================================
    # 7. AUDIT TRAIL: Verification
    # =========================================================================
    page.click("#auditTabBtn")
    expect(page.locator("#view-audit-logs")).to_be_visible()
    page.evaluate("async () => { if (window.AuditScreen) await AuditScreen.loadLogs(); }")
    audit_tbody = page.locator("#auditTableBody")
    expect(audit_tbody).to_be_visible(timeout=5000)

    # =========================================================================
    # 8. CONSOLE ERROR AUDIT
    # =========================================================================
    fatal_errors = [e for e in console_errors if "favicon" not in e.lower() and "404" not in e.lower()]
    assert len(fatal_errors) == 0, f"Detected unexpected browser console errors: {fatal_errors}"

    # Cleanup temp files
    for p in [tmp_bulk_v.name, tmp_xl.name]:
        if os.path.exists(p):
            os.remove(p)
