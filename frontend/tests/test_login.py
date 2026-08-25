"""
Frontend Phase 1 — Login Screen Playwright Tests.

Tests:
1. Login screen renders correctly on page load.
2. Failed login shows error message.
3. Successful login transitions to app shell with correct role badge.
4. Admin login shows admin badge.
5. Password visibility toggle.
6. Register mode toggle shows correct UI.
7. Session persistence — refresh after login stays authenticated.
8. Logout returns to login screen.
9. Tab navigation works after login.
"""
import uuid
import pytest
from playwright.sync_api import Page, expect


# Unique test user credentials (per test run to avoid collisions)
_RUN_ID = uuid.uuid4().hex[:6]
TEST_USER = f"user_{_RUN_ID}"
TEST_EMAIL = f"{TEST_USER}@amipi.com"
TEST_PASSWORD = "TestPass123!"

ADMIN_USER = f"admin_{_RUN_ID}"
ADMIN_EMAIL = f"{ADMIN_USER}@amipi.com"
ADMIN_PASSWORD = "AdminPass123!"

REG_USER = f"reg_{_RUN_ID}"
REG_EMAIL = f"{REG_USER}@amipi.com"
REG_PASSWORD = "RegPass123!"


def _api_register(page: Page, base_url: str, email: str, username: str, password: str, role: str = "user"):
    """Register a user via direct API call (not through UI)."""
    result = page.evaluate(
        """
        async ([url, email, username, password, role]) => {
            try {
                const res = await fetch(url + '/api/v1/auth/register', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email, username, password, role })
                });
                const data = await res.json();
                return { ok: res.ok, status: res.status, data };
            } catch (e) {
                return { ok: false, error: e.message };
            }
        }
        """,
        [base_url, email, username, password, role],
    )
    return result


def _login_via_ui(page: Page, username: str, password: str):
    """Fill login form and submit."""
    page.fill("#loginUsername", username)
    page.fill("#loginPassword", password)
    page.click("#loginSubmitBtn")


def _fresh_login_page(page: Page, base_url: str):
    """Navigate to base URL with cleared session."""
    page.goto(base_url)
    page.evaluate("sessionStorage.clear()")
    page.reload()
    page.wait_for_load_state("networkidle")


# ── TESTS ─────────────────────────────────────────────────────────


def test_login_screen_renders(page: Page, base_url: str):
    """Login screen renders on first visit with all expected elements and no public register button."""
    _fresh_login_page(page, base_url)

    expect(page.locator("#loginScreen")).to_be_visible()
    expect(page.locator("#appShell")).to_be_hidden()
    expect(page.locator("#loginFormTitle")).to_contain_text("AMIPI INC")
    expect(page.locator("#loginUsername")).to_be_visible()
    expect(page.locator("#loginPassword")).to_be_visible()
    expect(page.locator("#loginSubmitBtn")).to_be_visible()
    # Public self-registration elements are completely removed
    expect(page.locator("#modeToggleBtn")).to_have_count(0)
    expect(page.locator("#emailGroup")).to_have_count(0)


def test_failed_login_shows_error(page: Page, base_url: str):
    """Incorrect credentials show an error message, login screen stays visible."""
    _fresh_login_page(page, base_url)

    _login_via_ui(page, "nonexistent_user_xyz", "wrong_password")

    error_el = page.locator("#loginError")
    expect(error_el).to_be_visible(timeout=5000)
    expect(error_el).to_contain_text("Incorrect")
    expect(page.locator("#loginScreen")).to_be_visible()


def test_successful_login_standard_user(page: Page, base_url: str):
    """Standard user login transitions to app shell with User role badge."""
    # Register user via API first
    _fresh_login_page(page, base_url)
    _api_register(page, base_url, TEST_EMAIL, TEST_USER, TEST_PASSWORD, "user")

    # Clear session and reload
    _fresh_login_page(page, base_url)

    # Login via UI
    _login_via_ui(page, TEST_USER, TEST_PASSWORD)

    # Should transition to app shell
    expect(page.locator("#appShell")).to_be_visible(timeout=5000)
    expect(page.locator("#loginScreen")).to_be_hidden()

    # Header shows User role badge
    header_info = page.locator("#headerUserInfo")
    expect(header_info).to_contain_text("User")
    expect(header_info).to_contain_text(TEST_USER)


def test_admin_login_shows_admin_badge(page: Page, base_url: str):
    """Admin user login shows admin badge in header."""
    _fresh_login_page(page, base_url)
    _api_register(page, base_url, ADMIN_EMAIL, ADMIN_USER, ADMIN_PASSWORD, "admin")

    _fresh_login_page(page, base_url)

    _login_via_ui(page, ADMIN_USER, ADMIN_PASSWORD)

    expect(page.locator("#appShell")).to_be_visible(timeout=5000)
    header_info = page.locator("#headerUserInfo")
    expect(header_info).to_contain_text("Admin")
    expect(header_info).to_contain_text(ADMIN_USER)


def test_password_visibility_toggle(page: Page, base_url: str):
    """Password field toggles between hidden and visible."""
    _fresh_login_page(page, base_url)

    pw_input = page.locator("#loginPassword")
    toggle_btn = page.locator("#togglePassword")

    expect(pw_input).to_have_attribute("type", "password")

    toggle_btn.click()
    expect(pw_input).to_have_attribute("type", "text")

    toggle_btn.click()
    expect(pw_input).to_have_attribute("type", "password")


def test_no_public_registration_on_login_screen(page: Page, base_url: str):
    """Verify that public self-registration is absent and only login is available."""
    _fresh_login_page(page, base_url)

    expect(page.locator("#loginScreen")).to_be_visible()
    expect(page.locator("#modeToggleBtn")).to_have_count(0)
    expect(page.locator("#emailGroup")).to_have_count(0)
    expect(page.locator("#loginSubmitBtn")).to_contain_text("Sign In")


def test_session_persistence_after_refresh(page: Page, base_url: str):
    """Authenticated session persists after page refresh."""
    _fresh_login_page(page, base_url)

    _login_via_ui(page, TEST_USER, TEST_PASSWORD)
    expect(page.locator("#appShell")).to_be_visible(timeout=5000)

    # Refresh page
    page.reload()
    page.wait_for_load_state("networkidle")

    # Should still be on app shell
    expect(page.locator("#appShell")).to_be_visible(timeout=3000)
    expect(page.locator("#loginScreen")).to_be_hidden()


def test_logout_returns_to_login(page: Page, base_url: str):
    """Clicking logout returns to login screen."""
    _fresh_login_page(page, base_url)

    _login_via_ui(page, TEST_USER, TEST_PASSWORD)
    expect(page.locator("#appShell")).to_be_visible(timeout=5000)

    # Click logout (triggers page reload)
    page.click("#logoutBtn")

    expect(page.locator("#loginScreen")).to_be_visible(timeout=5000)


def test_tab_navigation_after_login(page: Page, base_url: str):
    """Tab navigation works correctly in the authenticated app shell."""
    _fresh_login_page(page, base_url)

    _login_via_ui(page, TEST_USER, TEST_PASSWORD)
    expect(page.locator("#appShell")).to_be_visible(timeout=5000)

    # Initially on Generate tab
    expect(page.locator("#view-generate")).to_be_visible()
    expect(page.locator("#view-vendors")).to_be_hidden()

    # Click Vendor Book tab
    page.click('[data-view="vendors"]')
    expect(page.locator("#view-vendors")).to_be_visible()
    expect(page.locator("#view-generate")).to_be_hidden()

    # Click History tab
    page.click('[data-view="history"]')
    expect(page.locator("#view-history")).to_be_visible()
    expect(page.locator("#view-vendors")).to_be_hidden()

    # Click back to Generate
    page.click('[data-view="generate"]')
    expect(page.locator("#view-generate")).to_be_visible()
