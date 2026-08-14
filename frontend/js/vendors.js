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

    const closeEditVendorBtn = el('closeEditVendorModalBtn');
    const cancelEditVendorBtn = el('cancelEditVendorModalBtn');
    const editVendorForm = el('editVendorProfileForm');

    if (closeEditVendorBtn) closeEditVendorBtn.addEventListener('click', hideEditVendorModal);
    if (cancelEditVendorBtn) cancelEditVendorBtn.addEventListener('click', hideEditVendorModal);
    if (editVendorForm) editVendorForm.addEventListener('submit', handleSaveVendorProfile);

    // Add Vendor Modal Event Listeners
    const openAddVendorBtn = el('openAddVendorModalBtn');
    const closeAddVendorBtn = el('closeAddVendorModalBtn');
    const cancelAddVendorBtn = el('cancelAddVendorModalBtn');
    const cancelBulkVendorBtn = el('cancelBulkVendorModalBtn');
    const addSingleVendorTab = el('addSingleVendorTabBtn');
    const addBulkVendorTab = el('addBulkVendorTabBtn');
    const singleVendorForm = el('addVendorForm');
    const bulkVendorForm = el('bulkVendorForm');
    const downloadTemplateBtn = el('downloadVendorTemplateBtn');

    if (openAddVendorBtn) openAddVendorBtn.addEventListener('click', openAddVendorModal);
    if (closeAddVendorBtn) closeAddVendorBtn.addEventListener('click', hideAddVendorModal);
    if (cancelAddVendorBtn) cancelAddVendorBtn.addEventListener('click', hideAddVendorModal);
    if (cancelBulkVendorBtn) cancelBulkVendorBtn.addEventListener('click', hideAddVendorModal);
    if (addSingleVendorTab) addSingleVendorTab.addEventListener('click', () => switchAddVendorTab('single'));
    if (addBulkVendorTab) addBulkVendorTab.addEventListener('click', () => switchAddVendorTab('bulk'));
    if (singleVendorForm) singleVendorForm.addEventListener('submit', handleCreateSingleVendorSubmit);
    if (bulkVendorForm) bulkVendorForm.addEventListener('submit', handleUploadBulkVendorsSubmit);
    if (downloadTemplateBtn) downloadTemplateBtn.addEventListener('click', downloadVendorTemplate);

    // Auto-reload when switching to view-vendors tab
    document.querySelectorAll('#mainTabs .tab').forEach(tab => {
      tab.addEventListener('click', () => {
        if (tab.dataset.view === 'vendors') {
          loadData();
        }
      });
    });
  }

  function openEditVendorModal(vendorId) {
    const vendor = loadedVendors.find(v => v.id === vendorId);
    if (!vendor) return;

    el('editVendorId').value = vendor.id;
    el('editVendorModalTitle').textContent = `Edit Vendor Profile — ${vendor.name}`;
    el('editVendorName').value = vendor.name;
    el('editVendorEmail').value = vendor.email || (`ap@${vendor.name.toLowerCase().replace(/[^a-z0-9]/g, '')}.com`);
    el('editVendorRef').value = vendor.default_id_number || '';

    if (el('editVendorError')) el('editVendorError').style.display = 'none';
    if (el('editVendorSuccess')) el('editVendorSuccess').style.display = 'none';

    el('editVendorProfileModal').classList.add('active');
  }

  function hideEditVendorModal() {
    el('editVendorProfileModal').classList.remove('active');
  }

  async function handleSaveVendorProfile(e) {
    if (e) e.preventDefault();

    const vendorId = el('editVendorId').value;
    const name = el('editVendorName').value.trim();
    const email = el('editVendorEmail').value.trim();
    const ref = el('editVendorRef').value.trim();

    const errBox = el('editVendorError');
    const succBox = el('editVendorSuccess');
    const spinner = el('editVendorSpinner');
    const btn = el('saveVendorProfileBtn');

    if (errBox) errBox.style.display = 'none';
    if (succBox) succBox.style.display = 'none';

    if (!name) {
      errBox.textContent = 'Vendor Name is required.';
      errBox.style.display = 'block';
      return;
    }

    if (!email || !email.includes('@')) {
      errBox.textContent = 'Please enter a valid vendor email address.';
      errBox.style.display = 'block';
      return;
    }

    if (btn) btn.disabled = true;
    if (spinner) spinner.style.display = 'inline-block';

    try {
      await API.put(`/vendors/${vendorId}`, {
        name,
        email,
        default_id_number: ref || undefined,
      });

      if (succBox) {
        succBox.textContent = 'Vendor profile updated successfully! Email saved to database.';
        succBox.style.display = 'block';
      }

      await loadData();

      setTimeout(() => {
        hideEditVendorModal();
      }, 1500);
    } catch (err) {
      if (errBox) {
        errBox.textContent = err.message || 'Failed to update vendor profile.';
        errBox.style.display = 'block';
      }
    } finally {
      if (btn) btn.disabled = false;
      if (spinner) spinner.style.display = 'none';
    }
  }

  // ── Add Vendor Modal & Workflow ──────────────────────────────
  function switchAddVendorTab(tabType) {
    const singleTab = el('addSingleVendorTabBtn');
    const bulkTab = el('addBulkVendorTabBtn');
    const singleContent = el('addSingleVendorContent');
    const bulkContent = el('addBulkVendorContent');

    if (el('addVendorError')) el('addVendorError').style.display = 'none';
    if (el('addVendorSuccess')) el('addVendorSuccess').style.display = 'none';

    if (tabType === 'single') {
      if (singleTab) {
        singleTab.style.borderBottom = '2px solid var(--color-primary)';
        singleTab.style.color = 'var(--color-primary)';
      }
      if (bulkTab) {
        bulkTab.style.borderBottom = 'none';
        bulkTab.style.color = 'var(--color-text-muted)';
      }
      if (singleContent) singleContent.style.display = 'block';
      if (bulkContent) bulkContent.style.display = 'none';
    } else {
      if (bulkTab) {
        bulkTab.style.borderBottom = '2px solid var(--color-primary)';
        bulkTab.style.color = 'var(--color-primary)';
      }
      if (singleTab) {
        singleTab.style.borderBottom = 'none';
        singleTab.style.color = 'var(--color-text-muted)';
      }
      if (bulkContent) bulkContent.style.display = 'block';
      if (singleContent) singleContent.style.display = 'none';
    }
  }

  function openAddVendorModal() {
    if (el('addVendorError')) el('addVendorError').style.display = 'none';
    if (el('addVendorSuccess')) el('addVendorSuccess').style.display = 'none';
    if (el('bulkVendorResultSummary')) el('bulkVendorResultSummary').style.display = 'none';
    if (el('addVendorForm')) el('addVendorForm').reset();
    if (el('bulkVendorForm')) el('bulkVendorForm').reset();
    switchAddVendorTab('single');
    if (el('addVendorModal')) el('addVendorModal').classList.add('active');
  }

  function hideAddVendorModal() {
    if (el('addVendorModal')) el('addVendorModal').classList.remove('active');
  }

  async function handleCreateSingleVendorSubmit(e) {
    if (e) e.preventDefault();

    const name = el('addVendorName') ? el('addVendorName').value.trim() : '';
    const routing_number = el('addVendorRouting') ? el('addVendorRouting').value.trim() : '';
    const account_number = el('addVendorAccount') ? el('addVendorAccount').value.trim() : '';
    const account_type = el('addVendorAccountType') ? el('addVendorAccountType').value : 'checking';
    const default_id_number = el('addVendorRef') ? (el('addVendorRef').value.trim() || null) : null;
    const email = el('addVendorEmail') ? (el('addVendorEmail').value.trim() || null) : null;

    const errBox = el('addVendorError');
    const succBox = el('addVendorSuccess');
    const spinner = el('addVendorSpinner');
    const saveBtn = el('saveAddVendorBtn');

    if (errBox) errBox.style.display = 'none';
    if (succBox) succBox.style.display = 'none';

    if (!name || !routing_number || !account_number) {
      if (errBox) {
        errBox.textContent = 'Vendor Name, Routing Number, and Account Number are required.';
        errBox.style.display = 'block';
      }
      return;
    }

    if (saveBtn) saveBtn.disabled = true;
    if (spinner) spinner.style.display = 'inline-block';

    try {
      await API.post('/vendors', {
        name,
        routing_number,
        account_number,
        account_type,
        default_id_number,
        email,
      });

      hideAddVendorModal();
      await loadData();
    } catch (err) {
      if (errBox) {
        errBox.textContent = err.message || 'Failed to create vendor.';
        errBox.style.display = 'block';
      }
    } finally {
      if (saveBtn) saveBtn.disabled = false;
      if (spinner) spinner.style.display = 'none';
    }
  }

  function downloadVendorTemplate() {
    const csvContent = 'Vendor Name,Routing Number,Account Number,Account Type,Invoice Ref,Email\nACME SUPPLIES INC,021000021,11391039,checking,INV-1001,ap@acme.com\nBELGIUM DIA LLC,021000322,483110589481,checking,INV-1002,ap@belgium.com\n';
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    link.setAttribute('href', url);
    link.setAttribute('download', 'vendor_import_template.csv');
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  async function handleUploadBulkVendorsSubmit(e) {
    if (e) e.preventDefault();

    const fileInput = el('bulkVendorFileInput');
    const errBox = el('addVendorError');
    const succBox = el('addVendorSuccess');
    const summaryBox = el('bulkVendorResultSummary');
    const spinner = el('bulkVendorSpinner');
    const uploadBtn = el('uploadBulkVendorBtn');

    if (errBox) errBox.style.display = 'none';
    if (succBox) succBox.style.display = 'none';
    if (summaryBox) summaryBox.style.display = 'none';

    if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
      if (errBox) {
        errBox.textContent = 'Please select a CSV or Excel file to upload.';
        errBox.style.display = 'block';
      }
      return;
    }

    const file = fileInput.files[0];
    const formData = new FormData();
    formData.append('file', file);

    if (uploadBtn) uploadBtn.disabled = true;
    if (spinner) spinner.style.display = 'inline-block';

    try {
      const result = await API.postForm('/vendors/bulk-upload', formData);

      let summaryHtml = `<div class="card" style="padding: 12px; background: var(--color-surface-alt, #f8fafc); border-left: 4px solid var(--color-primary);">
        <strong style="font-size: var(--text-xs); color: var(--color-primary);">Bulk Import Complete:</strong>
        <ul style="margin: 4px 0 0 16px; padding: 0; font-size: var(--text-xs);">
          <li><strong>${result.imported_count}</strong> new vendor(s) imported successfully</li>
          <li><strong>${result.skipped_count}</strong> duplicate vendor(s) skipped</li>
          <li><strong>${result.errors ? result.errors.length : 0}</strong> row error(s)</li>
        </ul>
      </div>`;

      if (result.errors && result.errors.length > 0) {
        summaryHtml += `<div class="alert alert-danger" style="margin-top: 8px; font-size: var(--text-xs); max-height: 120px; overflow-y: auto;">
          <strong>Row Validation Warnings:</strong><br/>
          ${result.errors.map(err => `Row ${err.row}: ${err.error}`).join('<br/>')}
        </div>`;
      }

      if (summaryBox) {
        summaryBox.innerHTML = summaryHtml;
        summaryBox.style.display = 'block';
      }

      if (result.imported_count > 0) {
        await loadData();
      }
    } catch (err) {
      if (errBox) {
        errBox.textContent = err.message || 'Failed to upload bulk vendors file.';
        errBox.style.display = 'block';
      }
    } finally {
      if (uploadBtn) uploadBtn.disabled = false;
      if (spinner) spinner.style.display = 'none';
    }
  }

  return {
    init,
    loadData,
    openChangeModal,
    openEditVendorModal,
  };


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
            <span class="text-muted">Email Address:</span><br/>
            <span class="font-mono text-xs" style="color: var(--color-primary);">${v.email || 'ap@' + v.name.toLowerCase().replace(/[^a-z0-9]/g, '') + '.com'}</span>
          </div>
        </div>

        ${pendingNoticeHtml}

        <div style="margin-top: var(--space-md); display: flex; gap: var(--space-xs); justify-content: flex-end;">
          <button type="button" class="btn btn-secondary btn-sm" onclick="VendorsScreen.openEditVendorModal('${v.id}')">
            Edit Profile
          </button>
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
          <td colspan="7" style="padding: 24px; text-align: center; color: var(--color-text-muted);">
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

      const displayEmail = v.email || ('ap@' + v.name.toLowerCase().replace(/[^a-z0-9]/g, '') + '.com');

      tr.innerHTML = `
        <td style="padding: 12px 16px;">
          <strong style="color: var(--color-primary); font-size: var(--text-sm); display: block;">${v.name}</strong>
          <span class="text-xs text-muted">ID: ${v.id.substring(0, 8)}...</span>
        </td>
        <td style="padding: 12px 16px;" class="font-mono text-xs">${displayEmail}</td>
        <td style="padding: 12px 16px;" class="font-mono">${v.routing_number}</td>
        <td style="padding: 12px 16px;" class="font-mono">${maskAccount(v.account_number)}</td>
        <td style="padding: 12px 16px;" class="font-mono">${(v.account_type || 'checking').toUpperCase()}</td>
        <td style="padding: 12px 16px;">${statusBadge}</td>
        <td style="padding: 12px 16px; text-align: right;">
          <div style="display: flex; gap: var(--space-xs); justify-content: flex-end;">
            <button type="button" class="btn btn-secondary btn-sm" onclick="VendorsScreen.openEditVendorModal('${v.id}')">
              Edit Profile
            </button>
            <button type="button" class="btn btn-secondary btn-sm" onclick="VendorsScreen.openChangeModal('${v.id}')">
              Request Bank Change
            </button>
          </div>
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
    openEditVendorModal,
  };
})();

document.addEventListener('DOMContentLoaded', () => {
  VendorsScreen.init();
});
