/**
 * AMIPI NACHA ACH Payment System — Generate File & Upload Controller
 *
 * Handles file header inputs, drag-and-drop spreadsheet upload (Batch 1),
 * manual payment entry form (Batch 2), parsing response handling,
 * validation error rendering, duplicate detection with explicit override,
 * and combined NACHA file generation & text file downloading.
 */

const GenerateScreen = (() => {
  let currentFile = null;
  let lastUploadResponse = null;
  let loadedVendors = [];
  let b1ManualDraftEntries = [];
  let manualDraftEntries = [];
  let currentRenderedBatch1Payments = [];

  let batch1Id = null;
  let batch2Id = null;
  let generatedNachaRecord = null;

  function el(id) { return document.getElementById(id); }

  function init() {
    bindEvents();
    setDefaultEffectiveDate();
    loadVendors();
  }

  function setDefaultEffectiveDate() {
    const effInput = el('effDate');
    const b1ManualEffDate = el('b1ManualEffDate');
    const manualEffDate = el('manualEffDate');

    const d = new Date();
    d.setDate(d.getDate() + 1);
    if (d.getDay() === 6) d.setDate(d.getDate() + 2); // Sat -> Mon
    if (d.getDay() === 0) d.setDate(d.getDate() + 1); // Sun -> Mon

    const yyyy = d.getFullYear();
    const mmStr = String(d.getMonth() + 1).padStart(2, '0');
    const ddStr = String(d.getDate()).padStart(2, '0');

    if (effInput && !effInput.value) {
      const yy = String(yyyy).slice(2);
      effInput.value = `${yy}${mmStr}${ddStr}`;
    }

    if (b1ManualEffDate && !b1ManualEffDate.value) {
      b1ManualEffDate.value = `${yyyy}-${mmStr}-${ddStr}`;
    }

    if (manualEffDate && !manualEffDate.value) {
      manualEffDate.value = `${yyyy}-${mmStr}-${ddStr}`;
    }
  }

  function updateDiscretionaryPreview() {
    const chaseAcctInput = el('chaseAcct');
    const discPrev = el('discPrev');
    if (!chaseAcctInput || !discPrev) return;
    const digits = chaseAcctInput.value.replace(/\D/g, '');
    discPrev.textContent = digits.padStart(20, '0');
  }

  function filterVendorDropdown(selectId, searchTerm = '') {
    const select = el(selectId);
    if (!select) return;

    const term = (searchTerm || '').trim().toLowerCase();
    const currentVal = select.value;

    select.innerHTML = '<option value="">-- Select Vendor --</option>';

    const activeVendors = loadedVendors.filter(v => v.is_active !== false);
    const filtered = activeVendors.filter(v => {
      if (!term) return true;
      const name = (v.name || '').toLowerCase();
      const refId = ((v.account_number && v.account_number.length >= 5) ? v.account_number.slice(-5) : (v.default_id_number || '')).toLowerCase();
      const routing = (v.routing_number || '').toLowerCase();
      const acct = (v.account_number || '').toLowerCase();
      const email = (v.email || '').toLowerCase();

      return name.includes(term) || refId.includes(term) || routing.includes(term) || acct.includes(term) || email.includes(term);
    });

    if (filtered.length === 0) {
      select.innerHTML = '<option value="">No matching vendors found</option>';
      return;
    }

    filtered.forEach(v => {
      const opt = document.createElement('option');
      opt.value = v.id;
      const vId = (v.account_number && v.account_number.length >= 5) ? v.account_number.slice(-5) : (v.default_id_number || '—');
      opt.textContent = `${v.name} (ID: ${vId}, Routing: ${v.routing_number})`;
      if (v.id === currentVal) {
        opt.selected = true;
      }
      select.appendChild(opt);
    });

    // If search term filtered to exactly 1 vendor, auto-select it
    if (term && filtered.length === 1) {
      select.value = filtered[0].id;
    }
  }

  async function loadVendors() {
    try {
      const vendors = await API.get('/vendors?include_inactive=false');
      loadedVendors = vendors || [];
      filterVendorDropdown('manualVendorSelect', '');
      filterVendorDropdown('b1ManualVendorSelect', '');
    } catch (err) {
      console.warn('Failed to load vendors for manual entry dropdown:', err);
    }
  }

  function bindEvents() {
    const dropZone = el('dropZone');
    const fileInput = el('fileInput');

    if (dropZone && fileInput) {
      dropZone.addEventListener('click', (e) => {
        if (e.target.closest('#removeFileBtn')) return;
        fileInput.click();
      });

      fileInput.addEventListener('change', (e) => {
        if (e.target.files && e.target.files[0]) {
          setFile(e.target.files[0]);
        }
      });

      ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
          e.preventDefault();
          e.stopPropagation();
          dropZone.classList.add('dragover');
        }, false);
      });

      ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
          e.preventDefault();
          e.stopPropagation();
          dropZone.classList.remove('dragover');
        }, false);
      });

      dropZone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        if (dt && dt.files && dt.files[0]) {
          setFile(dt.files[0]);
        }
      });
    }

    const uploadBtn = el('uploadBtn');
    if (uploadBtn) {
      uploadBtn.addEventListener('click', () => handleUpload(false));
    }

    const retryOverrideBtn = el('retryOverrideBtn');
    if (retryOverrideBtn) {
      retryOverrideBtn.addEventListener('click', () => handleUpload(true));
    }

    const removeBtn = el('removeFileBtn');
    if (removeBtn) {
      removeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        clearFile();
      });
    }

    // Live Chase Discretionary Data Preview Listener
    const chaseAcctInput = el('chaseAcct');
    if (chaseAcctInput) {
      chaseAcctInput.addEventListener('input', updateDiscretionaryPreview);
      updateDiscretionaryPreview();
    }

    // Batch 1 Mode Tabs
    const b1TabUploadBtn = el('batch1TabUploadBtn');
    const b1TabManualBtn = el('batch1TabManualBtn');
    if (b1TabUploadBtn) b1TabUploadBtn.addEventListener('click', () => switchBatch1Mode('upload'));
    if (b1TabManualBtn) b1TabManualBtn.addEventListener('click', () => switchBatch1Mode('manual'));

    // Batch 1 Manual Entry Form Listeners
    const addB1ManualBtn = el('addB1ManualEntryBtn');
    if (addB1ManualBtn) {
      addB1ManualBtn.addEventListener('click', handleAddB1ManualEntry);
    }

    const b1ManualVendorSelect = el('b1ManualVendorSelect');
    if (b1ManualVendorSelect) {
      b1ManualVendorSelect.addEventListener('change', () => {
        const idInput = el('b1ManualIdNumber');
        if (idInput) idInput.value = ''; // Keep blank for explicit mandatory user entry
      });
    }

    const b1SearchInput = el('b1ManualVendorSearchInput');
    const b1SearchBtn = el('b1ManualVendorSearchBtn');
    if (b1SearchInput) {
      b1SearchInput.addEventListener('input', () => {
        filterVendorDropdown('b1ManualVendorSelect', b1SearchInput.value);
      });
      b1SearchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          filterVendorDropdown('b1ManualVendorSelect', b1SearchInput.value);
          if (el('b1ManualVendorSelect')) el('b1ManualVendorSelect').focus();
        }
      });
    }
    if (b1SearchBtn) {
      b1SearchBtn.addEventListener('click', () => {
        const val = b1SearchInput ? b1SearchInput.value : '';
        filterVendorDropdown('b1ManualVendorSelect', val);
        if (el('b1ManualVendorSelect')) el('b1ManualVendorSelect').focus();
      });
    }

    const addManualBtn = el('addManualEntryBtn');
    if (addManualBtn) {
      addManualBtn.addEventListener('click', handleAddManualEntry);
    }

    const manualVendorSelect = el('manualVendorSelect');
    if (manualVendorSelect) {
      manualVendorSelect.addEventListener('change', () => {
        const idInput = el('manualIdNumber');
        if (idInput) idInput.value = ''; // Keep blank for explicit mandatory user entry
      });
    }

    const manualSearchInput = el('manualVendorSearchInput');
    const manualSearchBtn = el('manualVendorSearchBtn');
    if (manualSearchInput) {
      manualSearchInput.addEventListener('input', () => {
        filterVendorDropdown('manualVendorSelect', manualSearchInput.value);
      });
      manualSearchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          filterVendorDropdown('manualVendorSelect', manualSearchInput.value);
          if (el('manualVendorSelect')) el('manualVendorSelect').focus();
        }
      });
    }
    if (manualSearchBtn) {
      manualSearchBtn.addEventListener('click', () => {
        const val = manualSearchInput ? manualSearchInput.value : '';
        filterVendorDropdown('manualVendorSelect', val);
        if (el('manualVendorSelect')) el('manualVendorSelect').focus();
      });
    }

    const manualRetryOverrideBtn = el('manualRetryOverrideBtn');
    if (manualRetryOverrideBtn) {
      manualRetryOverrideBtn.addEventListener('click', () => handleSubmitManualBatch(true));
    }

    // Generate Combined NACHA File Button
    const generateNachaBtn = el('generateNachaBtn');
    if (generateNachaBtn) {
      generateNachaBtn.addEventListener('click', handleGenerateNacha);
    }

    // Download NACHA File Button
    const downloadNachaBtn = el('downloadNachaBtn');
    if (downloadNachaBtn) {
      downloadNachaBtn.addEventListener('click', handleDownloadNacha);
    }

    // Copy NACHA Text Button
    const copyNachaBtn = el('copyNachaBtn');
    if (copyNachaBtn) {
      copyNachaBtn.addEventListener('click', handleCopyNachaText);
    }

    // Edit Payment Row Modal Listeners
    const closeEditModalBtn = el('closeEditPaymentModalBtn');
    const cancelEditModalBtn = el('cancelEditPaymentModalBtn');
    const editForm = el('editPaymentRowForm');

    if (closeEditModalBtn) closeEditModalBtn.addEventListener('click', hideEditRowModal);
    if (cancelEditModalBtn) cancelEditModalBtn.addEventListener('click', hideEditRowModal);
    // Breakdown Modal Listeners
    const closeBreakdownBtn = el('closeBreakdownModalBtn');
    const cancelBreakdownBtn = el('cancelBreakdownModalBtn');
    if (closeBreakdownBtn) closeBreakdownBtn.addEventListener('click', hideBreakdownModal);
    if (cancelBreakdownBtn) cancelBreakdownBtn.addEventListener('click', hideBreakdownModal);
  }

  return {
    init,
    handleUpload,
    loadVendors,
    switchBatch1Mode,
    handleAddB1ManualEntry,
    removeB1ManualEntry,
    handleSubmitB1ManualBatch,
    removeManualEntry,
    handleSubmitManualBatch,
    handleGenerateNacha,
    handleDownloadNacha,
    openEditRowModal,
    openBreakdownModal,
  };


  function openEditRowModal(idx) {
    if (!lastUploadResponse || !lastUploadResponse.valid_payments || !lastUploadResponse.valid_payments[idx]) return;
    const p = lastUploadResponse.valid_payments[idx];

    el('editPaymentIndex').value = idx;
    el('editPaymentId').value = p.payment_id || '';
    el('editPaymentVendorName').value = p.vendor_name || '';
    el('editPaymentAmount').value = parseFloat(p.amount || 0).toFixed(2);
    el('editPaymentRef').value = p.id_number || '';
    if (el('editPaymentModalError')) el('editPaymentModalError').style.display = 'none';

    el('editPaymentRowModal').classList.add('active');
    el('editPaymentRowModal').style.display = 'flex';
  }

  function hideEditRowModal() {
    el('editPaymentRowModal').classList.remove('active');
    el('editPaymentRowModal').style.display = 'none';
  }

  async function handleSaveEditPayment(e) {
    if (e) e.preventDefault();

    const idx = parseInt(el('editPaymentIndex').value, 10);
    const paymentId = el('editPaymentId').value;
    const newAmountVal = el('editPaymentAmount').value.trim();
    const newRefVal = el('editPaymentRef').value.trim();
    const errBox = el('editPaymentModalError');

    if (errBox) errBox.style.display = 'none';

    if (!newAmountVal || isNaN(newAmountVal) || parseFloat(newAmountVal) <= 0) {
      if (errBox) {
        errBox.textContent = 'Please enter a valid positive dollar amount.';
        errBox.style.display = 'block';
      }
      return;
    }

    if (!newRefVal) {
      if (errBox) {
        errBox.textContent = 'Invoice / Ref # is mandatory.';
        errBox.style.display = 'block';
      }
      return;
    }

    const p = lastUploadResponse.valid_payments[idx];
    const newAmount = parseFloat(newAmountVal);

    // Sync update to backend PostgreSQL if payment_id is present BEFORE updating UI
    if (paymentId) {
      try {
        await API.put(`/payments/${paymentId}`, {
          amount: newAmount,
          id_number: newRefVal,
        });
      } catch (err) {
        if (errBox) {
          errBox.textContent = err.message || 'Failed to update payment on backend server.';
          errBox.style.display = 'block';
        }
        return;
      }
    }

    p.amount = newAmount.toFixed(2);
    p.id_number = newRefVal;

    // Recalculate summary total amount
    let sumAmt = 0;
    lastUploadResponse.valid_payments.forEach(vp => {
      sumAmt += parseFloat(vp.amount || 0);
    });
    if (lastUploadResponse.summary) {
      lastUploadResponse.summary.total_amount = sumAmt.toFixed(2);
    }
    el('statTotalAmount').textContent = `$${sumAmt.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

    // Re-render table
    renderValidPaymentsTable(lastUploadResponse.valid_payments, 'validPaymentsTableBody');

    hideEditRowModal();
  }


  function setFile(file) {
    currentFile = file;
    el('selectedFileName').textContent = file.name;
    el('selectedFileSize').textContent = `(${formatBytes(file.size)})`;
    el('uploadFileInfo').style.display = 'flex';
    el('uploadZoneContent').style.display = 'none';
    el('uploadBtn').disabled = false;
    el('uploadGlobalError').style.display = 'none';
  }

  function clearFile() {
    currentFile = null;
    batch1Id = null;
    el('fileInput').value = '';
    el('uploadFileInfo').style.display = 'none';
    el('uploadZoneContent').style.display = 'block';
    el('uploadBtn').disabled = true;
    el('resultsSection').style.display = 'none';
    el('uploadGlobalError').style.display = 'none';
    checkNachaGenerateButtonState();
  }

  function formatBytes(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  }

  // ── Batch 1: Spreadsheet Upload ──────────────────────────────
  async function handleUpload(overrideFlag = false) {
    if (!currentFile) return;

    const formData = new FormData();
    formData.append('file', currentFile);
    formData.append('batch_number', '1');
    formData.append('allow_override', overrideFlag ? 'true' : 'false');

    const effVal = el('effDate').value.trim();
    if (effVal && effVal.length === 6) {
      const yyyy = '20' + effVal.substring(0, 2);
      const mm = effVal.substring(2, 4);
      const dd = effVal.substring(4, 6);
      formData.append('effective_date', `${yyyy}-${mm}-${dd}`);
    }

    setLoading(true);
    hideAlerts();

    try {
      const response = await API.postForm('/payments/upload', formData);
      lastUploadResponse = response;
      batch1Id = response.batch_id;
      renderUploadResults(response);
      checkNachaGenerateButtonState();
    } catch (err) {
      showGlobalError(err.message || 'Spreadsheet upload failed.');
    } finally {
      setLoading(false);
    }
  }

  function setLoading(loading) {
    const btn = el('uploadBtn');
    const spinner = el('uploadSpinner');
    if (btn) btn.disabled = loading || !currentFile;
    if (spinner) spinner.style.display = loading ? 'inline-block' : 'none';
  }

  function hideAlerts() {
    if (el('uploadGlobalError')) el('uploadGlobalError').style.display = 'none';
    if (el('duplicateBanner')) el('duplicateBanner').style.display = 'none';
    if (el('errorPanel')) el('errorPanel').style.display = 'none';
  }

  function showGlobalError(msg) {
    const errEl = el('uploadGlobalError');
    if (errEl) {
      errEl.textContent = msg;
      errEl.style.display = 'block';
    }
  }

  function renderUploadResults(data) {
    el('resultsSection').style.display = 'block';

    const summary = data.summary || {};
    const validPayments = data.valid_payments || [];
    const errors = data.errors || [];

    el('statTotalRows').textContent = summary.total_rows || 0;
    el('statValidRows').textContent = summary.valid_rows || validPayments.length;
    el('statErrorRows').textContent = summary.error_rows || errors.length;
    el('statTotalAmount').textContent = `$${parseFloat(summary.total_amount || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

    const hasDuplicateError = errors.some(e =>
      e.errors && e.errors.some(errStr => errStr.toLowerCase().includes('duplicate'))
    );

    if (hasDuplicateError) {
      el('duplicateBanner').style.display = 'block';
      el('overrideCheckbox').checked = false;
    } else {
      el('duplicateBanner').style.display = 'none';
    }

    if (errors.length > 0) {
      el('errorPanel').style.display = 'block';
      el('errorCountBadge').textContent = `${errors.length} issue(s)`;
      renderErrorsTable(errors, 'errorTableBody');
    } else {
      el('errorPanel').style.display = 'none';
    }

    renderValidPaymentsTable(validPayments, 'validPaymentsTableBody');
  }

  function renderErrorsTable(errors, tbodyId) {
    const tbody = el(tbodyId);
    if (!tbody) return;
    tbody.innerHTML = '';

    errors.forEach(err => {
      const tr = document.createElement('tr');
      const rawSnippet = err.raw_data
        ? Object.entries(err.raw_data).map(([k, v]) => `<b>${k}:</b> ${v}`).join(', ')
        : 'N/A';

      const errorMsgs = (err.errors || []).map(msg => {
        if (msg.toLowerCase().includes('duplicate')) {
          return `<span class="badge badge-warning">Duplicate Warning</span> ${msg}`;
        }
        return `<span class="badge badge-danger">Validation Error</span> ${msg}`;
      }).join('<br/>');

      tr.innerHTML = `
        <td class="font-mono">Row ${err.row_number}</td>
        <td style="font-size: var(--text-xs); color: var(--color-text-muted);">${rawSnippet}</td>
        <td>${errorMsgs}</td>
      `;
      tbody.appendChild(tr);
    });
  }

  function renderValidPaymentsTable(payments, tbodyId) {
    if (tbodyId === 'validPaymentsTableBody') {
      currentRenderedBatch1Payments = payments || [];
    }
    const tbody = el(tbodyId);
    if (!tbody) return;
    tbody.innerHTML = '';

    const isBatch2 = tbodyId === 'manualValidPaymentsTableBody';

    if (!payments || payments.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="8" class="text-center text-muted" style="padding: var(--space-xl);">
            No valid payment rows found in this batch.
          </td>
        </tr>
      `;
      return;
    }

    payments.forEach((p, idx) => {
      const tr = document.createElement('tr');
      const amtFormatted = `$${parseFloat(p.amount).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
      const dupBadge = p.is_duplicate_override
        ? `<span class="badge badge-warning">Override Duplicate</span>`
        : `<span class="badge badge-success">Valid</span>`;

      let breakdownBadge = '';
      if (p.invoice_breakdown && p.invoice_breakdown.length > 1) {
        breakdownBadge = `<button type="button" class="btn btn-secondary btn-sm" onclick="GenerateScreen.openBreakdownModal(${idx})" style="padding: 1px 6px; font-size: 10px; margin-left: 6px; vertical-align: middle;" title="View itemized price breakdown">
          <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-search" style="vertical-align: middle; margin-right: 3px;"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
          <span>${p.invoice_breakdown.length} Invoices</span>
        </button>`;
      }

      let actionBtn = '';
      if (isBatch2) {
        actionBtn = `<button type="button" class="btn btn-danger btn-sm" onclick="GenerateScreen.removeManualEntry(${idx})" style="padding: 2px 8px; font-size: var(--text-xs);">Remove</button>`;
      } else {
        actionBtn = `<button type="button" class="btn btn-secondary btn-sm" onclick="GenerateScreen.openEditRowModal(${idx})" style="padding: 2px 8px; font-size: var(--text-xs);">Edit</button>`;
      }

      tr.innerHTML = `
        <td class="font-mono">${idx + 1}</td>
        <td class="font-bold">${p.vendor_name}</td>
        <td class="font-mono">${p.routing_number || '—'}</td>
        <td class="font-mono">${p.account_number || '—'}</td>
        <td class="font-mono">${amtFormatted} ${breakdownBadge}</td>
        <td class="font-mono">${p.id_number || '—'}</td>
        <td>${dupBadge}</td>
        <td style="text-align: right;">${actionBtn}</td>
      `;
      tbody.appendChild(tr);
    });
  }

  function openBreakdownModal(idx) {
    const p = (currentRenderedBatch1Payments && currentRenderedBatch1Payments[idx])
      || (lastUploadResponse && lastUploadResponse.valid_payments && lastUploadResponse.valid_payments[idx]);
    if (!p || !p.invoice_breakdown || p.invoice_breakdown.length === 0) return;


    if (el('breakdownVendorTitle')) el('breakdownVendorTitle').textContent = `Invoice Breakdown — ${p.vendor_name}`;
    if (el('breakdownTotalSubtitle')) el('breakdownTotalSubtitle').textContent = `Total Payment Amount: $${parseFloat(p.amount).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} (${p.invoice_breakdown.length} Invoices)`;

    const tbody = el('breakdownTableBody');
    if (tbody) {
      tbody.innerHTML = '';
      p.invoice_breakdown.forEach((item, i) => {
        const tr = document.createElement('tr');
        tr.style.borderBottom = '1px solid var(--border-color, #e2e8f0)';
        const amtStr = item.amount !== null && item.amount !== undefined
          ? `$${parseFloat(item.amount).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
          : '—';

        tr.innerHTML = `
          <td style="padding: 8px 12px;" class="font-mono">${i + 1}</td>
          <td style="padding: 8px 12px;" class="font-mono font-bold">${item.invoice_number || '—'}</td>
          <td style="padding: 8px 12px;" class="font-mono text-muted">${item.invoice_date || '—'}</td>
          <td style="padding: 8px 12px; text-align: right;" class="font-mono">${amtStr}</td>
        `;
        tbody.appendChild(tr);
      });
    }

    const modal = el('invoiceBreakdownModal');
    if (modal) {
      modal.classList.add('active');
      modal.style.display = 'flex';
    }
  }

  function hideBreakdownModal() {
    const modal = el('invoiceBreakdownModal');
    if (modal) {
      modal.classList.remove('active');
      modal.style.display = 'none';
    }
  }




  // ── Batch 1: Mode Switch & Manual Payment Entry ───────────────
  function switchBatch1Mode(mode) {
    const uploadBtn = el('batch1TabUploadBtn');
    const manualBtn = el('batch1TabManualBtn');
    const uploadPanel = el('batch1UploadPanel');
    const manualPanel = el('batch1ManualPanel');

    if (mode === 'upload') {
      if (uploadBtn) {
        uploadBtn.classList.add('active');
        uploadBtn.classList.remove('btn-secondary');
      }
      if (manualBtn) {
        manualBtn.classList.remove('active');
        manualBtn.classList.add('btn-secondary');
      }
      if (uploadPanel) uploadPanel.style.display = 'block';
      if (manualPanel) manualPanel.style.display = 'none';
    } else {
      if (manualBtn) {
        manualBtn.classList.add('active');
        manualBtn.classList.remove('btn-secondary');
      }
      if (uploadBtn) {
        uploadBtn.classList.remove('active');
        uploadBtn.classList.add('btn-secondary');
      }
      if (uploadPanel) uploadPanel.style.display = 'none';
      if (manualPanel) manualPanel.style.display = 'block';
    }
  }

  async function handleAddB1ManualEntry() {
    const vendorSelect = el('b1ManualVendorSelect');
    const amtInput = el('b1ManualAmount');
    const idInput = el('b1ManualIdNumber');
    const dateInput = el('b1ManualEffDate');
    const errBox = el('b1ManualFormError');

    if (errBox) errBox.style.display = 'none';

    const vendorId = vendorSelect ? vendorSelect.value : '';
    const amountVal = amtInput ? amtInput.value.trim() : '';
    const idNum = idInput ? idInput.value.trim() : '';
    const effDate = dateInput ? dateInput.value.trim() : '';

    if (!vendorId) return showB1ManualError('Please select a vendor.');
    if (!amountVal || isNaN(amountVal) || parseFloat(amountVal) <= 0) return showB1ManualError('Payment Amount ($) is mandatory and must be greater than 0.');
    if (!idNum) return showB1ManualError('Invoice / Ref # is mandatory.');
    if (!effDate) return showB1ManualError('Effective Date is mandatory.');

    const vendorObj = loadedVendors.find(v => v.id === vendorId);
    if (!vendorObj) return showB1ManualError('Selected vendor is invalid.');

    b1ManualDraftEntries.push({
      vendor_id: vendorId,
      vendor_name: vendorObj.name,
      routing_number: vendorObj.routing_number,
      account_number: vendorObj.account_number,
      amount: parseFloat(amountVal).toFixed(2),
      id_number: idNum,
      effective_date: effDate,
    });

    const success = await handleSubmitB1ManualBatch(false);
    if (success) {
      if (el('b1ManualVendorSearchInput')) el('b1ManualVendorSearchInput').value = '';
      filterVendorDropdown('b1ManualVendorSelect', '');
      if (vendorSelect) vendorSelect.value = '';
      if (amtInput) amtInput.value = '';
      if (idInput) idInput.value = '';
      if (window.showToast) {
        window.showToast(`Payment for ${vendorObj.name} ($${parseFloat(amountVal).toFixed(2)}) validated & saved in Batch 1.`, 'success');
      }
    } else {
      b1ManualDraftEntries.pop();
    }
  }

  function showB1ManualError(msg) {
    const errBox = el('b1ManualFormError');
    if (errBox) {
      errBox.textContent = msg;
      errBox.style.display = 'block';
    }
  }

  async function removeB1ManualEntry(index) {
    if (index >= 0 && index < b1ManualDraftEntries.length) {
      const removed = b1ManualDraftEntries.splice(index, 1)[0];
      if (b1ManualDraftEntries.length === 0) {
        batch1Id = null;
        lastUploadResponse = null;
        if (el('resultsSection')) el('resultsSection').style.display = 'none';
        checkNachaGenerateButtonState();
        if (window.showToast) window.showToast('Removed all entries from Batch 1.', 'info');
      } else {
        await handleSubmitB1ManualBatch(false);
        if (window.showToast) window.showToast(`Removed entry for ${removed.vendor_name} from Batch 1.`, 'info');
      }
    }
  }

  async function handleSubmitB1ManualBatch(overrideFlag = false) {
    if (b1ManualDraftEntries.length === 0) return false;

    const payload = {
      batch_number: 1,
      filename: "Manual Batch 1",
      allow_override: overrideFlag,
      payments: b1ManualDraftEntries.map(e => ({
        vendor_id: e.vendor_id,
        amount: e.amount,
        id_number: e.id_number,
        effective_date: e.effective_date,
      }))
    };

    setB1ManualLoading(true);

    try {
      const response = await API.post('/payments/manual-batch', payload);
      batch1Id = response.batch_id;
      lastUploadResponse = response;
      renderUploadResults(response);
      checkNachaGenerateButtonState();
      return true;
    } catch (err) {
      showB1ManualError(err.message || 'Failed to submit and validate manual Batch 1 payments.');
      return false;
    } finally {
      setB1ManualLoading(false);
    }
  }

  function setB1ManualLoading(loading) {
    const btn = el('addB1ManualEntryBtn');
    const spinner = el('b1ManualBatchSpinner');
    if (btn) btn.disabled = loading;
    if (spinner) spinner.style.display = loading ? 'inline-block' : 'none';
  }

  // ── Batch 2: Manual Payment Entry ─────────────────────────────
  async function handleAddManualEntry() {
    const vendorSelect = el('manualVendorSelect');
    const amtInput = el('manualAmount');
    const idInput = el('manualIdNumber');
    const dateInput = el('manualEffDate');
    const errBox = el('manualFormError');

    if (errBox) errBox.style.display = 'none';

    const vendorId = vendorSelect ? vendorSelect.value : '';
    const amountVal = amtInput ? amtInput.value.trim() : '';
    const idNum = idInput ? idInput.value.trim() : '';
    const effDate = dateInput ? dateInput.value.trim() : '';

    if (!vendorId) return showManualError('Please select a vendor.');
    if (!amountVal || isNaN(amountVal) || parseFloat(amountVal) <= 0) return showManualError('Payment Amount ($) is mandatory and must be greater than 0.');
    if (!idNum) return showManualError('Invoice / Ref # is mandatory.');
    if (!effDate) return showManualError('Effective Date is mandatory.');

    const vendorObj = loadedVendors.find(v => v.id === vendorId);
    if (!vendorObj) return showManualError('Selected vendor is invalid.');

    manualDraftEntries.push({
      vendor_id: vendorId,
      vendor_name: vendorObj.name,
      routing_number: vendorObj.routing_number,
      account_number: vendorObj.account_number,
      amount: parseFloat(amountVal).toFixed(2),
      id_number: idNum,
      effective_date: effDate,
    });

    const success = await handleSubmitManualBatch(false);
    if (success) {
      if (el('manualVendorSearchInput')) el('manualVendorSearchInput').value = '';
      filterVendorDropdown('manualVendorSelect', '');
      if (vendorSelect) vendorSelect.value = '';
      if (amtInput) amtInput.value = '';
      if (idInput) idInput.value = '';
      if (window.showToast) {
        window.showToast(`Payment for ${vendorObj.name} ($${parseFloat(amountVal).toFixed(2)}) validated & saved in Batch 2.`, 'success');
      }
    } else {
      manualDraftEntries.pop();
    }
  }

  function showManualError(msg) {
    const errBox = el('manualFormError');
    if (errBox) {
      errBox.textContent = msg;
      errBox.style.display = 'block';
    }
  }

  async function removeManualEntry(index) {
    if (index >= 0 && index < manualDraftEntries.length) {
      const removed = manualDraftEntries.splice(index, 1)[0];
      if (manualDraftEntries.length === 0) {
        batch2Id = null;
        if (el('manualResultsSection')) el('manualResultsSection').style.display = 'none';
        checkNachaGenerateButtonState();
        if (window.showToast) window.showToast('Removed all entries from Batch 2.', 'info');
      } else {
        await handleSubmitManualBatch(false);
        if (window.showToast) window.showToast(`Removed entry for ${removed.vendor_name} from Batch 2.`, 'info');
      }
    }
  }

  async function handleSubmitManualBatch(overrideFlag = false) {
    if (manualDraftEntries.length === 0) return false;

    const payload = {
      batch_number: 2,
      filename: "Manual Batch 2",
      allow_override: overrideFlag,
      payments: manualDraftEntries.map(e => ({
        vendor_id: e.vendor_id,
        amount: e.amount,
        id_number: e.id_number,
        effective_date: e.effective_date,
      }))
    };

    setManualLoading(true);

    try {
      const response = await API.post('/payments/manual-batch', payload);
      batch2Id = response.batch_id;
      renderManualBatchResults(response);
      checkNachaGenerateButtonState();
      return true;
    } catch (err) {
      showManualError(err.message || 'Failed to submit and validate manual batch.');
      return false;
    } finally {
      setManualLoading(false);
    }
  }

  function setManualLoading(loading) {
    const btn = el('addManualEntryBtn');
    const spinner = el('manualBatchSpinner');
    if (btn) btn.disabled = loading;
    if (spinner) spinner.style.display = loading ? 'inline-block' : 'none';
  }

  function renderManualBatchResults(data) {
    el('manualResultsSection').style.display = 'block';

    const summary = data.summary || {};
    const validPayments = data.valid_payments || [];
    const errors = data.errors || [];

    el('manualStatTotalRows').textContent = summary.total_rows || 0;
    el('manualStatValidRows').textContent = summary.valid_rows || validPayments.length;
    el('manualStatErrorRows').textContent = summary.error_rows || errors.length;
    el('manualStatTotalAmount').textContent = `$${parseFloat(summary.total_amount || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

    const hasDuplicateError = errors.some(e =>
      e.errors && e.errors.some(errStr => errStr.toLowerCase().includes('duplicate'))
    );

    if (hasDuplicateError) {
      el('manualDuplicateBanner').style.display = 'block';
      if (el('manualOverrideCheckbox')) el('manualOverrideCheckbox').checked = false;
    } else {
      el('manualDuplicateBanner').style.display = 'none';
    }

    if (errors.length > 0) {
      el('manualErrorPanel').style.display = 'block';
      el('manualErrorCountBadge').textContent = `${errors.length} issue(s)`;
      renderErrorsTable(errors, 'manualErrorTableBody');
    } else {
      el('manualErrorPanel').style.display = 'none';
    }

    renderValidPaymentsTable(validPayments, 'manualValidPaymentsTableBody');
  }

  function checkNachaGenerateButtonState() {
    const btn = el('generateNachaBtn');
    if (!btn) return;
    const hasBatch1Valid = Boolean(batch1Id && lastUploadResponse && lastUploadResponse.valid_payments && lastUploadResponse.valid_payments.length > 0);
    const hasBatch2Valid = Boolean(batch2Id);
    btn.disabled = !(hasBatch1Valid || hasBatch2Valid);
  }

  // ── Phase 4: Combined NACHA File Generation & Download ──────
  async function handleGenerateNacha() {
    const batchIds = [];
    if (batch1Id) batchIds.push(batch1Id);
    if (batch2Id) batchIds.push(batch2Id);

    if (batchIds.length === 0) {
      showNachaError('Please upload Batch 1 (spreadsheet) or submit Batch 2 (manual entry) first.');
      return;
    }

    const coName = el('coName').value.trim() || 'AMIPI INC';
    const chaseAcct = el('chaseAcct').value.trim() || '785957066';
    const entryDesc = (el('entryDesc').value.trim() || 'EPAYMNT').toUpperCase();
    const effVal = el('effDate').value.trim();
    const fileIdMod = el('fileIdMod').value.trim() || 'A';
    const rawTraceStart = parseInt(el('traceStart').value.trim() || '0', 10);
    const traceStart = (!isNaN(rawTraceStart) && rawTraceStart > 0) ? rawTraceStart : null;

    if (entryDesc === 'PAYROLL' || entryDesc === 'REVERSAL') {
      showNachaError('Entry description cannot be PAYROLL or REVERSAL for Chase CCD credits.');
      return;
    }

    let effDateIso = null;
    if (effVal && effVal.length === 6) {
      effDateIso = `20${effVal.substring(0, 2)}-${effVal.substring(2, 4)}-${effVal.substring(4, 6)}`;
    }

    const payload = {
      batch_ids: batchIds,
      company_name: coName,
      company_account: chaseAcct,
      entry_description: entryDesc,
      effective_entry_date: effDateIso,
      file_id_modifier: fileIdMod,
      trace_sequence_start: traceStart,
    };


    setNachaLoading(true);
    if (el('nachaGlobalError')) el('nachaGlobalError').style.display = 'none';

    try {
      const response = await API.post('/nacha/generate', payload);
      generatedNachaRecord = response;
      renderNachaOutputCard(response);
    } catch (err) {
      showNachaError(err.message || 'Combined NACHA file generation failed.');
    } finally {
      setNachaLoading(false);
    }
  }

  function setNachaLoading(loading) {
    const btn = el('generateNachaBtn');
    const spinner = el('nachaSpinner');
    if (btn) btn.disabled = loading;
    if (spinner) spinner.style.display = loading ? 'inline-block' : 'none';
  }

  function showNachaError(msg) {
    const errBox = el('nachaGlobalError');
    if (errBox) {
      errBox.textContent = msg;
      errBox.style.display = 'block';
    }
  }

  function renderNachaOutputCard(data) {
    el('nachaOutputCard').style.display = 'block';
    el('nachaFilename').textContent = data.filename;
    el('nachaFileId').textContent = data.id;
    el('nachaEntryCount').textContent = data.total_entry_count;
    el('nachaBatchCount').textContent = data.total_batch_count;
    el('nachaBlockCount').textContent = data.total_block_count;
    el('nachaCreditTotal').textContent = `$${parseFloat(data.total_credit_amount).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    el('nachaEntryHash').textContent = data.entry_hash;
    el('nachaRawPreview').textContent = data.raw_content;

    // Scroll preview to top
    el('nachaOutputCard').scrollIntoView({ behavior: 'smooth' });
  }

  function handleDownloadNacha() {
    if (!generatedNachaRecord || !generatedNachaRecord.id) return;

    // Create a Blob from the raw content for clean browser download
    const blob = new Blob([generatedNachaRecord.raw_content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = generatedNachaRecord.filename || 'AMIPI_ACH_TRANSMIT.txt';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  function handleCopyNachaText() {
    if (!generatedNachaRecord || !generatedNachaRecord.raw_content) return;
    navigator.clipboard.writeText(generatedNachaRecord.raw_content).then(() => {
      const copyBtn = el('copyNachaBtn');
      if (copyBtn) {
        const origText = copyBtn.textContent;
        copyBtn.textContent = 'Copied to Clipboard!';
        setTimeout(() => { copyBtn.textContent = origText; }, 2000);
      }
    }).catch(err => {
      console.warn('Clipboard copy failed:', err);
    });
  }

  return {
    init,
    handleUpload,
    loadVendors,
    removeManualEntry,
    handleSubmitManualBatch,
    handleGenerateNacha,
    handleDownloadNacha,
    openEditRowModal,
    openBreakdownModal,
  };
})();

document.addEventListener('DOMContentLoaded', () => {
  GenerateScreen.init();
});
