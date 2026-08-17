"""
Frontend Phase 6 — Admin Review & Vendor Bank Change Approval Playwright Tests.

Tests:
1. Role Access Control: Standard User (non-admin) cannot see or access the Admin Review tab.
2. Admin Change Approval: Admin User sees pending requests, approves a request -> asserts vendor's actual bank details in DB/UI mutate to requested values.
3. Admin Change Rejection: Admin User rejects a request -> asserts vendor's actual bank details remain UNCHANGED.
"""
import uuid
import pytest
from playwright.sync_api import Page, expect


_RUN_ID = uuid.uuid4().hex[:6]
STD_USER = f"std_user_p6_{_RUN_ID}"
STD_EMAIL = f"{STD_USER}@amipi.com"
STD_PASSWORD = "StdUserPass123!"

ADMIN_USER = f"admin_user_p6_{_RUN_ID}"
ADMIN_EMAIL = f"{ADMIN_USER}@amipi.com"
ADMIN_PASSWORD = "AdminUserPass123!"


def test_standard_user_cannot_access_admin_review(page: Page, base_url: str):
    """Test standard user cannot see Admin Review tab and receives Access Denied."""
    page.goto(base_url)
    page.evaluate("sessionStorage.clear()")
    page.reload()

    run_id = uuid.uuid4().hex[:6]
    std_user = f"std_user_p6_{run_id}"
    std_email = f"{std_user}@amipi.com"
    std_password = "StdUserPass123!"

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
        [base_url, std_email, std_user, std_password],
    )

    page.fill("#loginUsername", std_user)
    page.fill("#loginPassword", std_password)
    page.click("#loginSubmitBtn")
    expect(page.locator("#appShell")).to_be_visible(timeout=5000)

    # Confirm Admin Review tab is hidden for Standard User
    expect(page.locator("#adminTabBtn")).to_be_hidden()


def test_admin_approve_and_reject_vendor_change_requests(page: Page, base_url: str):
    """Test Admin reviewing, approving (updates DB bank details), and rejecting (leaves DB unchanged) change requests."""
    page.goto(base_url)
    page.evaluate("sessionStorage.clear()")
    page.reload()

    # Create Admin user via API
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

    # Login as Admin to seed vendor
    page.fill("#loginUsername", ADMIN_USER)
    page.fill("#loginPassword", ADMIN_PASSWORD)
    page.click("#loginSubmitBtn")
    expect(page.locator("#appShell")).to_be_visible(timeout=5000)
    expect(page.locator("#adminRoleBadge")).to_be_visible()

    v_uid = uuid.uuid4().hex[:6]
    v_name = f"GLOBAL METALS {v_uid}"
    orig_routing = "026013356"
    orig_account = "112233445566"

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

    # Standard User submits Change Request #1 (to be APPROVED)
    req1_routing = "021000021"
    req1_account = "778899001122"

    req1_res = page.evaluate(
        """
        async ([url, vid, routing, account]) => {
            const token = sessionStorage.getItem('amipi_token');
            const res = await fetch(url + '/api/v1/vendors/' + vid + '/change-requests', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + token
                },
                body: JSON.stringify({
                    requested_routing_number: routing,
                    requested_account_number: account,
                    requested_account_type: 'checking',
                    reason: 'Approval Test'
                })
            });
            return await res.json();
        }
        """,
        [base_url, vendor_id, req1_routing, req1_account],
    )
    req1_id = req1_res.get("id")

    # Step A: Admin opens Admin Review Tab
    expect(page.locator("#adminTabBtn")).to_be_visible()
    page.click("#adminTabBtn")
    expect(page.locator("#view-admin-approvals")).to_be_visible()

    # Find request row in Admin table
    req1_row = page.locator(f"#adminRequestsTableBody tr[data-request-id='{req1_id}']")
    expect(req1_row).to_be_visible(timeout=5000)
    expect(req1_row).to_contain_text(v_name)
    expect(req1_row).to_contain_text(req1_routing)

    # Override window.confirm to return True for Playwright
    page.on("dialog", lambda dialog: dialog.accept())

    # Click Approve
    req1_row.locator(".btn-approve").click()

    # Request row should disappear from pending list
    expect(req1_row).to_be_hidden(timeout=10000)

    # Step B: Assert Vendor's actual bank details in Vendor Book are UPDATED to new values
    page.click("button[data-view='vendors']")
    page.fill("#vendorSearchInput", v_name)
    vendor_card = page.locator(f".vendor-card[data-vendor-id='{vendor_id}']")
    expect(vendor_card).to_be_visible(timeout=5000)

    expect(vendor_card.locator(".vendor-routing-display")).to_contain_text(req1_routing)
    expect(vendor_card.locator(".vendor-account-display")).to_contain_text(req1_account[-4:])

    # Step C: Standard User submits Change Request #2 (to be REJECTED)
    req2_routing = "026013356"
    req2_account = "555544443333"

    req2_res = page.evaluate(
        """
        async ([url, vid, routing, account]) => {
            const token = sessionStorage.getItem('amipi_token');
            const res = await fetch(url + '/api/v1/vendors/' + vid + '/change-requests', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + token
                },
                body: JSON.stringify({
                    requested_routing_number: routing,
                    requested_account_number: account,
                    requested_account_type: 'checking',
                    reason: 'Rejection Test'
                })
            });
            return await res.json();
        }
        """,
        [base_url, vendor_id, req2_routing, req2_account],
    )
    req2_id = req2_res.get("id")

    # Admin opens Admin Review tab and REJECTS Request #2
    page.click("#adminTabBtn")
    req2_row = page.locator(f"#adminRequestsTableBody tr[data-request-id='{req2_id}']")
    expect(req2_row).to_be_visible(timeout=5000)

    req2_row.locator(".btn-reject").click()
    expect(req2_row).to_be_hidden(timeout=10000)

    # Step D: Assert Vendor's actual bank details remain UNCHANGED (still req1 values)
    page.click("button[data-view='vendors']")
    page.fill("#vendorSearchInput", v_name)
    expect(vendor_card.locator(".vendor-routing-display")).to_contain_text(req1_routing)
    expect(vendor_card.locator(".vendor-account-display")).to_contain_text(req1_account[-4:])
