/**
 * AMIPI NACHA ACH Payment System — Vendor Directory & Change Request Controller
 *
 * Allows users to view registered vendors, inspect current bank details,
 * and submit bank detail change requests (which remain PENDING until approved by an Admin).
 */

const VendorsScreen = (() => {
  let loadedVendors = [];
  let loadedChangeRequests = [];
  let activeVendorForRequest = null;
  let currentViewMode = 'card'; // 'card' or 'table'
  let showFullAccountDetails = false;

  function el(id) { return document.getElementById(id); }

  function init() {
    bindEvents();
  }

  function bindEvents() {
    const searchInput = el('vendorSearchInput');
    if (searchInput) {
      searchInput.addEventListener('input', filterAndRenderVendors);
    }

    const refreshBtn = el('refreshVendorsBtn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', loadData);
    }

    // View Mode Toggle Listeners
    const cardBtn = el('vendorCardViewBtn');
    const tableBtn = el('vendorTableViewBtn');
    if (cardBtn) {
      cardBtn.addEventListener('click', () => setViewMode('card'));
    }
    if (tableBtn) {
      tableBtn.addEventListener('click', () => setViewMode('table'));
    }

    // Account Mask Toggle Listener
    const maskBtn = el('vendorMaskToggleBtn');
    if (maskBtn) {
      maskBtn.addEventListener('click', () => {
        showFullAccountDetails = !showFullAccountDetails;
        const btnText = maskBtn.querySelector('span');
        if (btnText) {
          btnText.textContent = showFullAccountDetails ? 'Hide Account Details' : 'Show Account Details';
        }
        filterAndRenderVendors();
      });
    }

    const closeBtn = el('closeReqModalBtn');
    const cancelBtn = el('cancelReqModalBtn');
    if (closeBtn) closeBtn.addEventListener('click', hideModal);
    if (cancelBtn) cancelBtn.addEventListener('click', hideModal);

    const form = el('changeReqForm');
    if (form) {
      form.addEventListener('submit', handleSubmitChangeRequest);
    }

    // Auto-reload when switching to view-vendors tab
    document.querySelectorAll('#mainTabs .tab').forEach(tab => {
      tab.addEventListener('click', () => {
        if (tab.dataset.view === 'vendors') {
          loadData();
        }
      });
    });
  }

  function setViewMode(mode) {
    currentViewMode = mode;
    const cardBtn = el('vendorCardViewBtn');
    const tableBtn = el('vendorTableViewBtn');
    const gridContainer = el('vendorGridContainer');
    const tableContainer = el('vendorTableContainer');

    if (mode === 'card') {
      if (cardBtn) {
        cardBtn.style.background = 'var(--color-surface, #ffffff)';
        cardBtn.style.color = 'var(--color-text, #0f172a)';
        cardBtn.style.fontWeight = '600';
        cardBtn.style.boxShadow = '0 1px 2px rgba(0,0,0,0.08)';
      }
      if (tableBtn) {
        tableBtn.style.background = 'transparent';
        tableBtn.style.color = 'var(--color-text-muted, #64748b)';
        tableBtn.style.fontWeight = 'normal';
        tableBtn.style.boxShadow = 'none';
      }
      if (gridContainer) gridContainer.style.display = 'grid';
      if (tableContainer) tableContainer.style.display = 'none';
    } else {
      if (tableBtn) {
        tableBtn.style.background = 'var(--color-surface, #ffffff)';
        tableBtn.style.color = 'var(--color-text, #0f172a)';
        tableBtn.style.fontWeight = '600';
        tableBtn.style.boxShadow = '0 1px 2px rgba(0,0,0,0.08)';
      }
      if (cardBtn) {
        cardBtn.style.background = 'transparent';
        cardBtn.style.color = 'var(--color-text-muted, #64748b)';
        cardBtn.style.fontWeight = 'normal';
        cardBtn.style.boxShadow = 'none';
      }
      if (gridContainer) gridContainer.style.display = 'none';
      if (tableContainer) tableContainer.style.display = 'block';
    }

    filterAndRenderVendors();
  }

  function maskAccount(acct) {
    if (!acct) return '••••';
    if (showFullAccountDetails) return acct;
    if (acct.length <= 4) return acct;
    return '•••• ' + acct.slice(-4);
  }

  async function loadData() {
    if (!API.isAuthenticated()) return;

    try {
      const [vendors, requests] = await Promise.all([
        API.get('/vendors').catch(() => []),
        API.get('/vendors/change-requests/all').catch(() => []),
      ]);

      loadedVendors = vendors || [];
      loadedChangeRequests = requests || [];

      renderPendingSummary();
      filterAndRenderVendors();
    } catch (err) {
      console.warn('Failed to load vendors or change requests:', err);
    }
  }

  function renderPendingSummary() {
    const summaryCard = el('pendingReqSummaryCard');
    const summaryText = el('pendingReqSummaryText');
    const summaryBadge = el('pendingReqBadge');
    if (!summaryCard) return;

    const pendingList = loadedChangeRequests.filter(r => r.status === 'pending');
    if (pendingList.length > 0) {
      summaryCard.style.display = 'block';
      if (summaryText) summaryText.textContent = `${pendingList.length} bank detail change request(s) awaiting Admin approval.`;
      if (summaryBadge) summaryBadge.textContent = `${pendingList.length} Pending`;
    } else {
      summaryCard.style.display = 'none';
    }
  }

  function filterAndRenderVendors() {
    const searchInput = el('vendorSearchInput');
    const term = searchInput ? searchInput.value.trim().toLowerCase() : '';

    const filtered = loadedVendors.filter(v =>
      v.name.toLowerCase().includes(term) ||
      (v.routing_number && v.routing_number.includes(term)) ||
      (v.account_number && v.account_number.includes(term))
    );

    if (currentViewMode === 'card') {
      renderVendorCards(filtered);
    } else {
      renderVendorTable(filtered);
    }
  }

  function renderVendorCards(vendors) {
    const container = el('vendorGridContainer');
    if (!container) return;

    container.innerHTML = '';

    if (vendors.length === 0) {
      container.innerHTML = `
        <div class="card full-width text-center text-muted" style="padding: var(--space-xl); grid-column: 1 / -1;">
          No vendors found in directory.
        </div>
      `;
      return;
    }

    vendors.forEach(v => {
      const card = document.createElement('div');
      card.className = 'card vendor-card';
      card.setAttribute('data-vendor-id', v.id);

      const pendingReq = loadedChangeRequests.find(r =>
        String(r.vendor_id).toLowerCase() === String(v.id).toLowerCase() &&
        String(r.status).toLowerCase() === 'pending'
      );

      let pendingNoticeHtml = '';
      if (pendingReq) {
        pendingNoticeHtml = `
          <div class="alert alert-warning show" style="margin-top: var(--space-sm); font-size: var(--text-xs); padding: 8px 12px;" data-pending-request-id="${pendingReq.id}">
            <strong>Change Request PENDING Admin Review</strong><br/>
            Requested Routing: <span class="font-mono font-bold">${pendingReq.requested_routing_number}</span> |
            Account: <span class="font-mono font-bold">${maskAccount(pendingReq.requested_account_number)}</span>
          </div>
        `;
      }

      card.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: var(--space-sm);">
          <div>
            <h4 style="margin: 0; font-size: var(--text-md); color: var(--color-primary);">${v.name}</h4>
            <div class="text-xs text-muted">ID: ${v.id.substring(0, 8)}...</div>
          </div>
          <span class="badge badge-success">Active</span>
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-xs); font-size: var(--text-xs); margin-bottom: var(--space-md);">
          <div>
            <span class="text-muted">Routing Number:</span><br/>
            <strong class="font-mono vendor-routing-display">${v.routing_number}</strong>
          </div>
          <div>
            <span class="text-muted">Account Number:</span><br/>
            <strong class="font-mono vendor-account-display">${maskAccount(v.account_number)}</strong>
          </div>
          <div>
            <span class="text-muted">Account Type:</span><br/>
            <span class="font-mono">${(v.account_type || 'checking').toUpperCase()}</span>
          </div>
          <div>
            <span class="text-muted">Default Ref:</span><br/>
            <span class="font-mono">${v.default_id_number || 'None'}</span>
          </div>
        </div>

        ${pendingNoticeHtml}

        <div style="margin-top: var(--space-md); display: flex; justify-content: flex-end;">
          <button type="button" class="btn btn-secondary btn-sm req-change-btn" onclick="VendorsScreen.openChangeModal('${v.id}')">
            Request Bank Change
          </button>
        </div>
      `;

      container.appendChild(card);
    });
  }

  function renderVendorTable(vendors) {
    const tbody = el('vendorTableBody');
    if (!tbody) return;

    tbody.innerHTML = '';

    if (vendors.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="6" style="padding: 24px; text-align: center; color: var(--color-text-muted);">
            No vendors found in directory.
          </td>
        </tr>
      `;
      return;
    }

    vendors.forEach((v, idx) => {
      const tr = document.createElement('tr');
      tr.style.borderBottom = '1px solid var(--border-color, #e2e8f0)';
      tr.style.background = idx % 2 === 0 ? 'var(--color-surface, #ffffff)' : 'var(--color-surface-alt, #f8fafc)';

      const pendingReq = loadedChangeRequests.find(r =>
        String(r.vendor_id).toLowerCase() === String(v.id).toLowerCase() &&
        String(r.status).toLowerCase() === 'pending'
      );

      let statusBadge = '<span class="badge badge-success">Active</span>';
      if (pendingReq) {
        statusBadge += ' <span class="badge badge-warning" title="Bank change request pending admin approval">Pending Change</span>';
      }

      tr.innerHTML = `
        <td style="padding: 12px 16px;">
          <strong style="color: var(--color-primary); font-size: var(--text-sm); display: block;">${v.name}</strong>
          <span class="text-xs text-muted">ID: ${v.id.substring(0, 8)}...</span>
        </td>
        <td style="padding: 12px 16px;" class="font-mono">${v.routing_number}</td>
        <td style="padding: 12px 16px;" class="font-mono">${maskAccount(v.account_number)}</td>
        <td style="padding: 12px 16px;" class="font-mono">${(v.account_type || 'checking').toUpperCase()}</td>
        <td style="padding: 12px 16px;">${statusBadge}</td>
        <td style="padding: 12px 16px; text-align: right;">
          <button type="button" class="btn btn-secondary btn-sm" onclick="VendorsScreen.openChangeModal('${v.id}')">
            Request Bank Change
          </button>
        </td>
      `;

      tbody.appendChild(tr);
    });
  }

  function openChangeModal(vendorId) {
    const vendor = loadedVendors.find(v => v.id === vendorId);
    if (!vendor) return;

    activeVendorForRequest = vendor;

    el('reqModalVendorId').value = vendor.id;
    el('reqModalVendorName').textContent = `Request Bank Change — ${vendor.name}`;
    el('reqModalCurrRouting').textContent = vendor.routing_number;
    el('reqModalCurrAccount').textContent = vendor.account_number;
    el('reqModalCurrType').textContent = (vendor.account_type || 'checking').toUpperCase();

    el('reqNewRouting').value = '';
    el('reqNewAccount').value = '';
    el('reqNewAccountType').value = vendor.account_type || 'checking';
    el('reqReason').value = '';

    el('reqModalError').style.display = 'none';
    el('reqModalSuccess').style.display = 'none';

    el('changeRequestModal').classList.add('active');
  }

  function hideModal() {
    el('changeRequestModal').classList.remove('active');
  }

  async function handleSubmitChangeRequest(e) {
    if (e) e.preventDefault();

    const vendorId = el('reqModalVendorId').value;
    const reqRouting = el('reqNewRouting').value.trim();
    const reqAccount = el('reqNewAccount').value.trim();
    const reqType = el('reqNewAccountType').value;
    const reason = el('reqReason').value.trim();

    const errBox = el('reqModalError');
    const succBox = el('reqModalSuccess');

    errBox.style.display = 'none';
    succBox.style.display = 'none';

    if (!reqRouting || reqRouting.length !== 9 || isNaN(reqRouting)) {
      errBox.textContent = 'Please enter a valid 9-digit ABA routing number.';
      errBox.style.display = 'block';
      return;
    }

    if (!reqAccount) {
      errBox.textContent = 'Please enter requested new account number.';
      errBox.style.display = 'block';
      return;
    }

    const payload = {
      requested_routing_number: reqRouting,
      requested_account_number: reqAccount,
      requested_account_type: reqType,
      reason: reason || undefined,
    };

    setModalLoading(true);

    try {
      const result = await API.post(`/vendors/${vendorId}/change-requests`, payload);

      succBox.innerHTML = `
        <strong>Bank Change Request Submitted!</strong><br/>
        Status: <span class="badge badge-warning">PENDING</span> (Awaiting Admin Review)<br/>
        <em>Note: Current vendor bank details remain UNCHANGED until approved.</em>
      `;
      succBox.style.display = 'block';

      // Reload data to show pending status badge on vendor card
      await loadData();

      setTimeout(() => {
        hideModal();
      }, 2000);
    } catch (err) {
      errBox.textContent = err.message || 'Failed to submit bank detail change request.';
      errBox.style.display = 'block';
    } finally {
      setModalLoading(false);
    }
  }

  function setModalLoading(loading) {
    const btn = el('submitReqBtn');
    const spinner = el('reqSpinner');
    if (btn) btn.disabled = loading;
    if (spinner) spinner.style.display = loading ? 'inline-block' : 'none';
  }

  return {
    init,
    loadData,
    openChangeModal,
  };
})();

document.addEventListener('DOMContentLoaded', () => {
  VendorsScreen.init();
});
