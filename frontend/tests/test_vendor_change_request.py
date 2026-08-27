"""
Frontend Phase 5 — Vendor Book & Bank Change Request Playwright Tests.

Tests:
1. Standard non-admin user views vendor directory and submits a bank detail change request.
2. Asserts that the change request status appears as PENDING in the UI.
3. Asserts that the vendor's actual bank details remain UNCHANGED until an Admin approves it.
"""
import uuid
import pytest
from playwright.sync_api import Page, expect


def test_standard_user_bank_change_request_remains_pending(page: Page, base_url: str):
    """Test standard user submitting bank change request -> request shows PENDING, vendor bank details remain UNCHANGED."""
    run_id = uuid.uuid4().hex[:6]
    std_user = f"std_user_{run_id}"
    std_email = f"{std_user}@amipi.com"
    std_password = "StdUserPass123!"

    admin_user = f"admin_user_{run_id}"
    admin_email = f"{admin_user}@amipi.com"
    admin_password = "AdminUserPass123!"

    page.goto(base_url)
    page.evaluate("sessionStorage.clear()")
    page.reload()
    page.wait_for_load_state("networkidle")

    # Step 1: Create Admin user to seed vendor via API
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

    # Login as Admin temporarily via UI to create a vendor
    page.fill("#loginUsername", admin_user)
    page.fill("#loginPassword", admin_password)
    page.click("#loginSubmitBtn")
    expect(page.locator("#appShell")).to_be_visible(timeout=5000)

    v_uid = uuid.uuid4().hex[:6]
    v_name = f"ACME SUPPLIES {v_uid}"
    orig_routing = "026013356"
    orig_account = "111222333444"

    v_res = page.evaluate(
        """
        async ([url, name, routing, account]) => {
            const token = sessionStorage.getItem('amipi_token');
            const res = await fetch(url + '/api/v1/vendors', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + token
                },
                body: JSON.stringify({
                    name: name,
                    routing_number: routing,
                    account_number: account,
                    account_type: 'checking'
                })
            });
            return await res.json();
        }
        """,
        [base_url, v_name, orig_routing, orig_account],
    )
    vendor_id = v_res.get("id")
    assert vendor_id is not None

    # Step 2: Register & Log in as Standard User (non-admin)
    page.click("#logoutBtn")
    expect(page.locator("#loginScreen")).to_be_visible(timeout=5000)
    page.wait_for_load_state("networkidle")

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

    page.fill("#loginUsername", std_user)
    page.fill("#loginPassword", std_password)
    page.click("#loginSubmitBtn")
    expect(page.locator("#appShell")).to_be_visible(timeout=5000)
    expect(page.locator("#adminRoleBadge")).to_be_hidden()  # Confirm Standard User role

    # Step 3: Switch to Vendor Directory Tab
    page.click("button[data-view='vendors']")
    expect(page.locator("#view-vendors")).to_be_visible()

    # Search for our created vendor
    page.fill("#vendorSearchInput", v_name)
    vendor_card = page.locator(f".vendor-card[data-vendor-id='{vendor_id}']")
    expect(vendor_card).to_be_visible(timeout=5000)

    # Verify initial registered bank details
    expect(vendor_card.locator(".vendor-routing-display")).to_contain_text(orig_routing)
    expect(vendor_card.locator(".vendor-account-display")).to_contain_text(orig_account[-4:])

    # Step 4: Click 'Request Bank Change'
    vendor_card.locator(".req-change-btn").click()
    expect(page.locator("#changeRequestModal")).to_be_visible(timeout=5000)

    req_routing = "021000021"
    req_account = "999888777666"

    page.fill("#reqNewRouting", req_routing)
    page.fill("#reqNewAccount", req_account)
    page.select_option("#reqNewAccountType", "savings")
    page.fill("#reqReason", "Updated vendor bank branch details")
    page.click("#submitReqBtn")

    # Step 5: Verify change request success feedback & modal close
    expect(page.locator("#reqModalSuccess")).to_be_visible(timeout=5000)
    expect(page.locator("#reqModalSuccess")).to_contain_text("PENDING")

    expect(page.locator("#changeRequestModal")).to_be_hidden(timeout=10000)

    # Step 6: Verify Pending Request Banner appears on Vendor Card
    expect(vendor_card.locator(".alert-warning")).to_be_visible(timeout=5000)
    expect(vendor_card.locator(".alert-warning")).to_contain_text("PENDING")
    expect(vendor_card.locator(".alert-warning")).to_contain_text(req_routing)

    # Step 7: CRITICAL ASSERTION: Vendor's actual bank details remain UNCHANGED
    expect(vendor_card.locator(".vendor-routing-display")).to_contain_text(orig_routing)
    expect(vendor_card.locator(".vendor-account-display")).to_contain_text(orig_account[-4:])
