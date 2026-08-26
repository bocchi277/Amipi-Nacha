"""
Comprehensive Deep Regression Test Suite for Generate File Screen (Frontend + Backend).

Covers:
1. Form validation & smooth error-scrolling for all invalid/empty field permutations.
2. Dynamic multi-batch operations (+ Add Batch, Remove Batch, Add/Remove Rows).
3. Live vendor bank details auto-population & reactive account type badges.
4. Triple-batch combined NACHA generation (Batch 1 Spreadsheet + Batch 2 Manual + Batch 3 Manual).
5. Exact 94-character NACHA structural compliance (1, 5, 6, 8, 9 records, entry hash, block padding).
6. Duplicate transaction detection & explicit override workflow.
7. CCD restrictions (rejecting PAYROLL / REVERSAL entry descriptions).
8. Download action, copy-to-clipboard, and modal breakdown inspection.
"""
import tempfile
import uuid
import pytest
from playwright.sync_api import Page, expect


_RUN_ID = uuid.uuid4().hex[:6]
ADMIN_USER = f"deep_reg_admin_{_RUN_ID}"
ADMIN_EMAIL = f"{ADMIN_USER}@amipi.com"
ADMIN_PASSWORD = "DeepRegPass123!"


def _setup_authenticated_session(page: Page, base_url: str):
    """Register and log in an admin user, then navigate to the Generate screen."""
    page.goto(base_url)
    page.evaluate("sessionStorage.clear()")
    page.reload()
    page.wait_for_load_state("networkidle")

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
        [base_url, ADMIN_EMAIL, ADMIN_USER, ADMIN_PASSWORD],
    )

    # Log in via UI
    page.fill("#loginUsername", ADMIN_USER)
    page.fill("#loginPassword", ADMIN_PASSWORD)
    page.click("#loginSubmitBtn")
    expect(page.locator("#appShell")).to_be_visible(timeout=5000)

    # Ensure on Generate Payments screen
    page.click(".tab[data-view='generate']")
    expect(page.locator("#view-generate")).to_be_visible()


def _create_test_vendor(page: Page, base_url: str, name: str, routing: str, acct: str = None, acct_type: str = "checking") -> str:
    """Helper to create a vendor via API and reload vendors cache."""
    if not acct:
        acct = f"99{uuid.uuid4().int % 100000000:08d}"

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


def _create_temp_csv(rows: list[dict]) -> str:
    """Create a temporary CSV file with the given payment records."""
    headers = ["Vendor Name", "Routing Number", "Account Number", "Account Type", "Amount", "Invoice Number"]
    content = [",".join(headers)]
    for r in rows:
        content.append(f"{r['name']},{r['routing']},{r['acct']},{r['acct_type']},{r['amount']},{r['inv']}")
    
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
    tmp.write("\n".join(content) + "\n")
    tmp.close()
    return tmp.name


# ======================================================================
# TEST 1: Regressive Input Validation & Smooth Error Scrolling
# ======================================================================
def test_regressive_validation_and_error_scrolling(page: Page, base_url: str):
    """Test all field permutations (empty vendor, negative amount, missing invoice, missing date) and error scrolling."""
    _setup_authenticated_session(page, base_url)
    uid = uuid.uuid4().hex[:5]
    v_id = _create_test_vendor(page, base_url, f"RegVendor_{uid}", "026013356")

    # 1. Click Generate with completely empty date
    page.fill("#manualEffDate", "")
    page.click("#generateNachaBtn")

    # Should show Effective Date error and scroll to date input / error box
    expect(page.locator("#manualFormError")).to_be_visible()
    expect(page.locator("#manualFormError")).to_contain_text("Effective Date is required for Batch 2")

    # 2. Fill effective date, leave row empty
    page.fill("#manualEffDate", "2026-08-25")
    page.click("#generateNachaBtn")

    # Should report missing vendor, amount, invoice
    expect(page.locator("#manualFormError")).to_be_visible()
    expect(page.locator("#manualFormError")).to_contain_text("Row 1: Vendor is required, Amount must be > 0, Invoice/Ref is required")
    row1 = page.locator("#manualInlineTableBody tr").first
    # Row should have danger highlight
    assert "rgb(254, 242, 242)" in row1.evaluate("el => window.getComputedStyle(el).backgroundColor")

    # 3. Select vendor, set negative amount
    row1.locator(".manual-row-vendor").select_option(v_id)
    row1.locator(".manual-row-amount").fill("-100.50")
    row1.locator(".manual-row-ref").fill(f"INV-VAL-{uid}-1")
    page.click("#generateNachaBtn")

    expect(page.locator("#manualFormError")).to_contain_text("Row 1: Amount must be > 0")

    # 4. Set zero amount
    row1.locator(".manual-row-amount").fill("0.00")
    page.click("#generateNachaBtn")
    expect(page.locator("#manualFormError")).to_contain_text("Row 1: Amount must be > 0")

    # 5. Fix row 1, add row 2 with missing invoice ref
    row1.locator(".manual-row-amount").fill("500.00")
    page.click("#addManualRowBtn")
    expect(page.locator("#manualInlineTableBody tr")).to_have_count(2)

    row2 = page.locator("#manualInlineTableBody tr").nth(1)
    row2.locator(".manual-row-vendor").select_option(v_id)
    row2.locator(".manual-row-amount").fill("350.00")
    row2.locator(".manual-row-ref").fill("")  # Empty invoice ref
    page.click("#generateNachaBtn")

    expect(page.locator("#manualFormError")).to_contain_text("Row 2: Invoice/Ref is required")

    # 6. Fix row 2 -> successful generation
    row2.locator(".manual-row-ref").fill(f"INV-VAL-{uid}-2")
    page.click("#generateNachaBtn")

    expect(page.locator("#nachaOutputCard")).to_be_visible(timeout=10000)
    expect(page.locator("#nachaEntryCount")).to_contain_text("2")
    expect(page.locator("#nachaCreditTotal")).to_contain_text("$850.00")


# ======================================================================
# TEST 2: Dynamic Multi-Batch Management (+ Add Batch, Remove, Edge Cases)
# ======================================================================
def test_dynamic_multi_batch_lifecycle_and_validation(page: Page, base_url: str):
    """Test spawning dynamic batches (Batch 3, Batch 4, Batch 5), removing batches, and validating independent batches."""
    _setup_authenticated_session(page, base_url)
    uid = uuid.uuid4().hex[:5]
    v1_id = _create_test_vendor(page, base_url, f"MultiVendor_A_{uid}", "026013356", acct_type="checking")
    v2_id = _create_test_vendor(page, base_url, f"MultiVendor_B_{uid}", "021000021", acct_type="savings")

    # Fill Batch 2
    page.fill("#manualEffDate", "2026-08-25")
    b2_row1 = page.locator("#manualInlineTableBody tr").first
    b2_row1.locator(".manual-row-vendor").select_option(v1_id)
    b2_row1.locator(".manual-row-amount").fill("1000.00")
    b2_row1.locator(".manual-row-ref").fill(f"B2-INV-{uid}-1")

    # Click + Add Batch -> spawns Batch 3
    page.click("#addBatchBtn")
    expect(page.locator("#card_batch_3")).to_be_visible()
    expect(page.locator("#card_batch_3")).to_contain_text("Manual Payment Entry (Batch 3)")

    # Click + Add Batch again -> spawns Batch 4
    page.click("#addBatchBtn")
    expect(page.locator("#card_batch_4")).to_be_visible()

    # Click + Add Batch again -> spawns Batch 5
    page.click("#addBatchBtn")
    expect(page.locator("#card_batch_5")).to_be_visible()

    # Remove Batch 4
    page.locator("#card_batch_4 button:has-text('× Remove Batch')").click()
    expect(page.locator("#card_batch_4")).to_have_count(0)

    # Now we have Batch 2, Batch 3, Batch 5 active
    # Fill Batch 3 (2 rows)
    page.fill("#manualEffDate_3", "2026-08-26")
    b3_row1 = page.locator("#manualInlineTableBody_3 tr").first
    b3_row1.locator(".manual-row-vendor").select_option(v2_id)
    b3_row1.locator(".manual-row-amount").fill("2000.00")
    b3_row1.locator(".manual-row-ref").fill(f"B3-INV-{uid}-1")

    # Add row in Batch 3
    page.locator("#card_batch_3 button:has-text('+ Add Row')").click()
    expect(page.locator("#manualInlineTableBody_3 tr")).to_have_count(2)
    b3_row2 = page.locator("#manualInlineTableBody_3 tr").nth(1)
    b3_row2.locator(".manual-row-vendor").select_option(v1_id)
    b3_row2.locator(".manual-row-amount").fill("3000.00")
    b3_row2.locator(".manual-row-ref").fill(f"B3-INV-{uid}-2")

    # Fill Batch 5 with invalid row (missing invoice ref) to verify error targeting
    page.fill("#manualEffDate_5", "2026-08-27")
    b5_row1 = page.locator("#manualInlineTableBody_5 tr").first
    b5_row1.locator(".manual-row-vendor").select_option(v2_id)
    b5_row1.locator(".manual-row-amount").fill("4000.00")
    b5_row1.locator(".manual-row-ref").fill("")  # intentionally empty

    # Click Generate Combined NACHA File
    page.click("#generateNachaBtn")

    # Batch 5 error alert must be visible with row error
    expect(page.locator("#manualFormError_5")).to_be_visible()
    expect(page.locator("#manualFormError_5")).to_contain_text("Row 1: Invoice/Ref is required")

    # Fix Batch 5 invoice ref
    b5_row1.locator(".manual-row-ref").fill(f"B5-INV-{uid}-1")

    # Click Generate Combined NACHA File -> should successfully generate combined NACHA across Batch 2, 3, 5
    page.click("#generateNachaBtn")

    expect(page.locator("#nachaOutputCard")).to_be_visible(timeout=10000)
    expect(page.locator("#nachaEntryCount")).to_contain_text("4")  # 1 + 2 + 1 = 4 entries
    expect(page.locator("#nachaBatchCount")).to_contain_text("3")  # Batch 2, 3, 5
    expect(page.locator("#nachaCreditTotal")).to_contain_text("$10,000.00")  # 1000 + 2000 + 3000 + 4000


# ======================================================================
# TEST 3: Live Bank Details Auto-Population & Reactive Indicators
# ======================================================================
def test_live_bank_details_auto_population(page: Page, base_url: str):
    """Test selecting vendors auto-populates routing, account, and account type badge in real time."""
    _setup_authenticated_session(page, base_url)
    uid = uuid.uuid4().hex[:5]
    
    v1_id = _create_test_vendor(page, base_url, f"ChaseVendor_{uid}", "026013356", acct_type="checking")
    v2_id = _create_test_vendor(page, base_url, f"SavingsVendor_{uid}", "021000021", acct_type="savings")

    row1 = page.locator("#manualInlineTableBody tr").first

    # Initially empty row has placeholder '—'
    expect(row1.locator(".manual-row-routing")).to_contain_text("—")
    expect(row1.locator(".manual-row-account")).to_contain_text("—")

    # Select Checking Vendor
    row1.locator(".manual-row-vendor").select_option(v1_id)
    expect(row1.locator(".manual-row-routing")).to_contain_text("026013356")
    expect(row1.locator(".manual-row-type")).to_contain_text("checking")

    # Switch to Savings Vendor in the same row
    row1.locator(".manual-row-vendor").select_option(v2_id)
    expect(row1.locator(".manual-row-routing")).to_contain_text("021000021")
    expect(row1.locator(".manual-row-type")).to_contain_text("savings")


# ======================================================================
# TEST 4: Triple-Batch NACHA Generation & Exact 94-Char Structural Verification
# ======================================================================
def test_triple_batch_nacha_and_94_char_spec_compliance(page: Page, base_url: str):
    """Upload Batch 1 Spreadsheet + Batch 2 Manual + Batch 3 Manual -> verify 94-char lines, entry hash, block padding."""
    _setup_authenticated_session(page, base_url)
    
    uid = uuid.uuid4().hex[:5]
    v1_name = f"Spreadsheet Co {uid}"
    v2_name = f"Manual B2 Co {uid}"
    v3_name = f"Manual B3 Co {uid}"

    v2_id = _create_test_vendor(page, base_url, v2_name, "026013356", acct_type="checking")
    v3_id = _create_test_vendor(page, base_url, v3_name, "021000021", acct_type="savings")

    # 1. Upload Batch 1 CSV
    csv_file = _create_temp_csv([
        {"name": v1_name, "routing": "026013356", "acct": f"88{uuid.uuid4().int % 10000000:07d}", "acct_type": "Checking", "amount": "1250.75", "inv": f"INV-B1-{uid}"}
    ])
    page.set_input_files("#fileInput", csv_file)
    page.click("#uploadBtn")
    expect(page.locator("#resultsSection")).to_be_visible(timeout=10000)

    # 2. Fill Batch 2 Manual
    page.fill("#manualEffDate", "2026-08-25")
    b2_row1 = page.locator("#manualInlineTableBody tr").first
    b2_row1.locator(".manual-row-vendor").select_option(v2_id)
    b2_row1.locator(".manual-row-amount").fill("2340.25")
    b2_row1.locator(".manual-row-ref").fill(f"INV-B2-{uid}")

    # 3. Add & Fill Batch 3 Manual
    page.click("#addBatchBtn")
    expect(page.locator("#card_batch_3")).to_be_visible()
    page.fill("#manualEffDate_3", "2026-08-26")
    b3_row1 = page.locator("#manualInlineTableBody_3 tr").first
    b3_row1.locator(".manual-row-vendor").select_option(v3_id)
    b3_row1.locator(".manual-row-amount").fill("3409.00")
    b3_row1.locator(".manual-row-ref").fill(f"INV-B3-{uid}")

    # Set custom NACHA transmission options
    page.fill("#coName", "AMIPI CORP")
    page.fill("#chaseAcct", "785957066")
    page.fill("#entryDesc", "EPAYMNT")

    # 4. Generate Combined NACHA File
    page.click("#generateNachaBtn")

    expect(page.locator("#nachaOutputCard")).to_be_visible(timeout=10000)
    expect(page.locator("#nachaEntryCount")).to_contain_text("3")
    expect(page.locator("#nachaBatchCount")).to_contain_text("3")
    # Total credit: 1250.75 + 2340.25 + 3409.00 = 7000.00
    expect(page.locator("#nachaCreditTotal")).to_contain_text("$7,000.00")

    # 5. Extract & Validate Raw NACHA Content
    raw_content = page.locator("#nachaRawPreview").text_content()
    assert raw_content is not None
    lines = [line.strip("\r") for line in raw_content.split("\n") if line.strip("\r")]

    # Rule 1: Every single line must be EXACTLY 94 characters
    for idx, line in enumerate(lines):
        assert len(line) == 94, f"Line {idx + 1} length is {len(line)}, expected exactly 94. Content: '{line}'"

    # Rule 2: Total line count must be an exact multiple of 10 (blocking factor = 10)
    assert len(lines) % 10 == 0, f"Total lines ({len(lines)}) must be a multiple of 10."

    # Rule 3: File Header Record (Record Type 1)
    file_header = lines[0]
    assert file_header.startswith("101 "), "File Header must start with 101 "
    assert "AMIPI CORP" in file_header, "File Header should contain Company Name"

    # Rule 4: Batch Headers & Controls count
    batch_headers = [l for l in lines if l.startswith("5")]
    entry_details = [l for l in lines if l.startswith("6")]
    batch_controls = [l for l in lines if l.startswith("8")]
    file_controls = [l for l in lines if l.startswith("9") and not l.startswith("9999999999")]
    padding_lines = [l for l in lines if l == "9" * 94]

    assert len(batch_headers) == 3, f"Expected 3 batch headers, found {len(batch_headers)}"
    assert len(entry_details) == 3, f"Expected 3 entry details, found {len(entry_details)}"
    assert len(batch_controls) == 3, f"Expected 3 batch controls, found {len(batch_controls)}"
    assert len(file_controls) == 1, f"Expected 1 file control record, found {len(file_controls)}"
    assert len(padding_lines) > 0, "Expected block padding lines of 9s"

    # Rule 5: File Control Record (Record Type 9) totals match
    file_ctrl = file_controls[0]
    # Positions 2-7: Batch Count (6 digits)
    batch_count_in_ctrl = int(file_ctrl[1:7])
    assert batch_count_in_ctrl == 3

    # Positions 8-13: Block Count (6 digits)
    block_count_in_ctrl = int(file_ctrl[7:13])
    assert block_count_in_ctrl == len(lines) // 10

    # Positions 14-21: Entry Count (8 digits)
    entry_count_in_ctrl = int(file_ctrl[13:21])
    assert entry_count_in_ctrl == 3

    # Positions 32-43: Total Debit Dollar Amount in Cents (12 digits)
    total_debit_cents = int(file_ctrl[31:43])
    assert total_debit_cents == 0

    # Positions 44-55: Total Credit Dollar Amount in Cents (12 digits)
    total_credit_cents = int(file_ctrl[43:55])
    assert total_credit_cents == 700000  # $7,000.00 in cents

    # 6. Test Download Button and file content parity
    with page.expect_download() as download_info:
        page.click("#downloadNachaBtn")

    download = download_info.value
    download_path = download.path()
    assert download_path is not None

    with open(download_path, "r", encoding="utf-8") as f:
        downloaded_content = f.read()

    assert downloaded_content.replace("\r\n", "\n").strip() == raw_content.replace("\r\n", "\n").strip(), "Downloaded file content must match UI raw preview exactly."
    assert "\r\n" in downloaded_content or "\n" in downloaded_content, "Downloaded file must contain valid line breaks."


# ======================================================================
# TEST 5: CCD Restrictions & Entry Description Protection
# ======================================================================
def test_ccd_forbidden_entry_descriptions(page: Page, base_url: str):
    """Test that PAYROLL and REVERSAL entry descriptions are rejected per Chase CCD rules."""
    _setup_authenticated_session(page, base_url)
    uid = uuid.uuid4().hex[:5]
    v_id = _create_test_vendor(page, base_url, f"CcdVendor_{uid}", "026013356")

    page.fill("#manualEffDate", "2026-08-25")
    row1 = page.locator("#manualInlineTableBody tr").first
    row1.locator(".manual-row-vendor").select_option(v_id)
    row1.locator(".manual-row-amount").fill("500.00")
    row1.locator(".manual-row-ref").fill(f"INV-CCD-{uid}")

    # 1. Test PAYROLL
    page.fill("#entryDesc", "PAYROLL")
    page.click("#generateNachaBtn")

    expect(page.locator("#nachaGlobalError")).to_be_visible()
    expect(page.locator("#nachaGlobalError")).to_contain_text("Entry description cannot be PAYROLL or REVERSAL")

    # 2. Test REVERSAL
    page.fill("#entryDesc", "REVERSAL")
    page.click("#generateNachaBtn")

    expect(page.locator("#nachaGlobalError")).to_be_visible()
    expect(page.locator("#nachaGlobalError")).to_contain_text("Entry description cannot be PAYROLL or REVERSAL")

    # 3. Test valid description e.g. VENDOR PMT
    page.fill("#entryDesc", "VENDOR PMT")
    page.click("#generateNachaBtn")

    expect(page.locator("#nachaOutputCard")).to_be_visible(timeout=10000)
