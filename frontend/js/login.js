/**
 * AMIPI NACHA ACH Payment System — Login Screen Controller
 *
 * Handles login form submission, registration toggle,
 * password visibility, validation, and role-aware redirect.
 */

const LoginScreen = (() => {
  // ── DOM refs ───────────────────────────────────────────────
  function el(id) { return document.getElementById(id); }

  // ── Initialise ─────────────────────────────────────────────
  function init() {
    // If already authenticated, skip login
    if (API.isAuthenticated()) {
      hideLoginScreen();
      initApp();
      return;
    }

    showLoginScreen();
    bindEvents();
  }

  function showLoginScreen() {
    el('loginScreen').style.display = 'flex';
    el('appShell').style.display = 'none';
    // Focus username field
    setTimeout(() => {
      const usernameInput = el('loginUsername');
      if (usernameInput) usernameInput.focus();
    }, 100);
  }

  function hideLoginScreen() {
    el('loginScreen').style.display = 'none';
    el('appShell').style.display = 'block';
  }

  // ── Event binding ──────────────────────────────────────────
  function bindEvents() {
    // Login form submission
    el('loginForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      await handleLogin();
    });

    // SVG Eye icons for password toggle
    const EYE_ICON = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-eye"><path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/><circle cx="12" cy="12" r="3"/></svg>`;
    const EYE_OFF_ICON = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-eye-off"><path d="M10.733 5.076a10.744 10.744 0 0 1 11.205 6.575 1 1 0 0 1 0 .696 10.747 10.747 0 0 1-1.444 2.49"/><path d="M14.084 14.158a3 3 0 0 1-4.242-4.242"/><path d="M17.479 17.499a10.75 10.75 0 0 1-15.417-5.151 1 1 0 0 1 0-.696 10.75 10.75 0 0 1 4.446-5.143"/><path d="m2 2 20 20"/></svg>`;

    // Password visibility toggle
    el('togglePassword').addEventListener('click', () => {
      const pwInput = el('loginPassword');
      const isHidden = pwInput.type === 'password';
      pwInput.type = isHidden ? 'text' : 'password';
      el('togglePassword').innerHTML = isHidden ? EYE_OFF_ICON : EYE_ICON;
    });

    // Enter key in password field
    el('loginPassword').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        el('loginForm').requestSubmit();
      }
    });
  }

  // ── Login handler ──────────────────────────────────────────
  async function handleLogin() {
    clearErrors();
    const username = el('loginUsername').value.trim();
    const password = el('loginPassword').value;

    if (!username) return showError('Username is required');
    if (!password) return showError('Password is required');

    setLoading(true);

    try {
      const data = await API.login(username, password);
      hideLoginScreen();
      initApp();
    } catch (err) {
      showError(err.message || 'Login failed. Please check your credentials.');
    } finally {
      setLoading(false);
    }
  }

  // ── UI helpers ─────────────────────────────────────────────
  function showError(msg) {
    const errEl = el('loginError');
    errEl.textContent = msg;
    errEl.classList.add('show');
  }

  function clearErrors() {
    const errEl = el('loginError');
    errEl.textContent = '';
    errEl.classList.remove('show');
  }

  function setLoading(loading) {
    const btn = el('loginSubmitBtn');
    const spinner = el('loginSpinner');
    const btnText = el('loginBtnText');
    if (btn) btn.disabled = loading;
    if (spinner) spinner.style.display = loading ? 'inline-block' : 'none';
    if (btnText) btnText.style.opacity = loading ? '0.5' : '1';
  }

  // ── Post-login app init ────────────────────────────────────
  function initApp() {
    const user = API.getUser();
    if (!user) return;

    // Update header with user info
    const userInfo = el('headerUserInfo');
    if (userInfo) {
      const roleBadgeHtml = user.role === 'admin' 
        ? '<span class="user-role-badge" id="adminRoleBadge">Admin</span>' 
        : '<span class="user-role-badge" id="userRoleBadge">User</span>';
      userInfo.innerHTML = `
        ${roleBadgeHtml}
        <span style="font-size: var(--text-xs); opacity: 0.85">${escapeHtml(user.username)}</span>
      `;
    }

    // Toggle Admin Review Tab
    if (typeof AdminScreen !== 'undefined') {
      AdminScreen.checkAdminAccess();
    }

    // Show logout button
    const logoutBtn = el('logoutBtn');
    if (logoutBtn) {
      logoutBtn.style.display = 'inline-flex';
      logoutBtn.addEventListener('click', () => API.logout());
    }
  }

  return { init };
})();


// ── Bootstrap on DOM ready ─────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  LoginScreen.init();
});
