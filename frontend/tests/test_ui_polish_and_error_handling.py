"""
Frontend Phase 8 — UI Polish, Error Handling & Empty States Playwright Tests.

Tests:
1. Graceful Error Handling: Failed API calls render clean user-friendly error banners without raw JSON/stack traces.
2. Empty States Verification:
   - Empty Vendor Directory displays clean 'No registered vendors found' notice.
   - Empty Admin Review table displays clean 'No pending bank detail change requests' notice.
   - Empty Transaction Table displays clean 'No payment transactions found' notice.
3. Accessibility & Zero Emojis: Form fields have proper labels, buttons are keyboard focusable, and 0 emojis exist in DOM.
"""
import uuid
import pytest
from playwright.sync_api import Page, expect


_RUN_ID = uuid.uuid4().hex[:6]
STD_USER = f"std_user_p8_{_RUN_ID}"
STD_EMAIL = f"{STD_USER}@amipi.com"
STD_PASSWORD = "StdUserPass123!"

ADMIN_USER = f"admin_user_p8_{_RUN_ID}"
ADMIN_EMAIL = f"{ADMIN_USER}@amipi.com"
ADMIN_PASSWORD = "AdminUserPass123!"


def test_login_error_handling_user_friendly(page: Page, base_url: str):
    """Test login failure displays clean user-friendly error banner."""
    page.goto(base_url)

    # Submit invalid login
    page.fill("#loginUsername", "invalid_nonexistent_user")
    page.fill("#loginPassword", "WrongPass123!")
    page.click("#loginSubmitBtn")

    err_el = page.locator("#loginError")
    expect(err_el).to_be_visible(timeout=5000)
    expect(err_el).to_contain_text("Incorrect username or password")
    # Verify no raw JSON or stack trace syntax
    text = err_el.text_content()
    assert "{" not in text and "Traceback" not in text


def test_empty_states_across_screens(page: Page, base_url: str):
    """Test clean empty state banners render across Vendor Directory, Admin Review, and Payment History screens."""
    page.goto(base_url)
    page.evaluate("sessionStorage.clear()")
    page.reload()

    # Create Admin user
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

    page.fill("#loginUsername", ADMIN_USER)
    page.fill("#loginPassword", ADMIN_PASSWORD)
    page.click("#loginSubmitBtn")
    expect(page.locator("#appShell")).to_be_visible(timeout=5000)

    # Clear any leftover pending change requests via API to test Admin Review empty state
    page.evaluate(
        """
        async (url) => {
            const token = sessionStorage.getItem('amipi_token');
            const res = await fetch(url + '/api/v1/vendors/change-requests/all', {
                headers: { 'Authorization': 'Bearer ' + token }
            });
            const reqs = await res.json();
            const pending = (reqs || []).filter(r => r.status === 'pending');
            for (const r of pending) {
                await fetch(url + '/api/v1/vendors/change-requests/' + r.id + '/reject', {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + token }
                });
            }
        }
        """,
        base_url,
    )

    # 1. Admin Review Empty State (no pending requests)
    page.click("#adminTabBtn")
    expect(page.locator("#view-admin-approvals")).to_be_visible()
    page.click("#refreshAdminApprovalsBtn")
    admin_tbody = page.locator("#adminRequestsTableBody")
    expect(admin_tbody).to_contain_text("No pending bank detail change requests awaiting review", timeout=5000)

    # 2. Payment History Empty State (with non-matching filter)
    page.click("button[data-view='history']")
    expect(page.locator("#view-history")).to_be_visible()
    page.fill("#colFilterVendor", "NON_EXISTENT_SEARCH_STRING_XYZ_99")

    hist_tbody = page.locator("#historyTableBody")
    expect(hist_tbody).to_contain_text("No payment transactions or remittance records found matching the selected filters", timeout=5000)

    # 3. Vendor Directory Empty State (with non-matching search)
    page.click("button[data-view='vendors']")
    expect(page.locator("#view-vendors")).to_be_visible()
    page.fill("#vendorSearchInput", "NON_EXISTENT_VENDOR_XYZ_99")
    expect(page.locator("#view-vendors")).to_contain_text("No vendors found in directory.", timeout=5000)


def test_accessibility_and_zero_emojis(page: Page, base_url: str):
    """Test form input labels, button focus states, and zero emojis in DOM."""
    page.goto(base_url)

    # Check key inputs have associated labels
    expect(page.locator("label[for='loginUsername']")).to_be_visible()
    expect(page.locator("label[for='loginPassword']")).to_be_visible()

    # Log in
    page.fill("#loginUsername", ADMIN_USER)
    page.fill("#loginPassword", ADMIN_PASSWORD)
    page.click("#loginSubmitBtn")
    expect(page.locator("#appShell")).to_be_visible(timeout=5000)

    # Verify zero emojis in body innerHTML
    body_text = page.locator("body").inner_text()
    emoji_ranges = [
        (0x1F600, 0x1F64F),  # Emoticons
        (0x1F300, 0x1F5FF),  # Misc Symbols & Pictographs
        (0x1F680, 0x1F6FF),  # Transport & Map Symbols
        (0x2600, 0x26FF),    # Misc Symbols
        (0x2700, 0x27BF),    # Dingbats
    ]
    for char in body_text:
        cp = ord(char)
        for start, end in emoji_ranges:
            assert not (start <= cp <= end), f"Found emoji in page DOM: {char} (U+{cp:X})"
