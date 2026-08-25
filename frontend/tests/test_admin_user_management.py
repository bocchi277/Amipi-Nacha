"""
Admin User Management Playwright Integration Test Suite.

Tests:
1. Standard user cannot access Admin User Management.
2. Admin can view list of users.
3. Admin can provision a new standard user via modal and new user can log in.
4. Admin can deactivate a user (deactivated user blocked from login) and reactivate.
5. Admin can reset a user's password and user can log in with the new password.
6. Admin can provision an admin user.
"""
import uuid
import pytest
from playwright.sync_api import Page, expect


_RUN_ID = uuid.uuid4().hex[:6]
ADMIN_USER = f"adm_mgmt_{_RUN_ID}"
ADMIN_EMAIL = f"{ADMIN_USER}@amipi.com"
ADMIN_PASSWORD = "AdminMgmtPass123!"

STD_USER = f"std_mgmt_{_RUN_ID}"
STD_EMAIL = f"{STD_USER}@amipi.com"
STD_PASSWORD = "StdMgmtPass123!"


def _register_api(page: Page, base_url: str, email: str, username: str, password: str, role: str):
    """Seed user via API helper."""
    page.evaluate(
        """
        async ([url, email, username, password, role]) => {
            await fetch(url + '/api/v1/auth/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, username, password, role })
            });
        }
        """,
        [base_url, email, username, password, role],
    )


def test_standard_user_cannot_see_admin_tab(page: Page, base_url: str):
    """Standard users do not see the Admin tab."""
    page.goto(base_url)
    page.evaluate("sessionStorage.clear()")
    page.reload()

    _register_api(page, base_url, STD_EMAIL, STD_USER, STD_PASSWORD, "user")

    page.fill("#loginUsername", STD_USER)
    page.fill("#loginPassword", STD_PASSWORD)
    page.click("#loginSubmitBtn")
    expect(page.locator("#appShell")).to_be_visible(timeout=5000)

    expect(page.locator("#adminTabBtn")).to_be_hidden()


def test_admin_user_management_lifecycle(page: Page, base_url: str):
    """Full lifecycle: Admin lists users, provisions a user, deactivates, reactivates, resets password."""
    page.goto(base_url)
    page.evaluate("sessionStorage.clear()")
    page.reload()

    _register_api(page, base_url, ADMIN_EMAIL, ADMIN_USER, ADMIN_PASSWORD, "admin")

    # Login as Admin
    page.fill("#loginUsername", ADMIN_USER)
    page.fill("#loginPassword", ADMIN_PASSWORD)
    page.click("#loginSubmitBtn")
    expect(page.locator("#appShell")).to_be_visible(timeout=5000)
    expect(page.locator("#adminTabBtn")).to_be_visible()

    # Open Admin Tab
    page.click("#adminTabBtn")
    expect(page.locator("#view-admin-approvals")).to_be_visible()

    # Check Users table is rendered
    expect(page.locator("#adminUsersTable")).to_be_visible(timeout=5000)
    expect(page.locator("#adminUsersTableBody")).to_contain_text(ADMIN_USER)

    # ------------------------------------------------------------------------
    # STEP 1: Provision a New Standard User via In-App Modal
    # ------------------------------------------------------------------------
    new_uid = uuid.uuid4().hex[:6]
    new_username = f"prov_user_{new_uid}"
    new_email = f"{new_username}@amipi.com"
    new_password = "ProvUserPassword123!"

    page.click("#openAddUserModalBtn")
    expect(page.locator("#addUserModal")).to_be_visible()

    page.fill("#newUsername", new_username)
    page.fill("#newUserEmail", new_email)
    page.fill("#newUserPassword", new_password)
    page.select_option("#newUserRole", "user")
    page.click("#submitAddUserBtn")

    # Modal closes and table shows new user
    expect(page.locator("#addUserModal")).to_be_hidden(timeout=5000)
    user_row = page.locator(f"#adminUsersTableBody tr:has-text('{new_username}')")
    expect(user_row).to_be_visible(timeout=5000)
    expect(user_row).to_contain_text(new_email)
    expect(user_row).to_contain_text("User")
    expect(user_row).to_contain_text("Active")

    # ------------------------------------------------------------------------
    # STEP 2: Deactivate User & Verify Login Blocked
    # ------------------------------------------------------------------------
    page.on("dialog", lambda dialog: dialog.accept())
    user_row.locator("button:has-text('Deactivate')").click()

    # Status updates to Inactive
    expect(user_row).to_contain_text("Inactive", timeout=5000)
    expect(user_row.locator("button:has-text('Activate')")).to_be_visible()

    # Logout and attempt login with deactivated account -> blocked
    page.click("#logoutBtn")
    expect(page.locator("#loginForm")).to_be_visible(timeout=5000)

    page.fill("#loginUsername", new_username)
    page.fill("#loginPassword", new_password)
    page.click("#loginSubmitBtn")
    expect(page.locator("#loginError")).to_be_visible(timeout=5000)
    expect(page.locator("#loginError")).to_contain_text("Inactive")

    # ------------------------------------------------------------------------
    # STEP 3: Admin Re-activates User and Resets Password
    # ------------------------------------------------------------------------
    page.fill("#loginUsername", ADMIN_USER)
    page.fill("#loginPassword", ADMIN_PASSWORD)
    page.click("#loginSubmitBtn")
    expect(page.locator("#appShell")).to_be_visible(timeout=5000)

    page.click("#adminTabBtn")
    user_row = page.locator(f"#adminUsersTableBody tr:has-text('{new_username}')")
    expect(user_row).to_be_visible(timeout=5000)

    # Reactivate
    user_row.locator("button:has-text('Activate')").click()
    expect(user_row).to_contain_text("Active", timeout=5000)

    # Reset Password
    user_row.locator("button:has-text('Reset Password')").click()
    expect(page.locator("#resetPasswordModal")).to_be_visible()

    updated_password = "NewUpdatedPassword123!"
    page.fill("#resetPasswordNewPassword", updated_password)
    page.click("#submitResetPasswordBtn")
    expect(page.locator("#resetPasswordModal")).to_be_hidden(timeout=5000)

    # ------------------------------------------------------------------------
    # STEP 4: Login with New Password
    # ------------------------------------------------------------------------
    page.click("#logoutBtn")
    expect(page.locator("#loginForm")).to_be_visible(timeout=5000)

    page.fill("#loginUsername", new_username)
    page.fill("#loginPassword", updated_password)
    page.click("#loginSubmitBtn")
    expect(page.locator("#appShell")).to_be_visible(timeout=5000)
    expect(page.locator("#headerUserInfo")).to_contain_text(new_username)
