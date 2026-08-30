/**
 * AMIPI NACHA ACH Payment System — API Client
 *
 * Centralised HTTP helper for all backend communication.
 * Handles token storage, auth headers, and JSON parsing.
 */

const API = (() => {
  // Allowed backend origins. The API base URL was previously read from
  // `localStorage.amipi_api_url`, which let anyone with a moment at the keyboard --
  // or any XSS payload -- permanently repoint every request, including the login
  // POST, at a server they control and harvest credentials and bank data.
  // `window.AMIPI_API_URL` is still honoured (it can only be set by a script already
  // running on the page) but must resolve to a known origin.
  const ALLOWED_API_ORIGINS = [
    'https://amipi-nacha-backend.onrender.com',
    'http://localhost:8099',
    'http://127.0.0.1:8099',
    'http://localhost:8000',
    'http://127.0.0.1:8000',
  ];

  function getApiBaseUrl() {
    const override = window.AMIPI_API_URL;
    if (override) {
      const clean = String(override).replace(/\/+$/, '');
      let origin = null;
      try {
        origin = new URL(clean, window.location.href).origin;
      } catch (e) {
        origin = null;
      }
      if (origin && ALLOWED_API_ORIGINS.indexOf(origin) !== -1) {
        return clean.endsWith('/api/v1') ? clean : `${clean}/api/v1`;
      }
      console.warn('[AMIPI] Ignoring AMIPI_API_URL override: origin not allow-listed.');
    }

    // If running on localhost, 127.0.0.1, or same-origin host (such as cPanel / custom domain)
    const isLocalhost = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
    const isNetlify = window.location.hostname.includes('netlify.app');

    if (isLocalhost || (!isNetlify && window.location.protocol.startsWith('http') && !window.location.hostname.includes('render.com'))) {
      return '/api/v1';
    }
    // Production default live Render backend for Netlify static deployments
    return 'https://amipi-nacha-backend.onrender.com/api/v1';
  }

  function getBaseUrl() {
    return getApiBaseUrl();
  }

  function getToken() {
    return sessionStorage.getItem('amipi_token');
  }

  function setToken(token) {
    sessionStorage.setItem('amipi_token', token);
  }

  function clearToken() {
    sessionStorage.removeItem('amipi_token');
    sessionStorage.removeItem('amipi_user');
  }

  function getUser() {
    const raw = sessionStorage.getItem('amipi_user');
    return raw ? JSON.parse(raw) : null;
  }

  function setUser(user) {
    sessionStorage.setItem('amipi_user', JSON.stringify(user));
  }

  function isAuthenticated() {
    return !!getToken();
  }

  // ── HTTP helpers ───────────────────────────────────────────

  function authHeaders() {
    const token = getToken();
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    return headers;
  }

  async function request(method, path, { body, formData, query } = {}) {
    let url = `${getBaseUrl()}${path}`;

    if (query) {
      const params = new URLSearchParams();
      Object.entries(query).forEach(([k, v]) => {
        if (v !== undefined && v !== null && v !== '') params.append(k, v);
      });
      const qs = params.toString();
      if (qs) url += `?${qs}`;
    }

    const opts = { method };

    if (formData) {
      // Multipart form — don't set Content-Type, browser adds boundary
      const token = getToken();
      opts.headers = {};
      if (token) opts.headers['Authorization'] = `Bearer ${token}`;
      opts.body = formData;
    } else {
      opts.headers = authHeaders();
      if (body) opts.body = JSON.stringify(body);
    }

    let res;
    try {
      res = await fetch(url, opts);
    } catch (netErr) {
      // Previously every transport failure was reported as "Backend server is waking
      // up", which hid genuine problems (offline, DNS failure, CORS rejection) behind
      // a message telling the user to just wait and retry.
      throw new Error(
        navigator.onLine === false
          ? 'You appear to be offline. Check your connection and try again.'
          : 'Could not reach the API server. It may still be starting up, or the ' +
            'connection was blocked. Please retry in a few seconds.'
      );
    }


    // Parse response body
    let data;
    const contentType = res.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      data = await res.json();
    } else {
      data = await res.text();
    }

    if (!res.ok) {
      if (res.status === 401) {
        clearToken();
        // Reloading unconditionally could loop: the reloaded page re-requests, gets
        // another 401, and reloads again. Reload at most once, and never while
        // already on the login screen.
        const alreadyHandled = sessionStorage.getItem('amipi_401_handled') === '1';
        if (!path.includes('/auth/') && !alreadyHandled) {
          sessionStorage.setItem('amipi_401_handled', '1');
          window.location.reload();
        }
      } else if (res.status === 429) {
        // Surface throttling clearly rather than as a generic failure.
        const err429 = new Error(
          (data && data.detail) ||
          'Too many attempts. Please wait a moment before trying again.'
        );
        err429.status = 429;
        err429.data = data;
        throw err429;
      }
      let errMsg = `An error occurred (HTTP ${res.status}). Please try again.`;
      if (data) {
        if (typeof data.detail === 'string') {
          errMsg = data.detail;
        } else if (Array.isArray(data.detail)) {
          errMsg = data.detail.map(e => e.msg || e.detail || 'Validation error').join('; ');
        } else if (typeof data.detail === 'object' && data.detail && data.detail.message) {
          errMsg = data.detail.message;
        } else if (typeof data.message === 'string') {
          errMsg = data.message;
        }
      }
      const err = new Error(errMsg);
      err.status = res.status;
      err.data = data;
      throw err;
    }

    return data;
  }

  // ── Convenience methods ────────────────────────────────────

  function get(path, query)         { return request('GET', path, { query }); }
  function post(path, body)         { return request('POST', path, { body }); }
  function put(path, body)          { return request('PUT', path, { body }); }
  function patch(path, body)        { return request('PATCH', path, { body }); }
  function del(path)                { return request('DELETE', path); }
  function postForm(path, formData) { return request('POST', path, { formData }); }

  // ── Auth-specific calls ────────────────────────────────────

  async function login(username, password) {
    // OAuth2PasswordRequestForm expects form-urlencoded
    const formBody = new URLSearchParams();
    formBody.append('username', username);
    formBody.append('password', password);

    const res = await fetch(`${getBaseUrl()}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: formBody,
    });

    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.detail || 'Login failed');
    }

    setToken(data.access_token);
    setUser({
      username: data.username,
      role: data.role,
    });
    // Reset the one-shot 401 reload guard now that we hold a fresh token.
    sessionStorage.removeItem('amipi_401_handled');

    return data;
  }

  async function register(email, username, password, role = 'user') {
    const data = await post('/auth/register', { email, username, password, role });
    return data;
  }

  function logout() {
    clearToken();
    window.location.reload();
  }

  // ── Inactivity timeout ───────────────────────────────────────
  /*
   * Clear the session after a period of no interaction.
   *
   * The bearer token lives in sessionStorage, which any script on the page can read, and
   * a stateless JWT cannot be revoked server-side. Storage does survive until the tab is
   * closed, so a dashboard left open on an unattended machine keeps a usable token for
   * the life of the token.
   *
   * This bounds that exposure by the time the tab is actually idle rather than by how
   * long it stays open. It is a client-side control and no substitute for the token's own
   * expiry, which the server enforces; the two are complementary.
   */
  const IDLE_LIMIT_MS = 30 * 60 * 1000; // 30 minutes
  let idleTimer = null;

  function startIdleTimeout() {
    const reset = () => {
      if (idleTimer) clearTimeout(idleTimer);
      if (!isAuthenticated()) return;
      idleTimer = setTimeout(() => {
        if (!isAuthenticated()) return;
        clearToken();
        // Reload rather than only hiding the UI, so nothing rendered from the previous
        // session is left in the DOM.
        window.location.reload();
      }, IDLE_LIMIT_MS);
    };

    ['click', 'keydown', 'mousemove', 'scroll', 'touchstart', 'focus']
      .forEach(evt => document.addEventListener(evt, reset, { passive: true }));
    reset();
  }

  async function getProfile() {
    return get('/auth/me');
  }

  // ── User Management (Admin) ────────────────────────────────
  async function getUsers() {
    return get('/users');
  }

  async function createUser(email, username, password, role = 'user') {
    return post('/users', { email, username, password, role });
  }

  async function updateUserStatus(userId, isActive) {
    return put(`/users/${userId}/status`, { is_active: isActive });
  }

  async function resetUserPassword(userId, newPassword) {
    return post(`/users/${userId}/reset-password`, { new_password: newPassword });
  }

  // ── Public API ─────────────────────────────────────────────

  // ── Authentication lifecycle ─────────────────────────────────
  /*
   * Screen modules bind their DOM handlers at DOMContentLoaded, which happens while the
   * login screen is still up. Any data loading they did at the same moment fired
   * authenticated requests with no token, producing 401s in the console before the user
   * had done anything, and leaving the screen with no data if the response was ignored.
   *
   * The Generate screen also needed the banking calendar from the server to pre-fill
   * effective dates; fetching it pre-login meant it silently came back empty and the
   * date fields were left blank.
   */
  const AUTH_READY_EVENT = 'amipi:authenticated';

  /** Run `fn` once a session exists: immediately if one already does. */
  function onAuthenticated(fn) {
    if (isAuthenticated()) {
      fn();
      return;
    }
    document.addEventListener(AUTH_READY_EVENT, fn, { once: true });
  }

  /** Called by the login controller once a token is stored. */
  function notifyAuthenticated() {
    startIdleTimeout();
    document.dispatchEvent(new CustomEvent(AUTH_READY_EVENT));
  }

  return {
    // Token
    getToken, setToken, clearToken, getUser, setUser,
    isAuthenticated,
    // Lifecycle
    onAuthenticated, notifyAuthenticated, startIdleTimeout,
    // HTTP
    get, post, put, patch, del, postForm,
    // Auth
    login, register, logout, getProfile,
    // Users (Admin)
    getUsers, createUser, updateUserStatus, resetUserPassword,
  };
})();

// ── HTML escaping ────────────────────────────────────────────
/**
 * Escape a value for safe interpolation into an HTML template string.
 *
 * The dashboard builds markup with template literals and assigns it via innerHTML in
 * ~60 places, interpolating values that originate from the database (vendor names,
 * emails, usernames, change-request reasons, filenames). Those values are attacker
 * controllable -- a vendor named `<img src=x onerror=...>` executed script in every
 * view that listed it. No escaping helper existed at all before this.
 *
 * Use for TEXT interpolated into markup and for values placed inside quoted HTML
 * attributes. (`textContent` assignments are already safe and need no escaping.)
 */
window.escapeHtml = function (value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
};

/**
 * Escape a value for use inside a single-quoted inline event handler argument,
 * e.g. onclick="Foo.bar('${escapeJsAttr(name)}')".
 */
window.escapeJsAttr = function (value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/\\/g, '\\\\')
    .replace(/'/g, "\\'")
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\r?\n/g, ' ');
};

// ── Global Toast Notification System ─────────────────────────
window.showToast = function(message, type = 'info', duration = 3500) {
  const container = document.getElementById('amipiToastContainer');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast-item toast-${type}`;

  let iconSvg = '';
  if (type === 'success') {
    iconSvg = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>';
  } else if (type === 'error') {
    iconSvg = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>';
  } else if (type === 'warning') {
    iconSvg = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>';
  } else {
    iconSvg = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>';
  }

  toast.innerHTML = `
    <div style="display: flex; align-items: center; gap: 8px;">
      ${iconSvg}
      <span>${window.escapeHtml(message)}</span>
    </div>
    <button type="button" class="toast-close-btn" aria-label="Close notification">&times;</button>
  `;

  const closeBtn = toast.querySelector('.toast-close-btn');
  if (closeBtn) {
    closeBtn.addEventListener('click', () => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(30px) scale(0.95)';
      setTimeout(() => toast.remove(), 200);
    });
  }

  container.appendChild(toast);

  setTimeout(() => {
    if (toast.isConnected) {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(30px) scale(0.95)';
      setTimeout(() => toast.remove(), 200);
    }
  }, duration);
};
