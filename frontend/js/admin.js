/**
 * AMIPI NACHA ACH Payment System — Admin Controller
 *
 * Comprehensive Admin panel for:
 * 1. Reviewing, approving, and rejecting vendor bank detail change requests.
 * 2. In-App User Management (listing, provisioning, status toggle, and password reset).
 */

const AdminScreen = (() => {
  let pendingRequests = [];
  let systemUsers = [];

  function el(id) { return document.getElementById(id); }

  function init() {
    bindEvents();
  }

  function bindEvents() {
    const refreshBtn = el('refreshAdminApprovalsBtn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', loadPendingRequests);
    }

    const refreshUsersBtn = el('refreshAdminUsersBtn');
    if (refreshUsersBtn) {
      refreshUsersBtn.addEventListener('click', loadUsers);
    }

    // Add User Modal bindings
    const openAddUserBtn = el('openAddUserModalBtn');
    const closeAddUserBtn = el('closeAddUserModalBtn');
    const cancelAddUserBtn = el('cancelAddUserModalBtn');
    const addUserForm = el('addUserForm');

    if (openAddUserBtn) openAddUserBtn.addEventListener('click', openAddUserModal);
    if (closeAddUserBtn) closeAddUserBtn.addEventListener('click', hideAddUserModal);
    if (cancelAddUserBtn) cancelAddUserBtn.addEventListener('click', hideAddUserModal);
    if (addUserForm) addUserForm.addEventListener('submit', handleCreateUser);

    // Reset Password Modal bindings
    const closeResetPwBtn = el('closeResetPasswordModalBtn');
    const cancelResetPwBtn = el('cancelResetPasswordModalBtn');
    const resetPwForm = el('resetPasswordForm');

    if (closeResetPwBtn) closeResetPwBtn.addEventListener('click', hideResetPasswordModal);
    if (cancelResetPwBtn) cancelResetPwBtn.addEventListener('click', hideResetPasswordModal);
    if (resetPwForm) resetPwForm.addEventListener('submit', handleResetPassword);

    // Auto-load when switching to view-admin-approvals tab
    document.querySelectorAll('#mainTabs .tab').forEach(tab => {
      tab.addEventListener('click', () => {
        if (tab.dataset.view === 'admin-approvals') {
          loadPendingRequests();
          loadUsers();
        }
      });
    });
  }

  function checkAdminAccess() {
    const user = API.getUser();
    const isAdmin = user && user.role === 'admin';

    const adminTab = el('adminTabBtn');
    const auditTab = el('auditTabBtn');
    if (adminTab) {
      adminTab.style.display = isAdmin ? 'inline-flex' : 'none';
    }
    if (auditTab) {
      auditTab.style.display = isAdmin ? 'inline-flex' : 'none';
    }

    return isAdmin;
  }

  // ── Change Request Review Section ──────────────────────────

  async function loadPendingRequests() {
    const container = el('adminApprovalsContainer');
    const deniedBox = el('adminAccessDeniedBox');
    if (!container) return;

    if (!checkAdminAccess()) {
      if (container) container.style.display = 'none';
      if (deniedBox) deniedBox.style.display = 'block';
      return;
    }

    if (deniedBox) deniedBox.style.display = 'none';
    if (container) container.style.display = 'block';

    setLoading(true);

    try {
      const allRequests = await API.get('/vendors/change-requests/all');
      pendingRequests = (allRequests || []).filter(r => String(r.status).toLowerCase() === 'pending');
      renderRequestsTable(pendingRequests);
    } catch (err) {
      showGlobalError(err.message || 'Failed to load change requests.');
    } finally {
      setLoading(false);
    }
  }

  function setLoading(loading) {
    const spinner = el('adminSpinner');
    if (spinner) spinner.style.display = loading ? 'inline-block' : 'none';
  }

  function showGlobalError(msg) {
    const alertEl = el('adminGlobalAlert');
    if (alertEl) {
      alertEl.className = 'alert alert-error show';
      alertEl.textContent = msg;
      alertEl.style.display = 'block';
    }
  }

  function showGlobalSuccess(msg) {
    const alertEl = el('adminGlobalAlert');
    if (alertEl) {
      alertEl.className = 'alert alert-success show';
      alertEl.textContent = msg;
      alertEl.style.display = 'block';
      setTimeout(() => { alertEl.style.display = 'none'; }, 4000);
    }
  }

  function renderRequestsTable(requests) {
    const tbody = el('adminRequestsTableBody');
    const badge = el('adminPendingCountBadge');
    if (!tbody) return;

    if (badge) badge.textContent = `${requests.length} Pending`;

    tbody.innerHTML = '';

    if (requests.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="7" class="text-center text-muted" style="padding: var(--space-xl);">
            No pending bank detail change requests awaiting review.
          </td>
        </tr>
      `;
      return;
    }

    requests.forEach((req, idx) => {
      const tr = document.createElement('tr');
      tr.setAttribute('data-request-id', req.id);

      tr.innerHTML = `
        <td class="font-mono">${idx + 1}</td>
        <td class="font-bold">${escapeHtml(req.vendor_name)}</td>
        <td class="font-mono text-xs">${req.requested_by_user_id ? req.requested_by_user_id.substring(0, 8) + '...' : 'User'}</td>
        <td class="font-mono text-xs">
          Routing: <strong style="color: var(--color-danger);">${req.requested_routing_number}</strong><br/>
          Account: <strong style="color: var(--color-danger);">${req.requested_account_number}</strong><br/>
          Type: ${req.requested_account_type.toUpperCase()}
        </td>
        <td class="text-xs" style="max-width: 200px;">${escapeHtml(req.reason || '<span class="text-muted">No notes provided</span>')}</td>
        <td><span class="badge badge-warning">PENDING</span></td>
        <td>
          <div style="display: flex; gap: var(--space-xs);">
            <button type="button" class="btn btn-success btn-sm btn-approve" onclick="AdminScreen.approveRequest('${req.id}')">
              Approve
            </button>
            <button type="button" class="btn btn-danger btn-sm btn-reject" onclick="AdminScreen.rejectRequest('${req.id}')">
              Reject
            </button>
          </div>
        </td>
      `;

      tbody.appendChild(tr);
    });
  }

  async function approveRequest(requestId) {
    if (!confirm('Approve this bank detail change request? This will update the vendor\'s actual banking records in the database.')) {
      return;
    }

    try {
      const result = await API.post(`/vendors/change-requests/${requestId}/approve`);
      showGlobalSuccess(`Approved bank detail change request for "${escapeHtml(result.vendor_name)}". Vendor bank details updated.`);
      await loadPendingRequests();
      if (typeof VendorsScreen !== 'undefined') VendorsScreen.loadData();
    } catch (err) {
      showGlobalError(err.message || 'Failed to approve change request.');
    }
  }

  async function rejectRequest(requestId) {
    if (!confirm('Reject this bank detail change request? Vendor bank details will remain unchanged.')) {
      return;
    }

    try {
      const result = await API.post(`/vendors/change-requests/${requestId}/reject`);
      showGlobalSuccess(`Rejected bank detail change request for "${escapeHtml(result.vendor_name)}". Vendor bank details remain unchanged.`);
      await loadPendingRequests();
      if (typeof VendorsScreen !== 'undefined') VendorsScreen.loadData();
    } catch (err) {
      showGlobalError(err.message || 'Failed to reject change request.');
    }
  }

  // ── In-App User Management Section ─────────────────────────

  async function loadUsers() {
    if (!checkAdminAccess()) return;

    setUsersLoading(true);

    try {
      const users = await API.getUsers();
      systemUsers = users || [];
      renderUsersTable(systemUsers);
    } catch (err) {
      showUserGlobalError(err.message || 'Failed to load user accounts.');
    } finally {
      setUsersLoading(false);
    }
  }

  function setUsersLoading(loading) {
    const spinner = el('adminUsersSpinner');
    if (spinner) spinner.style.display = loading ? 'inline-block' : 'none';
  }

  function showUserGlobalError(msg) {
    const alertEl = el('adminUserGlobalAlert');
    if (alertEl) {
      alertEl.className = 'alert alert-error show';
      alertEl.textContent = msg;
      alertEl.style.display = 'block';
    }
  }

  function showUserGlobalSuccess(msg) {
    const alertEl = el('adminUserGlobalAlert');
    if (alertEl) {
      alertEl.className = 'alert alert-success show';
      alertEl.textContent = msg;
      alertEl.style.display = 'block';
      setTimeout(() => { alertEl.style.display = 'none'; }, 4000);
    }
  }

  function renderUsersTable(users) {
    const tbody = el('adminUsersTableBody');
    const badge = el('adminUserCountBadge');
    if (!tbody) return;

    if (badge) badge.textContent = `${users.length} Users`;
    tbody.innerHTML = '';

    if (users.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="7" class="text-center text-muted" style="padding: var(--space-xl);">
            No user accounts found.
          </td>
        </tr>
      `;
      return;
    }

    const currentUser = API.getUser();

    users.forEach((u, idx) => {
      const tr = document.createElement('tr');
      tr.setAttribute('data-user-id', u.id);

      const roleBadge = u.role === 'admin'
        ? `<span class="badge badge-primary" style="font-weight: 600;">Admin</span>`
        : `<span class="badge badge-secondary">User</span>`;

      const statusBadge = u.is_active
        ? `<span class="badge badge-success">Active</span>`
        : `<span class="badge badge-danger">Inactive</span>`;

      const createdDateStr = u.created_at
        ? new Date(u.created_at).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })
        : '—';

      const isSelf = currentUser && (currentUser.username === u.username);

      let toggleBtn = '';
      if (!isSelf) {
        toggleBtn = u.is_active
          ? `<button type="button" class="btn btn-danger btn-sm" onclick="AdminScreen.toggleUserStatus('${u.id}', '${escapeJsAttr(u.username)}', true)" style="font-size: var(--text-xs); padding: 2px 8px;">Deactivate</button>`
          : `<button type="button" class="btn btn-success btn-sm" onclick="AdminScreen.toggleUserStatus('${u.id}', '${escapeJsAttr(u.username)}', false)" style="font-size: var(--text-xs); padding: 2px 8px;">Activate</button>`;
      } else {
        toggleBtn = `<span class="text-xs text-muted" style="padding: 2px 4px;">(Current User)</span>`;
      }

      tr.innerHTML = `
        <td class="font-mono">${idx + 1}</td>
        <td class="font-bold">${escapeHtml(u.username)}</td>
        <td class="font-mono text-xs">${escapeHtml(u.email)}</td>
        <td>${roleBadge}</td>
        <td>${statusBadge}</td>
        <td class="text-xs text-muted">${createdDateStr}</td>
        <td style="text-align: right;">
          <div style="display: flex; gap: var(--space-xs); justify-content: flex-end; align-items: center;">
            <button type="button" class="btn btn-secondary btn-sm" onclick="AdminScreen.openResetPasswordModal('${u.id}', '${escapeJsAttr(u.username)}')" style="font-size: var(--text-xs); padding: 2px 8px;">
              Reset Password
            </button>
            ${toggleBtn}
          </div>
        </td>
      `;

      tbody.appendChild(tr);
    });
  }

  // ── Add User Modal ─────────────────────────────────────────

  function openAddUserModal() {
    el('newUsername').value = '';
    el('newUserEmail').value = '';
    el('newUserPassword').value = '';
    el('newUserRole').value = 'user';

    const errBox = el('addUserModalError');
    if (errBox) errBox.style.display = 'none';

    const modal = el('addUserModal');
    if (modal) {
      modal.classList.add('active');
      modal.style.display = 'flex';
      el('newUsername')?.focus();
    }
  }

  function hideAddUserModal() {
    const modal = el('addUserModal');
    if (modal) {
      modal.classList.remove('active');
      modal.style.display = 'none';
    }
  }

  async function handleCreateUser(e) {
    if (e) e.preventDefault();

    const username = el('newUsername').value.trim();
    const email = el('newUserEmail').value.trim();
    const password = el('newUserPassword').value;
    const role = el('newUserRole').value;
    const errBox = el('addUserModalError');
    const spinner = el('addUserSpinner');
    const submitBtn = el('submitAddUserBtn');

    if (errBox) errBox.style.display = 'none';

    if (!username) {
      if (errBox) { errBox.textContent = 'Username is required.'; errBox.style.display = 'block'; }
      return;
    }
    if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      if (errBox) { errBox.textContent = 'A valid email address is required.'; errBox.style.display = 'block'; }
      return;
    }
    if (!password || password.length < 8) {
      if (errBox) { errBox.textContent = 'Password must be at least 8 characters long.'; errBox.style.display = 'block'; }
      return;
    }

    if (spinner) spinner.style.display = 'inline-block';
    if (submitBtn) submitBtn.disabled = true;

    try {
      await API.createUser(email, username, password, role);
      hideAddUserModal();
      showUserGlobalSuccess(`User account "${username}" (${role.toUpperCase()}) provisioned successfully.`);
      if (window.showToast) window.showToast(`User account "${username}" provisioned.`, 'success');
      await loadUsers();
    } catch (err) {
      if (errBox) {
        errBox.textContent = err.message || 'Failed to create user account.';
        errBox.style.display = 'block';
      }
    } finally {
      if (spinner) spinner.style.display = 'none';
      if (submitBtn) submitBtn.disabled = false;
    }
  }

  // ── Status Toggle ──────────────────────────────────────────

  async function toggleUserStatus(userId, username, isCurrentlyActive) {
    const action = isCurrentlyActive ? 'deactivate' : 'activate';
    if (!confirm(`Are you sure you want to ${action} the account for "${username}"?`)) {
      return;
    }

    try {
      await API.updateUserStatus(userId, !isCurrentlyActive);
      showUserGlobalSuccess(`User "${username}" has been ${isCurrentlyActive ? 'deactivated' : 'activated'}.`);
      if (window.showToast) window.showToast(`User "${username}" ${isCurrentlyActive ? 'deactivated' : 'activated'}.`, 'info');
      await loadUsers();
    } catch (err) {
      showUserGlobalError(err.message || `Failed to ${action} user.`);
    }
  }

  // ── Reset Password Modal ───────────────────────────────────

  function openResetPasswordModal(userId, username) {
    el('resetPasswordUserId').value = userId;
    el('resetPasswordNewPassword').value = '';
    const userLabel = el('resetPasswordUserLabel');
    if (userLabel) userLabel.textContent = `Set a new password for account "${username}".`;

    const errBox = el('resetPasswordModalError');
    if (errBox) errBox.style.display = 'none';

    const modal = el('resetPasswordModal');
    if (modal) {
      modal.classList.add('active');
      modal.style.display = 'flex';
      el('resetPasswordNewPassword')?.focus();
    }
  }

  function hideResetPasswordModal() {
    const modal = el('resetPasswordModal');
    if (modal) {
      modal.classList.remove('active');
      modal.style.display = 'none';
    }
  }

  async function handleResetPassword(e) {
    if (e) e.preventDefault();

    const userId = el('resetPasswordUserId').value;
    const newPassword = el('resetPasswordNewPassword').value;
    const errBox = el('resetPasswordModalError');
    const spinner = el('resetPasswordSpinner');
    const submitBtn = el('submitResetPasswordBtn');

    if (errBox) errBox.style.display = 'none';

    if (!newPassword || newPassword.length < 8) {
      if (errBox) { errBox.textContent = 'New password must be at least 8 characters long.'; errBox.style.display = 'block'; }
      return;
    }

    if (spinner) spinner.style.display = 'inline-block';
    if (submitBtn) submitBtn.disabled = true;

    try {
      const res = await API.resetUserPassword(userId, newPassword);
      hideResetPasswordModal();
      showUserGlobalSuccess(res.message || 'User password reset successfully.');
      if (window.showToast) window.showToast('Password updated successfully.', 'success');
    } catch (err) {
      if (errBox) {
        errBox.textContent = err.message || 'Failed to reset password.';
        errBox.style.display = 'block';
      }
    } finally {
      if (spinner) spinner.style.display = 'none';
      if (submitBtn) submitBtn.disabled = false;
    }
  }

  return {
    init,
    checkAdminAccess,
    loadPendingRequests,
    approveRequest,
    rejectRequest,
    loadUsers,
    openAddUserModal,
    hideAddUserModal,
    handleCreateUser,
    toggleUserStatus,
    openResetPasswordModal,
    hideResetPasswordModal,
    handleResetPassword,
  };
})();

document.addEventListener('DOMContentLoaded', () => {
  AdminScreen.init();
});

