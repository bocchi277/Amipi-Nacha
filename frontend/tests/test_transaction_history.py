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


def test_transaction_history_filtering_multiselect_confirm_and_bulk_resend(page: Page, base_url: str):
    """Test filtering by each type, multi-select checkboxes, confirmation modal, and bulk resend status update."""
    run_id = uuid.uuid4().hex[:8]
    std_user = f"std_user_p7_{run_id}"
    std_email = f"{std_user}@amipi.com"
    std_password = "StdUserPass123!"

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
        [base_url, std_email, std_user, std_password],
    )

    page.wait_for_selector("#loginUsername", state="visible")
    page.fill("#loginUsername", std_user)
    page.fill("#loginPassword", std_password)
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
    page.wait_for_selector(f"#manualInlineTableBody .manual-row-vendor option[value='{vendor_id}']", state="attached", timeout=5000)
    page.fill("#manualEffDate", "2026-08-25")
    row1 = page.locator("#manualInlineTableBody tr").first
    row1.locator(".manual-row-vendor").select_option(vendor_id)
    row1.locator(".manual-row-amount").fill("1800.00")
    row1.locator(".manual-row-ref").fill(inv2)
    # Generate Combined NACHA File (validates Batch 2 and generates combined file)
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

    # Verify Sequence column displays 6-digit truncated format with full trace in title tooltip
    seq_badge = tbody.locator("tr").first.locator("td:nth-child(8) .badge")
    if seq_badge.count() > 0 and seq_badge.text_content():
        seq_text = seq_badge.text_content().strip()
        assert len(seq_text) <= 6, f"Sequence display length must be <= 6, got '{seq_text}'"
        assert seq_badge.get_attribute("title").startswith("Full Trace:"), "Tooltip must include full trace"

    # Filter by Sequence Column
    page.click("#clearAllColFilters")
    page.fill("#colFilterSequence", "000001")
    # Table should react without errors
    expect(tbody).to_be_visible()

    # Verify no horizontal scrollbar on standard desktop viewport (1600x900)
    page.set_viewport_size({"width": 1600, "height": 900})
    wrap_info = page.evaluate("""
        () => {
            const el = document.getElementById('historyTableWrap');
            return {
                scrollWidth: el.scrollWidth,
                clientWidth: el.clientWidth
            };
        }
    """)
    assert wrap_info['scrollWidth'] <= wrap_info['clientWidth'] + 2, f"Payment history table should fit without horizontal scroll on desktop: {wrap_info}"

    # Step 5: Test Multi-Select Checkboxes & Select All
    page.click("#clearAllColFilters")
    page.fill("#colFilterVendor", v_name)
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


def test_custom_email_template_sync_and_view_modal(page: Page, base_url: str):
    """Test that editing the email template reflects dynamically when viewing remittances in Payment History."""
    run_id = uuid.uuid4().hex[:8]
    adm_user = f"adm_tmpl_{run_id}"
    adm_email = f"{adm_user}@amipi.com"
    adm_password = "AdmUserPass123!"

    page.goto(base_url)
    page.evaluate("sessionStorage.clear()")
    page.reload()

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
        [base_url, adm_email, adm_user, adm_password],
    )

    page.wait_for_selector("#loginUsername", state="visible")
    page.fill("#loginUsername", adm_user)
    page.fill("#loginPassword", adm_password)
    page.click("#loginSubmitBtn")
    expect(page.locator("#appShell")).to_be_visible(timeout=5000)

    # 1. Verify container is standard width (not wide) on Generate File screen
    gen_is_wide = page.evaluate("() => document.querySelector('.main-container').classList.contains('wide-container')")
    assert not gen_is_wide, "Generate screen must not have wide-container class"

    # 2. Create vendor and generate a remittance
    v_name = f"TMPL VENDOR {run_id}"
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

    page.fill("#manualEffDate", "2026-08-30")
    page.evaluate("async () => { await GenerateScreen.loadVendors(); }")
    page.wait_for_selector(f"#manualInlineTableBody .manual-row-vendor option[value='{vendor_id}']", state="attached", timeout=5000)
    row = page.locator("#manualInlineTableBody tr").first
    row.locator(".manual-row-vendor").select_option(vendor_id)
    row.locator(".manual-row-amount").fill("5000.00")
    row.locator(".manual-row-ref").fill(f"INV-TMPL-{run_id}")
    page.click("#generateNachaBtn")
    expect(page.locator("#nachaOutputCard")).to_be_visible(timeout=10000)

    # 3. Switch to Payment History tab
    page.click("button[data-view='history']")
    expect(page.locator("#view-history")).to_be_visible()

    # Verify container has wide-container class on Payment History
    hist_is_wide = page.evaluate("() => document.querySelector('.main-container').classList.contains('wide-container')")
    assert hist_is_wide, "Payment history screen must have wide-container class"

    # Open Email Template modal and customize template
    page.click("#openEmailTemplateModalBtn")
    expect(page.locator("#emailTemplateModal")).to_be_visible()
    custom_text = f"CUSTOM SPECIAL GREETING {run_id}"
    page.fill("#tmplBodyInput", f"Dear {{{{vendor_name}}}},\n\n{custom_text}\nPayment Amount: ${{{{amount}}}}\nInvoices applied:\n\nThank you,\n{{{{company_name}}}}")
    page.click("#saveEmailTmplBtn")
    expect(page.locator("#emailTmplSuccess")).to_be_visible(timeout=5000)

    # Close modal
    page.click("#closeEmailTemplateModalBtn")
    expect(page.locator("#emailTemplateModal")).to_be_hidden()

    # 4. Click "View" on the transaction in Payment History
    page.fill("#colFilterVendor", v_name)
    row = page.locator("#historyTableBody tr").first
    row.locator("button:has-text('View')").click()

    # 5. Verify the rendered View Remittance Email Modal contains the updated customized template text!
    expect(page.locator("#viewRemittanceEmailModal")).to_be_visible()
    expect(page.locator("#viewEmailHtmlBody")).to_contain_text(custom_text)
    expect(page.locator("#viewEmailHtmlBody")).to_contain_text(v_name)
    expect(page.locator("#viewEmailHtmlBody")).to_contain_text("5,000.00")
