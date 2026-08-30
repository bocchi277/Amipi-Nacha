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
  let selectedVendorIds = new Set();
  let vendorsToDelete = [];
  let pendingSingleVendorPayload = null;
  let cachedBulkPreviewData = null;

  function isAdmin() {
    const user = API.getUser();
    return user && String(user.role).toLowerCase() === 'admin';
  }

  function el(id) { return document.getElementById(id); }

  function init() {
    bindEvents();
  }

  function bindEvents() {
    const searchInput = el('vendorSearchInput');
    if (searchInput) {
      searchInput.addEventListener('input', filterAndRenderVendors);
    }

    const statusFilter = el('vendorStatusFilter');
    if (statusFilter) {
      statusFilter.addEventListener('change', filterAndRenderVendors);
    }

    const refreshBtn = el('refreshVendorsBtn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', loadData);
    }

    // Auto-load when switching to vendors tab
    document.querySelectorAll('#mainTabs .tab').forEach(tab => {
      tab.addEventListener('click', () => {
        if (tab.dataset.view === 'vendors') {
          loadData();
        }
      });
    });

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
    const saveVendorProfileBtn = el('saveVendorProfileBtn');

    if (closeEditVendorBtn) closeEditVendorBtn.addEventListener('click', hideEditVendorModal);
    if (cancelEditVendorBtn) cancelEditVendorBtn.addEventListener('click', hideEditVendorModal);
    if (editVendorForm) editVendorForm.addEventListener('submit', handleSaveVendorProfile);
    if (saveVendorProfileBtn) saveVendorProfileBtn.addEventListener('click', handleSaveVendorProfile);

    // Add Vendor Modal Event Listeners
    const openAddVendorBtn = el('openAddVendorModalBtn');
    const closeAddVendorBtn = el('closeAddVendorModalBtn');
    const cancelAddVendorBtn = el('cancelAddVendorModalBtn');
    const cancelBulkVendorBtn = el('cancelBulkVendorModalBtn');
    const addSingleVendorTab = el('addSingleVendorTabBtn');
    const addBulkVendorTab = el('addBulkVendorTabBtn');
    const singleVendorForm = el('addVendorForm');
    const bulkVendorForm = el('bulkVendorForm');
    const saveAddVendorBtn = el('saveAddVendorBtn');
    const uploadBulkVendorBtn = el('uploadBulkVendorBtn');
    const downloadTemplateBtn = el('downloadVendorTemplateBtn');
    const downloadTemplateXlsxBtn = el('downloadVendorTemplateXlsxBtn');

    if (openAddVendorBtn) openAddVendorBtn.addEventListener('click', openAddVendorModal);
    if (closeAddVendorBtn) closeAddVendorBtn.addEventListener('click', hideAddVendorModal);
    if (cancelAddVendorBtn) cancelAddVendorBtn.addEventListener('click', hideAddVendorModal);
    if (cancelBulkVendorBtn) cancelBulkVendorBtn.addEventListener('click', hideAddVendorModal);
    if (addSingleVendorTab) addSingleVendorTab.addEventListener('click', () => switchAddVendorTab('single'));
    if (addBulkVendorTab) addBulkVendorTab.addEventListener('click', () => switchAddVendorTab('bulk'));
    if (singleVendorForm) singleVendorForm.addEventListener('submit', handleCreateSingleVendorSubmit);
    if (saveAddVendorBtn) saveAddVendorBtn.addEventListener('click', handleCreateSingleVendorSubmit);
    if (bulkVendorForm) bulkVendorForm.addEventListener('submit', handleUploadBulkVendorsSubmit);
    if (downloadTemplateBtn) downloadTemplateBtn.addEventListener('click', downloadVendorTemplate);
    if (downloadTemplateXlsxBtn) downloadTemplateXlsxBtn.addEventListener('click', downloadVendorTemplateXlsx);

    // Auto-fill ID with last 5 digits of account number
    const addAcctInput = el('addVendorAccount');
    const addRefInput = el('addVendorRef');
    if (addAcctInput && addRefInput) {
      addAcctInput.addEventListener('input', () => {
        const cleanAcct = addAcctInput.value.replace(/\D/g, '');
        if (cleanAcct.length >= 5 && (!addRefInput.dataset.manuallyEdited || !addRefInput.value)) {
          addRefInput.value = cleanAcct.slice(-5);
        }
      });
      addRefInput.addEventListener('input', () => {
        addRefInput.dataset.manuallyEdited = 'true';
      });
    }

    // Live ABA Routing Number Checksum Validation
    const addRoutingInput = el('addVendorRouting');
    if (addRoutingInput) {
      addRoutingInput.addEventListener('input', () => {
        const val = addRoutingInput.value.replace(/\D/g, '');
        if (val.length === 9) {
          const d = val.split('').map(Number);
          const checksum = (3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7]) + 1 * (d[2] + d[5] + d[8])) % 10;
          if (checksum === 0) {
            addRoutingInput.style.borderColor = '#16a34a';
            addRoutingInput.title = 'Valid 9-digit ABA Routing Number';
          } else {
            addRoutingInput.style.borderColor = '#dc2626';
            addRoutingInput.title = 'Invalid ABA routing number checksum';
          }
        } else {
          addRoutingInput.style.borderColor = '';
          addRoutingInput.title = '';
        }
      });
    }

    // Duplicate Single Vendor Confirmation Modal Listeners
    const closeDupModalBtn = el('closeDupConfirmModalBtn');
    const cancelDupModalBtn = el('cancelDupConfirmModalBtn');
    const executeDupUpdateBtn = el('executeDupUpdateBtn');

    if (closeDupModalBtn) closeDupModalBtn.addEventListener('click', hideDupConfirmModal);
    if (cancelDupModalBtn) cancelDupModalBtn.addEventListener('click', hideDupConfirmModal);
    if (executeDupUpdateBtn) executeDupUpdateBtn.addEventListener('click', executeSingleVendorDuplicateUpdate);

    // Bulk Vendor Diff Modal Listeners
    const closeBulkDiffBtn = el('closeBulkDiffModalBtn');
    const cancelBulkDiffBtn = el('cancelBulkDiffModalBtn');
    const executeBulkDiffConfirmBtn = el('executeBulkDiffConfirmBtn');

    if (closeBulkDiffBtn) closeBulkDiffBtn.addEventListener('click', hideBulkDiffModal);
    if (cancelBulkDiffBtn) cancelBulkDiffBtn.addEventListener('click', hideBulkDiffModal);
    if (executeBulkDiffConfirmBtn) executeBulkDiffConfirmBtn.addEventListener('click', executeBulkDiffConfirm);

    // Delete Vendor Event Listeners
    const selectAllCb = el('vendorSelectAllCb');
    const clearSelectionBtn = el('clearVendorSelectionBtn');
    const bulkDeleteBtn = el('bulkDeleteVendorsBtn');
    const closeDeleteBtn = el('closeDeleteModalBtn');
    const cancelDeleteBtn = el('cancelDeleteModalBtn');
    const executeDeleteBtn = el('executeDeleteVendorsBtn');

    if (selectAllCb) selectAllCb.addEventListener('change', handleSelectAllVendors);
    if (clearSelectionBtn) clearSelectionBtn.addEventListener('click', clearVendorSelection);
    if (bulkDeleteBtn) bulkDeleteBtn.addEventListener('click', openConfirmDeleteSelection);
    if (closeDeleteBtn) closeDeleteBtn.addEventListener('click', hideDeleteModal);
    if (cancelDeleteBtn) cancelDeleteBtn.addEventListener('click', hideDeleteModal);
    if (executeDeleteBtn) executeDeleteBtn.addEventListener('click', executeVendorDeletion);

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

    // Only derive a reference from the account number when this user actually received
    // the real one. For a non-administrator `account_number` arrives masked, e.g.
    // '•••••7465', and slicing that produced '•7465' -- which would then be saved as
    // the vendor's default reference and end up in the NACHA ID field.
    const canSeeBankDetails = vendor.bank_details_masked !== true;
    const derivedTail = (canSeeBankDetails && vendor.account_number && vendor.account_number.length >= 5)
      ? vendor.account_number.slice(-5)
      : '';
    const defaultIdVal = vendor.default_id_number || derivedTail;

    el('editVendorId').value = vendor.id;
    el('editVendorModalTitle').textContent = `Edit Vendor Profile — ${vendor.name}`;
    el('editVendorName').value = vendor.name;
    el('editVendorEmail').value = vendor.email || (`ap@${vendor.name.toLowerCase().replace(/[^a-z0-9]/g, '')}.com`);
    el('editVendorRef').value = defaultIdVal;
    if (el('editVendorStatus')) el('editVendorStatus').value = (vendor.is_active !== false) ? 'true' : 'false';

    if (el('editVendorError')) el('editVendorError').style.display = 'none';
    if (el('editVendorSuccess')) el('editVendorSuccess').style.display = 'none';

    if (el('editVendorProfileModal')) {
      el('editVendorProfileModal').classList.add('active');
      el('editVendorProfileModal').style.display = 'flex';
    }
  }

  function hideEditVendorModal() {
    if (el('editVendorProfileModal')) {
      el('editVendorProfileModal').classList.remove('active');
      el('editVendorProfileModal').style.display = 'none';
    }
  }

  async function handleSaveVendorProfile(e) {
    if (e) e.preventDefault();

    const vendorId = el('editVendorId').value;
    const name = el('editVendorName').value.trim();
    const email = el('editVendorEmail').value.trim();
    const ref = el('editVendorRef').value.trim();
    const is_active = el('editVendorStatus') ? (el('editVendorStatus').value === 'true') : true;

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
        is_active,
      });

      if (succBox) {
        succBox.textContent = 'Vendor profile updated successfully! Status and details saved.';
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
    if (el('addVendorModal')) {
      el('addVendorModal').classList.add('active');
      el('addVendorModal').style.display = 'flex';
    }
  }

  function hideAddVendorModal() {
    if (el('addVendorModal')) {
      el('addVendorModal').classList.remove('active');
      el('addVendorModal').style.display = 'none';
    }
  }

  function hideDupConfirmModal() {
    pendingSingleVendorPayload = null;
    const modal = el('duplicateVendorConfirmModal');
    if (modal) {
      modal.classList.remove('active');
      modal.style.display = 'none';
    }
  }

  async function executeSingleVendorDuplicateUpdate() {
    if (!pendingSingleVendorPayload) return;

    const spinner = el('dupUpdateSpinner');
    const btn = el('executeDupUpdateBtn');
    if (btn) btn.disabled = true;
    if (spinner) spinner.style.display = 'inline-block';

    try {
      await API.post('/vendors', {
        ...pendingSingleVendorPayload,
        allow_update: true,
        allow_bank_update: isAdmin(),
      });

      hideDupConfirmModal();
      hideAddVendorModal();
      await loadData();
    } catch (err) {
      alert(err.message || 'Failed to update existing vendor.');
    } finally {
      if (btn) btn.disabled = false;
      if (spinner) spinner.style.display = 'none';
    }
  }

  async function handleCreateSingleVendorSubmit(e) {
    if (e) e.preventDefault();

    const name = el('addVendorName') ? el('addVendorName').value.trim() : '';
    const routing_number = el('addVendorRouting') ? el('addVendorRouting').value.trim() : '';
    const account_number = el('addVendorAccount') ? el('addVendorAccount').value.trim() : '';
    const account_type = el('addVendorAccountType') ? el('addVendorAccountType').value : 'checking';
    const default_id_number = (el('addVendorRef') && el('addVendorRef').value.trim())
      ? el('addVendorRef').value.trim()
      : (account_number.length >= 5 ? account_number.slice(-5) : (account_number || null));
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

    const payload = {
      name,
      routing_number,
      account_number,
      account_type,
      default_id_number,
      email,
    };

    try {
      await API.post('/vendors', payload);

      hideAddVendorModal();
      await loadData();
    } catch (err) {
      const detailObj = (err.data && typeof err.data.detail === 'object') ? err.data.detail : null;
      if (err.status === 409 && detailObj && detailObj.duplicate) {
        if (detailObj.exact_match) {
          if (errBox) {
            errBox.textContent = detailObj.message || `Vendor '${name}' already exists with identical details in the Master Book.`;
            errBox.style.display = 'block';
          }
        } else {
          // Open duplicate confirm modal with field differences
          pendingSingleVendorPayload = payload;
          if (el('dupVendorNameDisplay')) el('dupVendorNameDisplay').textContent = detailObj.vendor_name || name;

          if (detailObj.same_bank_different_name) {
            if (el('dupConfirmModalTitle')) el('dupConfirmModalTitle').textContent = 'Bank Account Already Exists';
            if (el('dupConfirmAlert')) {
              el('dupConfirmAlert').className = 'alert alert-warning show';
              el('dupConfirmAlert').innerHTML = `<strong>⚠️ Existing Bank Account Detected:</strong> An existing vendor (<strong>${escapeHtml(detailObj.existing_vendor_name || detailObj.vendor_name || '')}</strong>) is already registered with this exact bank account. Do you want to update this existing vendor's name and details to <strong>${escapeHtml(detailObj.new_vendor_name || name || '')}</strong>?`;
            }
          } else {
            if (el('dupConfirmModalTitle')) el('dupConfirmModalTitle').textContent = 'Update Existing Vendor?';
            if (el('dupConfirmAlert')) {
              el('dupConfirmAlert').className = 'alert alert-warning show';
              el('dupConfirmAlert').innerHTML = `An existing record was found in the Vendor Book for <strong>${escapeHtml(detailObj.vendor_name || name)}</strong> with modified details.`;
            }
          }

          const changesContainer = el('dupChangesList');
          if (changesContainer && detailObj.changes) {
            const fieldLabels = {
              email: 'Email',
              default_id_number: 'Default Invoice Ref',
              name: 'Vendor Name',
              routing_number: 'ABA Routing Number',
              account_number: 'Account Number',
              account_type: 'Account Type',
            };

            changesContainer.innerHTML = Object.entries(detailObj.changes).map(([field, ch]) => {
              const label = fieldLabels[field] || field;
              return `<div style="padding: 4px 0; border-bottom: 1px dashed #E2E8F0;">
                • <strong>${label}:</strong> <span style="text-decoration: line-through; color: #94A3B8;">${ch.old}</span> → <strong style="color: #059669;">${ch.new}</strong>
              </div>`;
            }).join('');
          }

          const bankBox = el('dupBankWarningBox');
          if (bankBox) {
            if (detailObj.has_bank_change) {
              bankBox.style.display = 'block';
              if (!isAdmin()) {
                bankBox.textContent = 'Note: You are logged in as a Standard User. Only profile details (email/reference) will be updated. Banking details require Admin privileges or a Bank Change Request.';
              } else {
                bankBox.textContent = 'Admin Authorization: Overwriting banking details (routing/account) directly. This action is permanently logged in the audit trail.';
              }
            } else {
              bankBox.style.display = 'none';
            }
          }

          const dupModal = el('duplicateVendorConfirmModal');
          if (dupModal) {
            dupModal.classList.add('active');
            dupModal.style.display = 'flex';
          }
        }
      } else {
        if (errBox) {
          errBox.textContent = err.message || 'Failed to create vendor.';
          errBox.style.display = 'block';
        }
      }
    } finally {
      if (saveBtn) saveBtn.disabled = false;
      if (spinner) spinner.style.display = 'none';
    }
  }

  function downloadVendorTemplate() {
    const csvContent = [
      'Vendor Name,Routing Number,Account Number,Account Type,Invoice Ref,Email',
      'ACME SUPPLIES INC,021000021,11391039,checking,INV-1001,ap@acme.com',
      'BELGIUM DIA LLC,021000322,483110589481,checking,INV-1002,ap@belgium.com',
      'GLOBAL METALS INC,026013356,112233445566,checking,INV-1003,billing@globalmetals.com',
      'PRECISION TOOLS CORP,121000247,445566778899,savings,INV-1004,accounts@precisiontools.com',
    ].join('\r\n');

    triggerFileDownload('vendor_import_template.csv', csvContent, 'text/csv;charset=utf-8;');
  }

  function downloadVendorTemplateXlsx() {
    if (typeof XLSX === 'undefined') {
      downloadVendorTemplate();
      return;
    }

    const headers = ['Vendor Name', 'Routing Number', 'Account Number', 'Account Type', 'Invoice Ref', 'Email'];
    const rows = [
      ['ACME SUPPLIES INC', '021000021', '11391039', 'checking', 'INV-1001', 'ap@acme.com'],
      ['BELGIUM DIA LLC', '021000322', '483110589481', 'checking', 'INV-1002', 'ap@belgium.com'],
      ['GLOBAL METALS INC', '026013356', '112233445566', 'checking', 'INV-1003', 'billing@globalmetals.com'],
      ['PRECISION TOOLS CORP', '121000247', '445566778899', 'savings', 'INV-1004', 'accounts@precisiontools.com'],
    ];

    const wsData = [headers, ...rows];
    const ws = XLSX.utils.aoa_to_sheet(wsData);

    ws['!cols'] = [
      { wch: 26 }, // Vendor Name
      { wch: 18 }, // Routing Number
      { wch: 20 }, // Account Number
      { wch: 15 }, // Account Type
      { wch: 15 }, // Invoice Ref
      { wch: 30 }, // Email
    ];

    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, 'Vendor Directory');
    XLSX.writeFile(wb, 'vendor_import_template.xlsx');
  }

  function triggerFileDownload(filename, content, mimeType) {
    const blob = new Blob([content], { type: mimeType });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    link.setAttribute('href', url);
    link.setAttribute('download', filename);
    link.style.display = 'none';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }

  function hideBulkDiffModal() {
    cachedBulkPreviewData = null;
    const modal = el('bulkVendorDiffModal');
    if (modal) {
      modal.classList.remove('active');
      modal.style.display = 'none';
    }
  }

  async function handleUploadBulkVendorsSubmit(e) {
    if (e) e.preventDefault();

    const fileInput = el('bulkVendorFileInput');
    const errBox = el('addVendorError');
    const succBox = el('addVendorSuccess');
    const spinner = el('bulkVendorSpinner');
    const uploadBtn = el('uploadBulkVendorBtn');

    if (errBox) errBox.style.display = 'none';
    if (succBox) succBox.style.display = 'none';

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
      const preview = await API.postForm('/vendors/bulk-preview', formData);
      cachedBulkPreviewData = preview;

      // Populate counters
      if (el('bulkDiffNewCount')) el('bulkDiffNewCount').textContent = preview.new_count || 0;
      if (el('bulkDiffUpdateCount')) el('bulkDiffUpdateCount').textContent = preview.update_count || 0;
      if (el('bulkDiffUnchangedCount')) el('bulkDiffUnchangedCount').textContent = preview.unchanged_count || 0;
      if (el('bulkDiffErrorCount')) el('bulkDiffErrorCount').textContent = preview.error_count || 0;

      // Error banner
      const errorAlert = el('bulkDiffErrorAlert');
      if (errorAlert) {
        if (preview.errors && preview.errors.length > 0) {
          errorAlert.innerHTML = `<strong>${preview.errors.length} Row Validation Warning(s):</strong><br/>` +
            preview.errors.map(err => `Row ${err.row}: ${err.error}`).join('<br/>');
          errorAlert.style.display = 'block';
        } else {
          errorAlert.style.display = 'none';
        }
      }

      // Render Diff Table
      const tbody = el('bulkDiffTableBody');
      const modSubtext = el('bulkDiffModSubtext');
      if (tbody) {
        tbody.innerHTML = '';
        if (preview.updated_vendors && preview.updated_vendors.length > 0) {
          if (modSubtext) modSubtext.textContent = `${preview.updated_vendors.length} vendor(s) have updated details`;
          preview.updated_vendors.forEach(uv => {
            const changes = uv.changes || {};
            const fieldLabels = {
              email: 'Email',
              default_id_number: 'Invoice Ref',
              name: 'Vendor Name',
              routing_number: 'ABA Routing',
              account_number: 'Account Number',
              account_type: 'Account Type',
            };

            Object.entries(changes).forEach(([field, ch]) => {
              const tr = document.createElement('tr');
              tr.style.borderBottom = '1px solid #E2E8F0';
              const isBank = ['routing_number', 'account_number', 'account_type'].includes(field);
              let badge = isBank
                ? `<span class="badge badge-danger" style="font-size: 10px;">Bank Detail</span>`
                : `<span class="badge badge-primary" style="font-size: 10px;">Profile</span>`;

              if (uv.same_bank_different_name && field === 'name') {
                badge = `<span class="badge badge-warning" style="font-size: 10px;" title="This bank account matches existing vendor ${escapeHtml(uv.vendor_name)}">⚠️ Existing Bank Account</span>`;
              }

              tr.innerHTML = `
                <td style="padding: 6px 10px;"><strong>${escapeHtml(uv.vendor_name)}</strong></td>
                <td style="padding: 6px 10px; font-weight: 500;">${fieldLabels[field] || field}</td>
                <td style="padding: 6px 10px; font-family: monospace; color: #64748B;">${ch.old}</td>
                <td style="padding: 6px 10px; font-family: monospace; color: #059669; font-weight: bold;">${ch.new}</td>
                <td style="padding: 6px 10px; text-align: center;">${badge}</td>
              `;
              tbody.appendChild(tr);
            });
          });
        } else {
          if (modSubtext) modSubtext.textContent = 'No modifications to existing vendors detected';
          tbody.innerHTML = `
            <tr>
              <td colspan="5" class="text-center text-muted" style="padding: 16px;">
                All matching existing vendors have identical details. ${preview.new_count} new vendor(s) ready to insert.
              </td>
            </tr>
          `;
        }
      }

      // Bank update options
      const hasAnyBankChange = preview.updated_vendors && preview.updated_vendors.some(uv => uv.has_bank_change);
      const bankSec = el('bulkDiffBankSection');
      const allowBankCb = el('bulkDiffAllowBankCb');
      if (allowBankCb) allowBankCb.checked = false;

      if (bankSec) {
        if (hasAnyBankChange && isAdmin()) {
          bankSec.style.display = 'block';
        } else {
          bankSec.style.display = 'none';
        }
      }

      // Update button text
      const confirmBtnText = el('bulkDiffConfirmBtnText');
      if (confirmBtnText) {
        confirmBtnText.textContent = `Confirm & Apply (${preview.new_count} New, ${preview.update_count} Updates)`;
      }

      // Open diff modal
      const diffModal = el('bulkVendorDiffModal');
      if (diffModal) {
        diffModal.classList.add('active');
        diffModal.style.display = 'flex';
      }
    } catch (err) {
      if (errBox) {
        errBox.textContent = err.message || 'Failed to analyze vendor spreadsheet.';
        errBox.style.display = 'block';
      }
    } finally {
      if (uploadBtn) uploadBtn.disabled = false;
      if (spinner) spinner.style.display = 'none';
    }
  }

  async function executeBulkDiffConfirm() {
    if (!cachedBulkPreviewData) return;

    const applyUpdates = el('bulkDiffApplyUpdatesCb') ? el('bulkDiffApplyUpdatesCb').checked : true;
    const allowBankUpdates = el('bulkDiffAllowBankCb') ? el('bulkDiffAllowBankCb').checked : false;

    const spinner = el('bulkDiffSpinner');
    const confirmBtn = el('executeBulkDiffConfirmBtn');

    if (confirmBtn) confirmBtn.disabled = true;
    if (spinner) spinner.style.display = 'inline-block';

    try {
      const result = await API.post('/vendors/bulk-confirm', {
        new_vendors: cachedBulkPreviewData.new_vendors || [],
        updated_vendors: cachedBulkPreviewData.updated_vendors || [],
        apply_updates: applyUpdates,
        allow_bank_updates: allowBankUpdates && isAdmin(),
      });

      hideBulkDiffModal();
      hideAddVendorModal();
      await loadData();
      const alertBox = el('vendorListAlert');
      if (alertBox) {
        alertBox.className = 'alert alert-success show';
        alertBox.textContent = result.message || 'Bulk vendor import and update completed successfully.';
        alertBox.style.display = 'block';
        setTimeout(() => { alertBox.style.display = 'none'; }, 5000);
      }
    } catch (err) {
      alert(err.message || 'Failed to apply bulk vendor import.');
    } finally {
      if (confirmBtn) confirmBtn.disabled = false;
      if (spinner) spinner.style.display = 'none';
    }
  }

  async function handleDeduplicateVendors() {
    if (!isAdmin()) {
      alert('Only administrators can perform database vendor deduplication.');
      return;
    }

    const btn = el('deduplicateVendorsBtn');
    const spinner = el('dedupSpinner');
    const alertBox = el('vendorListAlert');

    if (btn) btn.disabled = true;
    if (spinner) spinner.style.display = 'inline-block';

    try {
      const res = await API.post('/vendors/deduplicate', {});
      await loadData();
      if (alertBox) {
        alertBox.className = 'alert alert-success show';
        alertBox.textContent = res.message || 'Vendor deduplication completed successfully.';
        alertBox.style.display = 'block';
        setTimeout(() => { alertBox.style.display = 'none'; }, 6000);
      }
    } catch (err) {
      if (alertBox) {
        alertBox.className = 'alert alert-error show';
        alertBox.textContent = err.message || 'Failed to deduplicate vendors.';
        alertBox.style.display = 'block';
        setTimeout(() => { alertBox.style.display = 'none'; }, 6000);
      }
    } finally {
      if (btn) btn.disabled = false;
      if (spinner) spinner.style.display = 'none';
    }
  }

  // ── Selection & Deletion Management ─────────────────────────
  function getFilteredVendors() {
    const searchInput = el('vendorSearchInput');
    const term = searchInput ? searchInput.value.trim().toLowerCase() : '';
    const statusFilter = el('vendorStatusFilter') ? el('vendorStatusFilter').value : 'all';

    const rawFiltered = loadedVendors.filter(v => {
      const matchesSearch = !term ||
        (v.name && v.name.toLowerCase().includes(term)) ||
        (v.routing_number && v.routing_number.includes(term)) ||
        (v.account_number && v.account_number.includes(term)) ||
        (v.email && v.email.toLowerCase().includes(term));

      let matchesStatus = true;
      if (statusFilter === 'active') {
        matchesStatus = (v.is_active !== false);
      } else if (statusFilter === 'inactive') {
        matchesStatus = (v.is_active === false);
      }

      return matchesSearch && matchesStatus;
    });

    // Defensive UI deduplication: consolidate records with matching normalized names
    const seenNames = new Set();
    const deduplicated = [];
    for (const v of rawFiltered) {
      const normName = (v.name || '').trim().toUpperCase();
      if (!seenNames.has(normName)) {
        seenNames.add(normName);
        deduplicated.push(v);
      }
    }
    return deduplicated;
  }

  function updateBulkDeleteBar() {
    const bar = el('vendorBulkActionBar');
    const countText = el('vendorSelectedCountText');
    const deleteBtn = el('bulkDeleteVendorsBtn');

    if (!bar) return;

    if (isAdmin() && selectedVendorIds.size > 0) {
      bar.style.display = 'block';
      if (countText) countText.textContent = `${selectedVendorIds.size} Vendor(s) Selected`;
      if (deleteBtn) {
        const btnSpan = deleteBtn.querySelector('span:not(.spinner)');
        if (btnSpan) btnSpan.textContent = `🗑 Delete Selected Vendors (${selectedVendorIds.size})`;
      }
    } else {
      bar.style.display = 'none';
    }
  }

  function clearVendorSelection() {
    selectedVendorIds.clear();
    const selectAllCb = el('vendorSelectAllCb');
    if (selectAllCb) selectAllCb.checked = false;
    document.querySelectorAll('.vendor-select-cb').forEach(cb => cb.checked = false);
    updateBulkDeleteBar();
  }

  function handleSelectAllVendors(e) {
    const isChecked = e.target.checked;
    const currentFiltered = getFilteredVendors();
    if (isChecked) {
      currentFiltered.forEach(v => selectedVendorIds.add(v.id));
    } else {
      currentFiltered.forEach(v => selectedVendorIds.delete(v.id));
    }
    document.querySelectorAll('.vendor-select-cb').forEach(cb => {
      cb.checked = isChecked;
    });
    updateBulkDeleteBar();
  }

  function toggleVendorSelection(vendorId, isChecked) {
    if (isChecked) {
      selectedVendorIds.add(vendorId);
    } else {
      selectedVendorIds.delete(vendorId);
    }
    updateBulkDeleteBar();
  }

  function openConfirmDeleteSingle(vendorId) {
    const v = loadedVendors.find(item => item.id === vendorId);
    if (!v) return;
    vendorsToDelete = [v];
    showDeleteConfirmationModal();
  }

  function openConfirmDeleteSelection() {
    if (selectedVendorIds.size === 0) return;
    vendorsToDelete = loadedVendors.filter(v => selectedVendorIds.has(v.id));
    showDeleteConfirmationModal();
  }

  function showDeleteConfirmationModal() {
    const modal = el('confirmDeleteVendorModal');
    const msgEl = el('confirmDeleteMessage');
    const listEl = el('deleteVendorsListText');

    if (!modal) return;

    if (msgEl) {
      msgEl.textContent = vendorsToDelete.length === 1
        ? `Are you sure you want to permanently delete vendor "${vendorsToDelete[0].name}" from the database?`
        : `Are you sure you want to permanently delete ${vendorsToDelete.length} selected vendor(s) from the database?`;
    }

    if (listEl) {
      listEl.innerHTML = vendorsToDelete.map(v => `• ${escapeHtml(v.name)} (Routing: ${v.routing_number}, Acct: ${maskAccount(v.account_number)})`).join('<br/>');
    }

    const cascadeCb = el('vendorDeleteCascadeCb');
    if (cascadeCb) cascadeCb.checked = false;

    modal.classList.add('active');
    modal.style.display = 'flex';
  }

  function hideDeleteModal() {
    const modal = el('confirmDeleteVendorModal');
    if (modal) {
      modal.classList.remove('active');
      modal.style.display = 'none';
    }
  }

  async function executeVendorDeletion() {
    if (vendorsToDelete.length === 0) return;

    const spinner = el('executeDeleteSpinner');
    const executeBtn = el('executeDeleteVendorsBtn');

    if (executeBtn) executeBtn.disabled = true;
    if (spinner) spinner.style.display = 'inline-block';

    try {
      let res;
      if (vendorsToDelete.length === 1) {
        res = await API.del(`/vendors/${vendorsToDelete[0].id}`);
      } else {
        const vendor_ids = vendorsToDelete.map(v => v.id);
        res = await API.post('/vendors/bulk-delete', { vendor_ids });
      }

      hideDeleteModal();
      clearVendorSelection();
      await loadData();

      if (res && res.message) {
        const alertBox = el('vendorListAlert');
        if (alertBox) {
          alertBox.className = 'alert alert-success show';
          alertBox.textContent = res.message;
          alertBox.style.display = 'block';
          setTimeout(() => { alertBox.style.display = 'none'; }, 5000);
        }
      }
    } catch (err) {
      alert(err.message || 'Failed to delete vendor(s).');
    } finally {
      if (executeBtn) executeBtn.disabled = false;
      if (spinner) spinner.style.display = 'none';
    }
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
    const filtered = getFilteredVendors();

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
      const isInactive = v.is_active === false;
      const card = document.createElement('div');
      card.className = `card vendor-card ${isInactive ? 'vendor-inactive' : ''}`;
      card.setAttribute('data-vendor-id', v.id);
      if (isInactive) {
        card.style.opacity = '0.85';
        card.style.borderColor = '#cbd5e1';
      }

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

      const isChecked = selectedVendorIds.has(v.id);
      const vendorIdDisplay = (v.account_number && v.account_number.length >= 5)
        ? v.account_number.slice(-5)
        : (v.default_id_number || v.account_number || '—');

      const statusBadge = v.is_active === false
        ? '<span class="badge" style="background: var(--color-surface-alt, #f1f5f9); color: var(--color-text-muted, #64748b); border: 1px solid #cbd5e1;">Inactive</span>'
        : '<span class="badge badge-success">Active</span>';

      card.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: var(--space-sm);">
          <div style="display: flex; align-items: center; gap: var(--space-md);">
            ${isAdmin() ? `<input type="checkbox" class="vendor-select-cb" data-vendor-id="${v.id}" ${isChecked ? 'checked' : ''} onchange="VendorsScreen.toggleVendorSelection('${v.id}', this.checked)" style="cursor: pointer; width: 16px; height: 16px; flex-shrink: 0;" />` : ''}
            <div>
              <h4 style="margin: 0; font-size: var(--text-md); color: var(--color-primary);">${escapeHtml(v.name)}</h4>
              <div class="text-xs text-muted font-mono" style="margin-top: 2px;">ID: <strong>${vendorIdDisplay}</strong></div>
            </div>
          </div>
          ${statusBadge}
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-sm) var(--space-md); font-size: var(--text-xs); margin-bottom: var(--space-base);">
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
            <span class="font-mono text-xs" style="color: var(--color-primary);">${escapeHtml(v.email || 'ap@' + v.name.toLowerCase().replace(/[^a-z0-9]/g, '') + '.com')}</span>
          </div>
        </div>

        ${pendingNoticeHtml}

        <div style="margin-top: var(--space-md); display: flex; gap: var(--space-xs); justify-content: flex-end; flex-wrap: wrap;">
          <button type="button" class="btn btn-secondary btn-sm" onclick="VendorsScreen.openEditVendorModal('${v.id}')">
            Edit Profile
          </button>
          <button type="button" class="btn btn-secondary btn-sm req-change-btn" onclick="VendorsScreen.openChangeModal('${v.id}')">
            Request Bank Change
          </button>
          ${isAdmin() ? `
          <button type="button" class="btn btn-sm" onclick="VendorsScreen.openConfirmDeleteSingle('${v.id}')" style="background: #fef2f2; color: #dc2626; border: 1px solid #fecaca; padding: 4px 8px; font-weight: 600;" title="Delete Vendor (Admin Only)">
            🗑 Delete
          </button>` : ''}
        </div>
      `;

      const cb = card.querySelector('.vendor-select-cb');
      if (cb) {
        cb.addEventListener('change', (e) => toggleVendorSelection(v.id, e.target.checked));
      }

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
          <td colspan="8" style="padding: 24px; text-align: center; color: var(--color-text-muted);">
            No vendors found in directory.
          </td>
        </tr>
      `;
      return;
    }

    vendors.forEach((v, idx) => {
      const isInactive = v.is_active === false;
      const tr = document.createElement('tr');
      tr.style.borderBottom = '1px solid var(--border-color, #e2e8f0)';
      tr.style.background = idx % 2 === 0 ? 'var(--color-surface, #ffffff)' : 'var(--color-surface-alt, #f8fafc)';
      if (isInactive) {
        tr.style.opacity = '0.85';
      }

      const pendingReq = loadedChangeRequests.find(r =>
        String(r.vendor_id).toLowerCase() === String(v.id).toLowerCase() &&
        String(r.status).toLowerCase() === 'pending'
      );

      let statusBadge = isInactive
        ? '<span class="badge" style="background: var(--color-surface-alt, #f1f5f9); color: var(--color-text-muted, #64748b); border: 1px solid #cbd5e1;">Inactive</span>'
        : '<span class="badge badge-success">Active</span>';
      if (pendingReq) {
        statusBadge += ' <span class="badge badge-warning" title="Bank change request pending admin approval">Pending Change</span>';
      }

      const displayEmail = v.email || ('ap@' + v.name.toLowerCase().replace(/[^a-z0-9]/g, '') + '.com');
      const isChecked = selectedVendorIds.has(v.id);
      const vendorIdDisplay = (v.account_number && v.account_number.length >= 5)
        ? v.account_number.slice(-5)
        : (v.default_id_number || v.account_number || '—');

      tr.innerHTML = `
        <td style="padding: 12px 16px; text-align: center;">
          ${isAdmin() ? `<input type="checkbox" class="vendor-select-cb" data-vendor-id="${v.id}" ${isChecked ? 'checked' : ''} onchange="VendorsScreen.toggleVendorSelection('${v.id}', this.checked)" style="cursor: pointer;" />` : '—'}
        </td>
        <td style="padding: 12px 16px;">
          <strong style="color: var(--color-primary); font-size: var(--text-sm); display: block;">${escapeHtml(v.name)}</strong>
          <span class="text-xs text-muted font-mono" style="margin-top: 2px;">ID: <strong>${vendorIdDisplay}</strong></span>
        </td>
        <td style="padding: 12px 16px;" class="font-mono text-xs">${displayEmail}</td>
        <td style="padding: 12px 16px;" class="font-mono">${v.routing_number}</td>
        <td style="padding: 12px 16px;" class="font-mono">${maskAccount(v.account_number)}</td>
        <td style="padding: 12px 16px;" class="font-mono">${(v.account_type || 'checking').toUpperCase()}</td>
        <td style="padding: 12px 16px;">${statusBadge}</td>
        <td style="padding: 12px 16px; text-align: right;">
          <div style="display: flex; gap: var(--space-xs); justify-content: flex-end; flex-wrap: wrap;">
            <button type="button" class="btn btn-secondary btn-sm" onclick="VendorsScreen.openEditVendorModal('${v.id}')">
              Edit Profile
            </button>
            <button type="button" class="btn btn-secondary btn-sm" onclick="VendorsScreen.openChangeModal('${v.id}')">
              Request Bank Change
            </button>
            ${isAdmin() ? `
            <button type="button" class="btn btn-sm" onclick="VendorsScreen.openConfirmDeleteSingle('${v.id}')" style="background: #fef2f2; color: #dc2626; border: 1px solid #fecaca; padding: 4px 8px; font-weight: 600;" title="Delete Vendor (Admin Only)">
              🗑 Delete
            </button>` : ''}
          </div>
        </td>
      `;

      const cb = tr.querySelector('.vendor-select-cb');
      if (cb) {
        cb.addEventListener('change', (e) => toggleVendorSelection(v.id, e.target.checked));
      }

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
    el('changeRequestModal').style.display = 'flex';
  }

  function hideModal() {
    el('changeRequestModal').classList.remove('active');
    el('changeRequestModal').style.display = 'none';
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
    openAddVendorModal,
    hideAddVendorModal,
    openConfirmDeleteSingle,
    openConfirmDeleteSelection,
    executeBulkDiffConfirm,
    executeSingleVendorDuplicateUpdate,
    executeVendorDeletion,
    hideBulkDiffModal,
    hideDupConfirmModal,
    hideDeleteModal,
    handleDeduplicateVendors,
    toggleVendorSelection,
  };
})();

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => { VendorsScreen.init(); });
} else {
  VendorsScreen.init();
}
