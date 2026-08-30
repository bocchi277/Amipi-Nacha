"""
Live browser verification against a locally served frontend + backend.

Confirms the UI still works after the security changes and that a stored XSS payload
in a vendor name is rendered inert. Requires the app to be running:

    uvicorn app.main:app --host 127.0.0.1 --port 8099

Run with:  pytest tests/test_live_ui_verification.py -v
Skipped automatically when the server is not reachable.
"""
import os

import httpx
import pytest
from playwright.sync_api import sync_playwright

BASE = os.getenv("AMIPI_UI_BASE_URL", "http://127.0.0.1:8099")
ADMIN_USER = os.getenv("AMIPI_UI_ADMIN", "uitest_admin")
ADMIN_PASS = os.getenv("AMIPI_UI_PASSWORD", "UiTestPass123!")


def _server_up() -> bool:
    try:
        return httpx.get(f"{BASE}/health", timeout=5).status_code in (200, 503)
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _server_up(), reason=f"App not reachable at {BASE}"
)


@pytest.fixture(scope="module")
def page_ctx():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        yield page, errors
        ctx.close()
        browser.close()


def _login(page):
    """Log in, or do nothing if this page is already authenticated."""
    if page.url.startswith(BASE) and page.locator("#appShell").count():
        if page.locator("#appShell").first.is_visible():
            return

    # The login screen is revealed by login.js after it runs, so wait for the network
    # to settle and for the field to actually become visible rather than merely exist.
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_selector("#loginUsername", state="visible", timeout=30000)
    page.fill("#loginUsername", ADMIN_USER)
    page.fill("#loginPassword", ADMIN_PASS)
    page.click("#loginSubmitBtn")
    page.wait_for_selector("#appShell", state="visible", timeout=30000)
    page.wait_for_load_state("networkidle")


def _significant(errors: list[str]) -> list[str]:
    """
    Filter out console noise that is not a regression.

    NOTE: the dashboard issues authenticated API calls on page load, before the user
    has signed in, which produces expected 401s in the console. That is pre-existing
    cosmetic behaviour (logged as a minor finding), not a fault introduced here.
    """
    ignorable = ("favicon", "401 (Unauthorized)", "Authentication token required")
    return [e for e in errors if not any(tok in e for tok in ignorable)]


def test_login_succeeds_and_dashboard_loads(page_ctx):
    page, errors = page_ctx
    _login(page)
    assert page.is_visible("#appShell")
    fatal = _significant(errors)
    assert not fatal, f"console errors on load: {fatal[:5]}"


def test_all_primary_views_render(page_ctx):
    """
    Every navigation tab must render its view without throwing.

    Admin-only tabs are hidden for standard users, so they are unhidden here to
    exercise them; the account under test is an administrator.
    """
    page, errors = page_ctx
    _login(page)
    before = len(errors)

    # Reveal admin-only tabs (they are display:none until the role is applied).
    page.evaluate(
        "() => document.querySelectorAll('#mainTabs .tab')"
        ".forEach(t => { t.style.display = ''; })"
    )

    tabs = page.locator("#mainTabs .tab")
    count = tabs.count()
    assert count >= 5, f"expected the main navigation tabs, found {count}"

    visited = []
    for i in range(count):
        tab = tabs.nth(i)
        view = tab.get_attribute("data-view")
        assert view, f"tab {i} has no data-view attribute"
        tab.click()
        page.wait_for_timeout(700)

        # The active view container must be the visible one.
        active = page.evaluate(
            "() => Array.from(document.querySelectorAll('[id^=\"view-\"]'))"
            ".filter(e => getComputedStyle(e).display !== 'none').map(e => e.id)"
        )
        assert active, f"no view visible after selecting {view!r}"
        visited.append((view, active))

    assert len(visited) == count, visited

    new_errors = _significant(errors[before:])
    assert not new_errors, f"console errors while navigating: {new_errors[:5]}"


def test_stored_xss_in_vendor_name_is_not_executed(page_ctx):
    """
    A vendor name is attacker-controlled and was interpolated straight into innerHTML.
    Create one containing a script payload and confirm it renders as inert text.
    """
    page, errors = page_ctx
    _login(page)

    token = page.evaluate("() => sessionStorage.getItem('amipi_token')")
    assert token, "expected a session token after login"

    payload_name = "<img src=x onerror=window.__xss=1>"
    with httpx.Client(base_url=BASE, timeout=30) as c:
        res = c.post(
            "/api/v1/vendors",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": payload_name,
                "routing_number": "021000021",
                "account_number": "192837465",
                "account_type": "checking",
            },
        )
        assert res.status_code in (201, 409), res.text

    # Render the vendor directory, which lists vendor names.
    page.locator('#mainTabs .tab[data-view="vendors"]').first.click()
    page.wait_for_timeout(2000)

    assert page.evaluate("() => window.__xss === undefined"), (
        "XSS payload EXECUTED: vendor name was not escaped"
    )
    # The payload must not have produced a real element.
    assert page.evaluate(
        "() => document.querySelectorAll('img[src=\"x\"]').length === 0"
    ), "payload created a live <img> element instead of being escaped"

    # And the name must be present as inert TEXT, proving it rendered escaped rather
    # than simply being absent (which would make this assertion vacuous).
    assert page.evaluate(
        "(needle) => document.body.innerText.includes(needle)",
        "<img src=x onerror=",
    ), "escaped payload text not found; the test did not actually render the vendor"


def test_security_headers_present_on_api_response():
    with httpx.Client(base_url=BASE, timeout=15) as c:
        r = c.get("/health")
        assert r.headers.get("x-content-type-options") == "nosniff"
        assert r.headers.get("x-frame-options") == "DENY"
        assert "content-security-policy" in r.headers
        assert r.headers.get("access-control-allow-origin") != "*"


def test_unauthenticated_api_access_is_refused():
    with httpx.Client(base_url=BASE, timeout=15) as c:
        for path in ["/api/v1/vendors", "/api/v1/nacha/latest"]:
            assert c.get(path).status_code == 401, f"{path} must require auth"
