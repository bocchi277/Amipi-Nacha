/**
 * AMIPI NACHA ACH Payment System — Admin Bank Change Request Review Controller
 *
 * Restrictive Admin panel for reviewing, approving, and rejecting vendor bank detail change requests.
 * Approvals immediately update actual Vendor bank details in PostgreSQL and write to AuditLog.
 * Rejections leave Vendor bank details unchanged and record the decision in AuditLog.
 */

const AdminScreen = (() => {
  let pendingRequests = [];

  function el(id) { return document.getElementById(id); }

  function init() {
    bindEvents();
  }

  function bindEvents() {
    const refreshBtn = el('refreshAdminApprovalsBtn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', loadPendingRequests);
    }

    // Auto-load when switching to view-admin-approvals tab
    document.querySelectorAll('#mainTabs .tab').forEach(tab => {
      tab.addEventListener('click', () => {
        if (tab.dataset.view === 'admin-approvals') {
          loadPendingRequests();
        }
      });
    });
  }

  function checkAdminAccess() {
    const user = API.getUser();
    const isAdmin = user && user.role === 'admin';

    const adminTab = el('adminTabBtn');
    if (adminTab) {
      adminTab.style.display = isAdmin ? 'inline-flex' : 'none';
    }

    return isAdmin;
  }

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
        <td class="font-bold">${req.vendor_name}</td>
        <td class="font-mono text-xs">${req.requested_by_user_id ? req.requested_by_user_id.substring(0, 8) + '...' : 'User'}</td>
        <td class="font-mono text-xs">
          Routing: <strong style="color: var(--color-danger);">${req.requested_routing_number}</strong><br/>
          Account: <strong style="color: var(--color-danger);">${req.requested_account_number}</strong><br/>
          Type: ${req.requested_account_type.toUpperCase()}
        </td>
        <td class="text-xs" style="max-width: 200px;">${req.reason || '<span class="text-muted">No notes provided</span>'}</td>
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
      showGlobalSuccess(`Approved bank detail change request for "${result.vendor_name}". Vendor bank details updated.`);
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
      showGlobalSuccess(`Rejected bank detail change request for "${result.vendor_name}". Vendor bank details remain unchanged.`);
      await loadPendingRequests();
      if (typeof VendorsScreen !== 'undefined') VendorsScreen.loadData();
    } catch (err) {
      showGlobalError(err.message || 'Failed to reject change request.');
    }
  }

  return {
    init,
    checkAdminAccess,
    loadPendingRequests,
    approveRequest,
    rejectRequest,
  };
})();

document.addEventListener('DOMContentLoaded', () => {
  AdminScreen.init();
});
