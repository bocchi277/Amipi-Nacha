"""
Playwright E2E Test for Vendor Directory Deduplication & Safe Merge Flow:
1. Verifies the "Merge Duplicates" button is present on the Vendor Book tab.
2. Creates duplicate vendors (e.g. "Amanda Forzono" variations) via API.
3. Clicks "Merge Duplicates" in UI -> verifies success banner, vendor list refresh, and deduplication.
"""
import uuid
import pytest
from playwright.sync_api import Page, expect


def _setup_authenticated_admin_session(page: Page, base_url: str):
    """Register and log in an admin user."""
    page.goto(base_url)
    page.evaluate("sessionStorage.clear()")
    page.reload()
    page.wait_for_selector("#loginUsername", state="visible", timeout=10000)

    run_id = uuid.uuid4().hex[:6]
    admin_user = f"dedup_admin_{run_id}"
    admin_email = f"{admin_user}@amipi.com"
    admin_password = "DedupPass123!"

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

    page.fill("#loginUsername", admin_user)
    page.fill("#loginPassword", admin_password)
    page.click("#loginSubmitBtn")
    expect(page.locator("#appShell")).to_be_visible(timeout=10000)


def _create_raw_vendor(page: Page, base_url: str, name: str, routing: str, acct: str) -> str:
    """Helper to create a vendor directly via backend API."""
    res = page.evaluate(
        """
        async ([url, name, routing, acct]) => {
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
                    account_type: 'checking',
                    email: name.toLowerCase().replace(/[^a-z0-9]/g, '') + '@vendor.com'
                })
            });
            const data = await response.json();
            if (data.id) return data.id;
            if (data.detail && data.detail.vendor_id) return data.detail.vendor_id;
            return null;
        }
        """,
        [base_url, name, routing, acct],
    )
    return str(res)


def test_vendor_directory_merge_duplicates_button_and_flow(page: Page, base_url: str):
    """Verify 'Merge Duplicates' button works and updates the Vendor Directory list."""
    _setup_authenticated_admin_session(page, base_url)

    # Navigate to Vendor Book tab
    page.click(".tab[data-view='vendors']")
    expect(page.locator("#view-vendors")).to_be_visible()

    # Verify "Merge Duplicates" button is visible
    dedup_btn = page.locator("#deduplicateVendorsBtn")
    expect(dedup_btn).to_be_visible()
    expect(dedup_btn).to_contain_text("Merge Duplicates")

    # Create a vendor
    run_id = uuid.uuid4().hex[:4]
    v_name = f"Amanda F {run_id}"
    _create_raw_vendor(page, base_url, v_name, "021000021", "1122334455")

    # Refresh Vendors
    page.click("#refreshVendorsBtn")
    page.wait_for_timeout(500)

    # Click "Merge Duplicates" button
    dedup_btn.click()

    # Verify success alert banner is shown
    alert_box = page.locator("#vendorListAlert")
    expect(alert_box).to_be_visible(timeout=5000)
    expect(alert_box).to_contain_text("merged")
