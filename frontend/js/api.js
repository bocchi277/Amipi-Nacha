/**
 * AMIPI NACHA ACH Payment System — API Client
 *
 * Centralised HTTP helper for all backend communication.
 * Handles token storage, auth headers, and JSON parsing.
 */

const API = (() => {
  function getApiBaseUrl() {
    const customUrl = window.AMIPI_API_URL || localStorage.getItem('amipi_api_url');
    if (customUrl) {
      const clean = customUrl.replace(/\/+$/, '');
      return clean.endsWith('/api/v1') ? clean : `${clean}/api/v1`;
    }
    // If running on localhost or 127.0.0.1, use relative path or local port
    const isLocalhost = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
    if (isLocalhost) {
      return '/api/v1';
    }
    // Production default live Render backend
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
      throw new Error('Backend server is waking up or initializing. Please retry in a few seconds.');
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
        if (!path.includes('/auth/')) {
          window.location.reload();
        }
      }
      let errMsg = `An error occurred (HTTP ${res.status}). Please try again.`;
      if (data) {
        if (typeof data.detail === 'string') {
          errMsg = data.detail;
        } else if (Array.isArray(data.detail)) {
          errMsg = data.detail.map(e => e.msg || e.detail || 'Validation error').join('; ');
        } else if (typeof data.message === 'string') {
          errMsg = data.message;
        }
      }
      throw new Error(errMsg);
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

  async function getProfile() {
    return get('/auth/me');
  }

  // ── Public API ─────────────────────────────────────────────

  return {
    // Token
    getToken, setToken, clearToken, getUser, setUser,
    isAuthenticated,
    // HTTP
    get, post, put, patch, del, postForm,
    // Auth
    login, register, logout, getProfile,
  };
})();
