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
  let lastBatch2Response = null;
  let currentEditBatchType = 'batch1';
  let batch2OverrideActive = false;
  let generatedNachaRecord = null;

  function el(id) { return document.getElementById(id); }

  function init() {
    initVendorComboboxes();
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

  let b1VendorCombobox = null;
  let manualVendorCombobox = null;

  function createSearchableVendorCombobox(config) {
    const {
      wrapperId,
      hiddenInputId,
      triggerId,
      labelId,
      clearBtnId,
      dropdownId,
      searchInputId,
      optionsId,
      onSelect,
    } = config;

    const wrapper = el(wrapperId);
    const hiddenInput = el(hiddenInputId);
    const trigger = el(triggerId);
    const label = el(labelId);
    const clearBtn = el(clearBtnId);
    const dropdown = el(dropdownId);
    const searchInput = el(searchInputId);
    const optionsContainer = el(optionsId);

    let isOpen = false;
    let vendors = [];
    let highlightedIndex = -1;

    function renderOptions(filterTerm = '') {
      if (!optionsContainer) return;
      optionsContainer.innerHTML = '';
      highlightedIndex = -1;

      const term = (filterTerm || '').trim().toLowerCase();
      const currentSelectedId = hiddenInput ? hiddenInput.value : '';

      const activeVendors = vendors.filter(v => v.is_active !== false);
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
        const noResults = document.createElement('div');
        noResults.className = 'custom-select-no-results';
        noResults.innerHTML = `
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/><path d="M8 11h6"/></svg>
          <div style="font-weight: 600; color: #475569;">No matching vendors found</div>
          <div style="font-size: 11px; color: #94a3b8;">Try searching by vendor name, routing #, or ID</div>
        `;
        optionsContainer.appendChild(noResults);
        return;
      }

      filtered.forEach((v, idx) => {
        const opt = document.createElement('div');
        const isSelected = String(v.id) === String(currentSelectedId);
        opt.className = 'custom-select-option' + (isSelected ? ' selected' : '');
        opt.setAttribute('data-index', idx);
        opt.setAttribute('role', 'option');

        const vId = (v.account_number && v.account_number.length >= 5) ? v.account_number.slice(-5) : (v.default_id_number || '—');
        const routing = v.routing_number || '—';
        const acctLast4 = (v.account_number && v.account_number.length >= 4) ? `****${v.account_number.slice(-4)}` : (v.account_number || '');

        opt.innerHTML = `
          <div class="custom-select-option-main">
            <span class="custom-select-option-name">${v.name}</span>
            <div class="custom-select-option-tags">
              <span class="custom-select-tag">ID: ${vId}</span>
              <span class="custom-select-tag">Routing: ${routing}</span>
              ${acctLast4 ? `<span class="custom-select-tag">Acct: ${acctLast4}</span>` : ''}
            </div>
          </div>
          ${isSelected ? `<svg class="custom-select-check" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M20 6 9 17l-5-5"/></svg>` : ''}
        `;

        opt.addEventListener('click', (e) => {
          e.stopPropagation();
          selectVendor(v);
        });

        optionsContainer.appendChild(opt);
      });
    }

    function selectVendor(vendor) {
      if (!vendor) {
        if (hiddenInput) hiddenInput.value = '';
        if (label) {
          label.textContent = '-- Select Vendor --';
          label.classList.add('placeholder');
        }
        if (wrapper) wrapper.classList.remove('has-value');
      } else {
        if (hiddenInput) hiddenInput.value = vendor.id;
        const vId = (vendor.account_number && vendor.account_number.length >= 5) ? vendor.account_number.slice(-5) : (vendor.default_id_number || '—');
        if (label) {
          label.textContent = `${vendor.name} (ID: ${vId}, Routing: ${vendor.routing_number})`;
          label.classList.remove('placeholder');
        }
        if (wrapper) wrapper.classList.add('has-value');
      }
      close();
      if (typeof onSelect === 'function') {
        onSelect(vendor);
      }
    }

    function open() {
      if (isOpen) return;
      document.querySelectorAll('.custom-select-dropdown').forEach(d => d.style.display = 'none');
      document.querySelectorAll('.custom-select-wrapper').forEach(w => w.classList.remove('open'));

      isOpen = true;
      if (dropdown) dropdown.style.display = 'block';
      if (wrapper) wrapper.classList.add('open');
      if (searchInput) {
        searchInput.value = '';
        renderOptions('');
        setTimeout(() => searchInput.focus(), 50);
      }
    }

    function close() {
      if (!isOpen) return;
      isOpen = false;
      if (dropdown) dropdown.style.display = 'none';
      if (wrapper) wrapper.classList.remove('open');
      highlightedIndex = -1;
    }

    function toggle() {
      if (isOpen) close();
      else open();
    }

    if (trigger) {
      trigger.addEventListener('click', (e) => {
        if (e.target.closest('.custom-select-clear-btn')) return;
        e.stopPropagation();
        toggle();
      });
      trigger.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          toggle();
        } else if (e.key === 'Escape') {
          close();
        }
      });
    }

    if (clearBtn) {
      clearBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        selectVendor(null);
      });
    }

    if (searchInput) {
      searchInput.addEventListener('input', () => {
        renderOptions(searchInput.value);
      });
      searchInput.addEventListener('click', (e) => {
        e.stopPropagation();
      });
      searchInput.addEventListener('keydown', (e) => {
        const optionEls = optionsContainer ? optionsContainer.querySelectorAll('.custom-select-option') : [];

        if (e.key === 'Escape') {
          close();
        } else if (e.key === 'ArrowDown') {
          e.preventDefault();
          if (optionEls.length > 0) {
            highlightedIndex = (highlightedIndex + 1) % optionEls.length;
            updateHighlight(optionEls);
          }
        } else if (e.key === 'ArrowUp') {
          e.preventDefault();
          if (optionEls.length > 0) {
            highlightedIndex = (highlightedIndex - 1 + optionEls.length) % optionEls.length;
            updateHighlight(optionEls);
          }
        } else if (e.key === 'Enter') {
          e.preventDefault();
          if (highlightedIndex >= 0 && optionEls[highlightedIndex]) {
            optionEls[highlightedIndex].click();
          } else if (optionEls.length > 0) {
            optionEls[0].click();
          }
        }
      });
    }

    function updateHighlight(optionEls) {
      optionEls.forEach((el, idx) => {
        if (idx === highlightedIndex) {
          el.classList.add('highlighted');
          el.scrollIntoView({ block: 'nearest' });
        } else {
          el.classList.remove('highlighted');
        }
      });
    }

    if (hiddenInput && hiddenInput.tagName === 'SELECT') {
      hiddenInput.addEventListener('change', () => {
        const found = vendors.find(v => String(v.id) === String(hiddenInput.value));
        selectVendor(found || null);
      });
    }

    document.addEventListener('click', (e) => {
      if (wrapper && !wrapper.contains(e.target)) {
        close();
      }
    });

    return {
      setVendors: (newVendors) => {
        vendors = newVendors || [];
        if (hiddenInput && hiddenInput.tagName === 'SELECT') {
          hiddenInput.innerHTML = '<option value="">-- Select Vendor --</option>' +
            vendors.map(v => `<option value="${v.id}">${v.name}</option>`).join('');
        }
        renderOptions('');
      },
      reset: () => {
        selectVendor(null);
        if (searchInput) searchInput.value = '';
        renderOptions('');
      },
      getValue: () => (hiddenInput ? hiddenInput.value : ''),
      setValue: (vendorId) => {
        const found = vendors.find(v => String(v.id) === String(vendorId));
        selectVendor(found || null);
      },
      close,
      open,
    };
  }

  function initVendorComboboxes() {
    b1VendorCombobox = createSearchableVendorCombobox({
      wrapperId: 'b1ManualVendorWrapper',
      hiddenInputId: 'b1ManualVendorSelect',
      triggerId: 'b1ManualVendorTrigger',
      labelId: 'b1ManualVendorLabel',
      clearBtnId: 'b1ManualVendorClearBtn',
      dropdownId: 'b1ManualVendorDropdown',
      searchInputId: 'b1ManualVendorSearchInput',
      optionsId: 'b1ManualVendorOptions',
      onSelect: () => {
        const idInput = el('b1ManualIdNumber');
        if (idInput) idInput.value = ''; // Always stay blank for explicit mandatory entry
      }
    });

    // Batch 2 vendor combobox is no longer needed — vendors are now inline per-row <select> elements
  }

  async function loadVendors() {
    try {
      const vendors = await API.get('/vendors?include_inactive=false');
      loadedVendors = vendors || [];
      if (b1VendorCombobox) b1VendorCombobox.setVendors(loadedVendors);
      // Render initial blank inline row for Batch 2
      renderManualInlineRows();
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

    // Batch 2 Inline Multi-Row Entry
    const addManualRowBtn = el('addManualRowBtn');
    if (addManualRowBtn) {
      addManualRowBtn.addEventListener('click', () => addManualInlineRow(2));
    }

    const submitManualBtn = el('submitManualBatchBtn');
    if (submitManualBtn) {
      submitManualBtn.addEventListener('click', () => handleSubmitManualBatch(batch2OverrideActive || false));
    }

    const manualOverrideCb = el('manualOverrideCheckbox');
    if (manualOverrideCb) {
      manualOverrideCb.addEventListener('change', () => {
        batch2OverrideActive = manualOverrideCb.checked;
      });
    }

    const manualRetryOverrideBtn = el('manualRetryOverrideBtn');
    if (manualRetryOverrideBtn) {
      manualRetryOverrideBtn.addEventListener('click', () => {
        batch2OverrideActive = true;
        if (el('manualOverrideCheckbox')) el('manualOverrideCheckbox').checked = true;
        handleSubmitManualBatch(true);
      });
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
    if (editForm) editForm.addEventListener('submit', handleSaveEditPayment);

    // Breakdown Modal Listeners
    const closeBreakdownBtn = el('closeBreakdownModalBtn');
    const cancelBreakdownBtn = el('cancelBreakdownModalBtn');
    if (closeBreakdownBtn) closeBreakdownBtn.addEventListener('click', hideBreakdownModal);
    if (cancelBreakdownBtn) cancelBreakdownBtn.addEventListener('click', hideBreakdownModal);
  }

  function openEditRowModal(idx, batchType = 'batch1') {
    currentEditBatchType = batchType;

    let p = null;
    if (batchType === 'batch2') {
      p = (lastBatch2Response && lastBatch2Response.valid_payments && lastBatch2Response.valid_payments[idx]) || manualDraftEntries[idx];
    } else {
      p = lastUploadResponse && lastUploadResponse.valid_payments && lastUploadResponse.valid_payments[idx];
    }

    if (!p) return;

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

    if (currentEditBatchType === 'batch2') {
      if (lastBatch2Response && lastBatch2Response.valid_payments && lastBatch2Response.valid_payments[idx]) {
        const p = lastBatch2Response.valid_payments[idx];
        p.amount = newAmount.toFixed(2);
        p.id_number = newRefVal;
      }
      if (manualDraftEntries[idx]) {
        manualDraftEntries[idx].amount = newAmount.toFixed(2);
        manualDraftEntries[idx].id_number = newRefVal;
      }

      // Recalculate summary total amount
      let sumAmt = 0;
      if (lastBatch2Response && lastBatch2Response.valid_payments) {
        lastBatch2Response.valid_payments.forEach(vp => {
          sumAmt += parseFloat(vp.amount || 0);
        });
        if (lastBatch2Response.summary) {
          lastBatch2Response.summary.total_amount = sumAmt.toFixed(2);
        }
      } else {
        sumAmt = manualDraftEntries.reduce((s, e) => s + (parseFloat(e.amount) || 0), 0);
      }
      if (el('manualStatTotalAmount')) {
        el('manualStatTotalAmount').textContent = `$${sumAmt.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
      }

      // Re-render Batch 2 valid payments table
      if (lastBatch2Response && lastBatch2Response.valid_payments) {
        renderValidPaymentsTable(lastBatch2Response.valid_payments, 'manualValidPaymentsTableBody');
      }
    } else {
      const p = lastUploadResponse.valid_payments[idx];
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

      // Re-render Batch 1 valid payments table
      renderValidPaymentsTable(lastUploadResponse.valid_payments, 'validPaymentsTableBody');
    }

    hideEditRowModal();
    if (window.showToast) window.showToast('Payment item updated successfully.', 'success');
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
        actionBtn = `
          <div style="display: flex; gap: 6px; justify-content: flex-end;">
            <button type="button" class="btn btn-secondary btn-sm" onclick="GenerateScreen.openEditRowModal(${idx}, 'batch2')" style="padding: 2px 8px; font-size: var(--text-xs);">Edit</button>
            <button type="button" class="btn btn-danger btn-sm" onclick="GenerateScreen.removeManualEntry(${idx})" style="padding: 2px 8px; font-size: var(--text-xs);">Remove</button>
          </div>
        `;
      } else {
        actionBtn = `<button type="button" class="btn btn-secondary btn-sm" onclick="GenerateScreen.openEditRowModal(${idx}, 'batch1')" style="padding: 2px 8px; font-size: var(--text-xs);">Edit</button>`;
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
    const amtInput = el('b1ManualAmount');
    const idInput = el('b1ManualIdNumber');
    const dateInput = el('b1ManualEffDate');
    const errBox = el('b1ManualFormError');

    if (errBox) errBox.style.display = 'none';

    const vendorId = b1VendorCombobox ? b1VendorCombobox.getValue() : (el('b1ManualVendorSelect') ? el('b1ManualVendorSelect').value : '');
    const amountVal = amtInput ? amtInput.value.trim() : '';
    const idNum = idInput ? idInput.value.trim() : '';
    const effDate = dateInput ? dateInput.value.trim() : '';

    if (!vendorId) return showB1ManualError('Please select a vendor.');
    if (!amountVal || isNaN(amountVal) || parseFloat(amountVal) <= 0) return showB1ManualError('Payment Amount ($) is mandatory and must be greater than 0.');
    if (!idNum) return showB1ManualError('Invoice / Ref # is mandatory.');
    if (!effDate) return showB1ManualError('Effective Date is mandatory.');

    const vendorObj = loadedVendors.find(v => String(v.id) === String(vendorId));
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
      if (b1VendorCombobox) b1VendorCombobox.reset();
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

  // ── Batch 2 & Multi-Batch Manual Payment Entry ──────────────────
  let manualBatches = [
    { batchNum: 2, rowCount: 1, overrideActive: false, dbBatchId: null }
  ];

  function getManualBatchObj(batchNum = 2) {
    const num = (typeof batchNum === 'number' && !isNaN(batchNum)) ? batchNum : (parseInt(batchNum, 10) || 2);
    let b = manualBatches.find(x => x.batchNum === num);
    if (!b) {
      b = { batchNum: num, rowCount: 1, overrideActive: false, dbBatchId: null };
      manualBatches.push(b);
    }
    return b;
  }

  function getBatchTbody(batchNum = 2) {
    const num = (typeof batchNum === 'number' && !isNaN(batchNum)) ? batchNum : (parseInt(batchNum, 10) || 2);
    return num === 2 ? el('manualInlineTableBody') : el(`manualInlineTableBody_${num}`);
  }

  function getBatchEffDateInput(batchNum = 2) {
    const num = (typeof batchNum === 'number' && !isNaN(batchNum)) ? batchNum : (parseInt(batchNum, 10) || 2);
    return num === 2 ? el('manualEffDate') : el(`manualEffDate_${num}`);
  }

  function getBatchErrorBox(batchNum = 2) {
    const num = (typeof batchNum === 'number' && !isNaN(batchNum)) ? batchNum : (parseInt(batchNum, 10) || 2);
    return num === 2 ? el('manualFormError') : el(`manualFormError_${num}`);
  }

  function getBatchDuplicateBanner(batchNum = 2) {
    const num = (typeof batchNum === 'number' && !isNaN(batchNum)) ? batchNum : (parseInt(batchNum, 10) || 2);
    return num === 2 ? el('manualDuplicateBanner') : el(`manualDuplicateBanner_${num}`);
  }

  function renderManualInlineRows(batchNum = 2) {
    const b = getManualBatchObj(batchNum);
    const tbody = getBatchTbody(batchNum);
    if (!tbody) return;

    // Collect existing values to preserve while expanding rows
    const existingRows = tbody.querySelectorAll('tr');
    const existingValues = [];
    existingRows.forEach(tr => {
      const vendorSel = tr.querySelector('.manual-row-vendor');
      const amtInput = tr.querySelector('.manual-row-amount');
      const refInput = tr.querySelector('.manual-row-ref');
      existingValues.push({
        vendor_id: vendorSel ? vendorSel.value : '',
        amount: amtInput ? amtInput.value : '',
        ref: refInput ? refInput.value : '',
      });
    });

    tbody.innerHTML = '';
    const vendorOptions = '<option value="">-- Select Vendor --</option>' +
      loadedVendors.map(v => `<option value="${v.id}">${v.name}</option>`).join('');

    for (let i = 0; i < b.rowCount; i++) {
      const tr = document.createElement('tr');
      tr.setAttribute('data-row-idx', i);
      const saved = existingValues[i] || { vendor_id: '', amount: '', ref: '' };
      const vendorObj = saved.vendor_id ? loadedVendors.find(v => String(v.id) === String(saved.vendor_id)) : null;

      tr.innerHTML = `
        <td class="font-mono" style="vertical-align: middle; text-align: center; color: var(--color-text-muted); font-size: 11px;">${i + 1}</td>
        <td style="padding: 4px 6px;">
          <select class="form-select manual-row-vendor" data-idx="${i}" style="width: 100%; padding: 4px 8px; font-size: 12px; height: 32px;">
            ${vendorOptions}
          </select>
        </td>
        <td class="font-mono manual-row-routing" style="vertical-align: middle; padding: 4px 6px; font-size: 11px; color: var(--color-text-muted);">
          ${vendorObj ? vendorObj.routing_number : '—'}
        </td>
        <td class="font-mono manual-row-account" style="vertical-align: middle; padding: 4px 6px; font-size: 11px; color: var(--color-text-muted);">
          ${vendorObj ? (vendorObj.account_number || '••••••') : '—'}
        </td>
        <td class="manual-row-type" style="vertical-align: middle; padding: 4px 6px; font-size: 11px;">
          ${vendorObj ? `<span class="badge badge-neutral" style="font-size: 10px; text-transform: capitalize;">${vendorObj.account_type || 'Checking'}</span>` : '—'}
        </td>
        <td style="padding: 4px 6px;">
          <input type="number" class="form-input manual-row-amount" data-idx="${i}" step="0.01" placeholder="0.00" style="width: 100%; padding: 4px 8px; font-size: 12px; height: 32px;" value="${saved.amount}" />
        </td>
        <td style="padding: 4px 6px;">
          <input type="text" class="form-input manual-row-ref" data-idx="${i}" placeholder="Invoice #" style="width: 100%; padding: 4px 8px; font-size: 12px; height: 32px;" maxlength="15" value="${saved.ref}" />
        </td>
        <td style="text-align: center; padding: 4px 6px; vertical-align: middle;">
          <button type="button" class="btn btn-danger btn-sm" onclick="GenerateScreen.removeManualInlineRow(${i}, ${batchNum})"
            style="padding: 2px 8px; font-size: 11px;" ${b.rowCount <= 1 ? 'disabled' : ''}>×</button>
        </td>
      `;
      tbody.appendChild(tr);

      // Restore vendor selection and attach change listener
      const sel = tr.querySelector('.manual-row-vendor');
      if (sel) {
        if (saved.vendor_id) sel.value = saved.vendor_id;
        sel.addEventListener('change', (e) => {
          const vid = e.target.value;
          const v = loadedVendors.find(x => String(x.id) === String(vid));
          const rCell = tr.querySelector('.manual-row-routing');
          const aCell = tr.querySelector('.manual-row-account');
          const tCell = tr.querySelector('.manual-row-type');
          if (rCell) rCell.textContent = v ? v.routing_number : '—';
          if (aCell) aCell.textContent = v ? (v.account_number || '••••••') : '—';
          if (tCell) tCell.innerHTML = v ? `<span class="badge badge-neutral" style="font-size: 10px; text-transform: capitalize;">${v.account_type || 'Checking'}</span>` : '—';
          checkNachaGenerateButtonState();
        });
      }

      const amtInp = tr.querySelector('.manual-row-amount');
      if (amtInp) {
        amtInp.addEventListener('input', checkNachaGenerateButtonState);
      }
    }
  }

  function addManualInlineRow(batchNum = 2) {
    const b = getManualBatchObj(batchNum);
    b.rowCount++;
    renderManualInlineRows(batchNum);
    // Focus the new vendor select
    const tbody = getBatchTbody(batchNum);
    if (tbody) {
      const lastRow = tbody.querySelector(`tr[data-row-idx="${b.rowCount - 1}"]`);
      if (lastRow) {
        const sel = lastRow.querySelector('.manual-row-vendor');
        if (sel) sel.focus();
      }
    }
  }

  function addManualRow(batchNum = 2) {
    addManualInlineRow(batchNum);
  }

  function removeManualInlineRow(index, batchNum = 2) {
    const b = getManualBatchObj(batchNum);
    if (b.rowCount <= 1) return;

    const tbody = getBatchTbody(batchNum);
    if (!tbody) return;

    const allRows = tbody.querySelectorAll('tr');
    const values = [];
    allRows.forEach((tr, i) => {
      if (i === index) return;
      const vendorSel = tr.querySelector('.manual-row-vendor');
      const amtInput = tr.querySelector('.manual-row-amount');
      const refInput = tr.querySelector('.manual-row-ref');
      values.push({
        vendor_id: vendorSel ? vendorSel.value : '',
        amount: amtInput ? amtInput.value : '',
        ref: refInput ? refInput.value : '',
      });
    });

    b.rowCount = values.length || 1;

    tbody.innerHTML = '';
    const vendorOptions = '<option value="">-- Select Vendor --</option>' +
      loadedVendors.map(v => `<option value="${v.id}">${v.name}</option>`).join('');

    for (let i = 0; i < b.rowCount; i++) {
      const tr = document.createElement('tr');
      tr.setAttribute('data-row-idx', i);
      const saved = values[i] || { vendor_id: '', amount: '', ref: '' };
      const vendorObj = saved.vendor_id ? loadedVendors.find(v => String(v.id) === String(saved.vendor_id)) : null;

      tr.innerHTML = `
        <td class="font-mono" style="vertical-align: middle; text-align: center; color: var(--color-text-muted); font-size: 11px;">${i + 1}</td>
        <td style="padding: 4px 6px;">
          <select class="form-select manual-row-vendor" data-idx="${i}" style="width: 100%; padding: 4px 8px; font-size: 12px; height: 32px;">
            ${vendorOptions}
          </select>
        </td>
        <td class="font-mono manual-row-routing" style="vertical-align: middle; padding: 4px 6px; font-size: 11px; color: var(--color-text-muted);">
          ${vendorObj ? vendorObj.routing_number : '—'}
        </td>
        <td class="font-mono manual-row-account" style="vertical-align: middle; padding: 4px 6px; font-size: 11px; color: var(--color-text-muted);">
          ${vendorObj ? (vendorObj.account_number || '••••••') : '—'}
        </td>
        <td class="manual-row-type" style="vertical-align: middle; padding: 4px 6px; font-size: 11px;">
          ${vendorObj ? `<span class="badge badge-neutral" style="font-size: 10px; text-transform: capitalize;">${vendorObj.account_type || 'Checking'}</span>` : '—'}
        </td>
        <td style="padding: 4px 6px;">
          <input type="number" class="form-input manual-row-amount" data-idx="${i}" step="0.01" placeholder="0.00" style="width: 100%; padding: 4px 8px; font-size: 12px; height: 32px;" value="${saved.amount}" />
        </td>
        <td style="padding: 4px 6px;">
          <input type="text" class="form-input manual-row-ref" data-idx="${i}" placeholder="Invoice #" style="width: 100%; padding: 4px 8px; font-size: 12px; height: 32px;" maxlength="15" value="${saved.ref}" />
        </td>
        <td style="text-align: center; padding: 4px 6px; vertical-align: middle;">
          <button type="button" class="btn btn-danger btn-sm" onclick="GenerateScreen.removeManualInlineRow(${i}, ${batchNum})"
            style="padding: 2px 8px; font-size: 11px;" ${b.rowCount <= 1 ? 'disabled' : ''}>×</button>
        </td>
      `;
      tbody.appendChild(tr);

      const sel = tr.querySelector('.manual-row-vendor');
      if (sel) {
        if (saved.vendor_id) sel.value = saved.vendor_id;
        sel.addEventListener('change', (e) => {
          const vid = e.target.value;
          const v = loadedVendors.find(x => String(x.id) === String(vid));
          const rCell = tr.querySelector('.manual-row-routing');
          const aCell = tr.querySelector('.manual-row-account');
          const tCell = tr.querySelector('.manual-row-type');
          if (rCell) rCell.textContent = v ? v.routing_number : '—';
          if (aCell) aCell.textContent = v ? (v.account_number || '••••••') : '—';
          if (tCell) tCell.innerHTML = v ? `<span class="badge badge-neutral" style="font-size: 10px; text-transform: capitalize;">${v.account_type || 'Checking'}</span>` : '—';
          checkNachaGenerateButtonState();
        });
      }

      const amtInp = tr.querySelector('.manual-row-amount');
      if (amtInp) {
        amtInp.addEventListener('input', checkNachaGenerateButtonState);
      }
    }
  }

  function addBatch() {
    const nextNum = manualBatches.length > 0 ? Math.max(...manualBatches.map(b => b.batchNum)) + 1 : 3;
    const newBatch = { batchNum: nextNum, rowCount: 1, overrideActive: false, dbBatchId: null };
    manualBatches.push(newBatch);

    const container = el('additionalBatchesContainer');
    if (!container) return;

    const todayStr = new Date().toISOString().split('T')[0];
    const card = document.createElement('div');
    card.className = 'card';
    card.id = `card_batch_${nextNum}`;
    card.style.cssText = 'margin-top: var(--space-xl); margin-bottom: var(--space-lg);';

    card.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-xs);">
        <div class="card-title" style="margin: 0;">Manual Payment Entry (Batch ${nextNum})</div>
        <button type="button" class="btn btn-danger btn-sm" onclick="GenerateScreen.removeBatch(${nextNum})" style="padding: 2px 8px; font-size: 11px;">× Remove Batch</button>
      </div>
      <p class="text-xs text-muted" style="margin-bottom: var(--space-md);">Enter payment rows below. Click <strong>+ Add Row</strong> to add more. All rows in this batch share the same effective date.</p>

      <!-- Shared Effective Date -->
      <div class="form-group" style="max-width: 220px; margin-bottom: var(--space-md);">
        <label class="form-label" for="manualEffDate_${nextNum}">Effective Date <span style="color: #dc2626;">*</span></label>
        <input class="form-input batch-eff-date" type="date" id="manualEffDate_${nextNum}" value="${todayStr}" />
      </div>

      <!-- Inline Multi-Row Entry Table -->
      <div class="payments-table-wrap">
        <table class="data-table" id="manualInlineTable_${nextNum}">
          <thead>
            <tr>
              <th style="width: 35px;">#</th>
              <th style="min-width: 170px;">Vendor *</th>
              <th style="width: 105px;">Routing #</th>
              <th style="width: 115px;">Account #</th>
              <th style="width: 80px;">Type</th>
              <th style="width: 110px;">Amount ($) *</th>
              <th style="width: 130px;">Invoice / Ref # *</th>
              <th style="width: 45px; text-align: center;"></th>
            </tr>
          </thead>
          <tbody id="manualInlineTableBody_${nextNum}" class="manual-table-body" data-batch-num="${nextNum}">
          </tbody>
        </table>
      </div>

      <!-- Error display -->
      <div class="alert alert-error batch-form-error" id="manualFormError_${nextNum}" style="display: none; margin-top: var(--space-md);"></div>

      <!-- Duplicate Warning & Override Banner -->
      <div class="duplicate-banner batch-duplicate-banner" id="manualDuplicateBanner_${nextNum}" style="display: none; margin-top: var(--space-md);">
        <div class="duplicate-title">Duplicate Transactions Detected in Batch ${nextNum}</div>
        <div class="duplicate-sub">One or more manual payment rows match existing transactions previously uploaded to the system.</div>
        <div class="duplicate-actions">
          <label class="override-checkbox-label">
            <input type="checkbox" id="manualOverrideCheckbox_${nextNum}" />
            Allow Duplicate Override
          </label>
          <button type="button" class="btn btn-secondary btn-sm" onclick="GenerateScreen.retryBatchOverride(${nextNum})">Re-upload with Override</button>
        </div>
      </div>

      <!-- Action Buttons -->
      <div style="margin-top: var(--space-md); display: flex; gap: var(--space-md); align-items: center; flex-wrap: wrap;">
        <button type="button" class="btn btn-secondary btn-sm" onclick="GenerateScreen.addManualRow(${nextNum})">
          + Add Row
        </button>
      </div>
    `;

    container.appendChild(card);
    renderManualInlineRows(nextNum);
    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
    checkNachaGenerateButtonState();
    if (window.showToast) window.showToast(`Batch ${nextNum} added.`, 'info');
  }

  function removeBatch(batchNum) {
    const idx = manualBatches.findIndex(b => b.batchNum === Number(batchNum));
    if (idx !== -1) {
      manualBatches.splice(idx, 1);
    }
    const card = el(`card_batch_${batchNum}`);
    if (card) card.remove();
    checkNachaGenerateButtonState();
    if (window.showToast) window.showToast(`Batch ${batchNum} removed.`, 'info');
  }

  function retryBatchOverride(batchNum) {
    const b = getManualBatchObj(batchNum);
    b.overrideActive = true;
    handleGenerateNacha();
  }

  function collectManualBatchData(batchNum = 2) {
    const tbody = getBatchTbody(batchNum);
    if (!tbody) return { entries: [], errors: [], hasFilledRows: false, effDate: '' };

    const rows = tbody.querySelectorAll('tr');
    const entries = [];
    const errors = [];
    let hasFilledRows = false;
    const effInput = getBatchEffDateInput(batchNum);
    const effDate = effInput ? effInput.value.trim() : '';

    rows.forEach((tr, idx) => {
      const vendorSel = tr.querySelector('.manual-row-vendor');
      const amtInput = tr.querySelector('.manual-row-amount');
      const refInput = tr.querySelector('.manual-row-ref');

      const vendorId = vendorSel ? vendorSel.value : '';
      const amount = amtInput ? amtInput.value.trim() : '';
      const ref = refInput ? refInput.value.trim() : '';

      if (vendorId || amount || ref) {
        hasFilledRows = true;
      }

      const rowErrors = [];
      if (!vendorId) rowErrors.push('Vendor is required');
      if (!amount || isNaN(amount) || parseFloat(amount) <= 0) rowErrors.push('Amount must be > 0');
      if (!ref) rowErrors.push('Invoice/Ref is required');

      if (rowErrors.length > 0) {
        errors.push({ row: idx + 1, messages: rowErrors });
        tr.style.background = 'var(--color-danger-bg, #fef2f2)';
      } else {
        tr.style.background = '';
        const vendorObj = loadedVendors.find(v => String(v.id) === String(vendorId));
        entries.push({
          vendor_id: vendorId,
          vendor_name: vendorObj ? vendorObj.name : '',
          routing_number: vendorObj ? vendorObj.routing_number : '',
          account_number: vendorObj ? vendorObj.account_number : '',
          amount: parseFloat(amount).toFixed(2),
          id_number: ref,
          effective_date: effDate,
        });
      }
    });

    return { entries, errors, hasFilledRows, effDate };
  }

  function showManualError(msg, batchNum = 2) {
    const errBox = getBatchErrorBox(batchNum);
    if (errBox) {
      errBox.textContent = msg;
      errBox.style.display = 'block';
    }
  }

  async function removeManualEntry(index) {
    if (index >= 0 && index < manualDraftEntries.length) {
      const removed = manualDraftEntries.splice(index, 1)[0];
      if (lastBatch2Response && lastBatch2Response.valid_payments && lastBatch2Response.valid_payments[index]) {
        lastBatch2Response.valid_payments.splice(index, 1);
      }

      if (manualDraftEntries.length === 0) {
        batch2Id = null;
        lastBatch2Response = null;
        batch2OverrideActive = false;
        if (el('manualResultsSection')) el('manualResultsSection').style.display = 'none';
        checkNachaGenerateButtonState();
        if (window.showToast) window.showToast('Removed all entries from Batch 2.', 'info');
      } else if (batch2Id) {
        await handleSubmitManualBatch(batch2OverrideActive);
        if (window.showToast) window.showToast(`Removed entry for ${removed.vendor_name} from Batch 2.`, 'info');
      } else {
        if (window.showToast) window.showToast(`Removed staged entry for ${removed.vendor_name}.`, 'info');
      }
    }
  }

  function toggleManualDraftSection() {
    const inlineTable = el('manualInlineTable');
    if (inlineTable) {
      inlineTable.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }

  async function handleSubmitManualBatch(overrideFlag = false) {
    // Backwards-compatible programmatic submit for Batch 2
    return await handleGenerateNacha();
  }

  function setManualLoading(loading) {
    const addBtn = el('addManualRowBtn');
    const spinner = el('manualBatchSpinner');
    if (addBtn) addBtn.disabled = loading;
    if (spinner) spinner.style.display = loading ? 'inline-block' : 'none';
  }

  function renderManualBatchResults(data) {
    if (el('manualResultsSection')) el('manualResultsSection').style.display = 'block';

    const summary = data.summary || {};
    const validPayments = data.valid_payments || [];
    const errors = data.errors || [];

    if (el('manualStatTotalRows')) el('manualStatTotalRows').textContent = summary.total_rows || 0;
    if (el('manualStatValidRows')) el('manualStatValidRows').textContent = summary.valid_rows || validPayments.length;
    if (el('manualStatErrorRows')) el('manualStatErrorRows').textContent = summary.error_rows || errors.length;
    if (el('manualStatTotalAmount')) el('manualStatTotalAmount').textContent = `$${parseFloat(summary.total_amount || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

    const hasDuplicateError = errors.some(e =>
      e.errors && e.errors.some(errStr => errStr.toLowerCase().includes('duplicate'))
    );

    if (hasDuplicateError) {
      if (el('manualDuplicateBanner')) el('manualDuplicateBanner').style.display = 'block';
      if (el('manualOverrideCheckbox')) el('manualOverrideCheckbox').checked = batch2OverrideActive;
    } else {
      if (el('manualDuplicateBanner')) el('manualDuplicateBanner').style.display = 'none';
    }

    if (errors.length > 0) {
      if (el('manualErrorPanel')) {
        el('manualErrorPanel').style.display = 'block';
        el('manualErrorCountBadge').textContent = `${errors.length} issue(s)`;
        renderErrorsTable(errors, 'manualErrorTableBody');
      }
    } else {
      if (el('manualErrorPanel')) el('manualErrorPanel').style.display = 'none';
    }

    if (el('manualValidPaymentsTableBody')) {
      renderValidPaymentsTable(validPayments, 'manualValidPaymentsTableBody');
    }
  }

  function checkNachaGenerateButtonState() {
    const btn = el('generateNachaBtn');
    if (btn) btn.disabled = false;
  }

  // ── Phase 4: Combined NACHA File Generation & Download ──────
  async function handleGenerateNacha() {
    if (el('nachaGlobalError')) el('nachaGlobalError').style.display = 'none';

    // Hide all batch-level errors before re-validating
    manualBatches.forEach(b => {
      const errBox = getBatchErrorBox(b.batchNum);
      if (errBox) errBox.style.display = 'none';
    });

    const entryDesc = (el('entryDesc') ? el('entryDesc').value.trim() : 'EPAYMNT').toUpperCase();
    if (entryDesc === 'PAYROLL' || entryDesc === 'REVERSAL') {
      showNachaError('Entry description cannot be PAYROLL or REVERSAL for CCD SEC code per Chase NACHA guidelines.');
      const errTarget = el('entryDesc') || el('nachaGlobalError');
      if (errTarget) errTarget.scrollIntoView({ behavior: 'smooth', block: 'center' });
      return false;
    }

    // 1. Validate all active manual batches
    const validBatchesData = [];

    for (const b of manualBatches) {
      const batchData = collectManualBatchData(b.batchNum);

      // If this batch has rows or entered data, or if no Batch 1 exists
      if (batchData.hasFilledRows || (!batch1Id && manualBatches.length === 1)) {
        if (!batchData.effDate) {
          showManualError(`Effective Date is required for Batch ${b.batchNum}.`, b.batchNum);
          const errTarget = getBatchEffDateInput(b.batchNum) || getBatchErrorBox(b.batchNum);
          if (errTarget) errTarget.scrollIntoView({ behavior: 'smooth', block: 'center' });
          if (window.showToast) window.showToast(`Please enter an Effective Date for Batch ${b.batchNum}.`, 'error');
          return false;
        }

        if (batchData.errors.length > 0) {
          const errMsg = batchData.errors.map(e => `Row ${e.row}: ${e.messages.join(', ')}`).join('\n');
          showManualError(errMsg, b.batchNum);
          const errTarget = getBatchErrorBox(b.batchNum) || getBatchTbody(b.batchNum);
          if (errTarget) errTarget.scrollIntoView({ behavior: 'smooth', block: 'center' });
          if (window.showToast) window.showToast(`Please fix the validation issues in Batch ${b.batchNum} before generating NACHA.`, 'error');
          return false;
        }

        if (batchData.entries.length === 0) {
          showManualError(`Please add at least one payment row with a selected vendor in Batch ${b.batchNum}.`, b.batchNum);
          const errTarget = getBatchErrorBox(b.batchNum) || getBatchTbody(b.batchNum);
          if (errTarget) errTarget.scrollIntoView({ behavior: 'smooth', block: 'center' });
          return false;
        }

        validBatchesData.push({
          batchNum: b.batchNum,
          entries: batchData.entries,
          overrideActive: b.overrideActive || Boolean(el(`manualOverrideCheckbox_${b.batchNum}`)?.checked) || Boolean(el('manualOverrideCheckbox')?.checked),
        });
      }
    }

    // 2. Submit valid manual batches to backend
    setNachaLoading(true);

    const generatedBatchIds = [];
    if (batch1Id) generatedBatchIds.push(batch1Id);

    try {
      for (const vb of validBatchesData) {
        const payload = {
          batch_number: vb.batchNum,
          filename: `Manual Batch ${vb.batchNum}`,
          allow_override: vb.overrideActive,
          payments: vb.entries.map(e => ({
            vendor_id: e.vendor_id,
            amount: e.amount,
            id_number: e.id_number,
            effective_date: e.effective_date,
          }))
        };

        const response = await API.post('/payments/manual-batch', payload);
        const b = getManualBatchObj(vb.batchNum);
        b.dbBatchId = response.batch_id;
        if (vb.batchNum === 2) {
          batch2Id = response.batch_id;
          lastBatch2Response = response;
          manualDraftEntries = vb.entries;
          renderManualBatchResults(response);
        }

        const hasDuplicateError = (response.errors || []).some(e =>
          e.errors && e.errors.some(msg => msg.toLowerCase().includes('duplicate'))
        );

        if (hasDuplicateError && !vb.overrideActive) {
          const dupBanner = getBatchDuplicateBanner(vb.batchNum);
          if (dupBanner) {
            dupBanner.style.display = 'block';
            dupBanner.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }
          if (window.showToast) window.showToast(`Duplicate transactions detected in Batch ${vb.batchNum}. Review override.`, 'warning');
          setNachaLoading(false);
          return false;
        }

        generatedBatchIds.push(response.batch_id);
      }

      if (generatedBatchIds.length === 0) {
        showNachaError('Please upload Batch 1 (spreadsheet) or enter valid manual payments first.');
        const target = el('batch1Card') || el('additionalBatchesContainer') || el('nachaGlobalError');
        if (target) target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        setNachaLoading(false);
        return;
      }

      // 3. Generate Combined NACHA File
      const coName = el('coName').value.trim() || 'AMIPI INC';
      const chaseAcct = el('chaseAcct').value.trim() || '785957066';
      const entryDesc = (el('entryDesc').value.trim() || 'EPAYMNT').toUpperCase();
      const effVal = el('effDate').value.trim();
      const fileIdMod = el('fileIdMod').value.trim() || 'A';
      const rawTraceStart = parseInt(el('traceStart').value.trim() || '0', 10);
      const traceStart = (!isNaN(rawTraceStart) && rawTraceStart > 0) ? rawTraceStart : null;

      if (entryDesc === 'PAYROLL' || entryDesc === 'REVERSAL') {
        showNachaError('Entry description cannot be PAYROLL or REVERSAL for Chase CCD credits.');
        if (el('entryDesc')) el('entryDesc').scrollIntoView({ behavior: 'smooth', block: 'center' });
        setNachaLoading(false);
        return;
      }

      let effDateIso = null;
      if (effVal && effVal.length === 6) {
        effDateIso = `20${effVal.substring(0, 2)}-${effVal.substring(2, 4)}-${effVal.substring(4, 6)}`;
      }

      const nachaPayload = {
        batch_ids: generatedBatchIds,
        company_name: coName,
        company_account: chaseAcct,
        entry_description: entryDesc,
        effective_entry_date: effDateIso,
        file_id_modifier: fileIdMod,
        trace_sequence_start: traceStart,
      };

      const response = await API.post('/nacha/generate', nachaPayload);
      generatedNachaRecord = response;
      renderNachaOutputCard(response);
      if (window.showToast) window.showToast('Combined NACHA file generated successfully!', 'success');
      return true;
    } catch (err) {
      showNachaError(err.message || 'Combined NACHA file generation failed.');
      if (el('nachaGlobalError')) el('nachaGlobalError').scrollIntoView({ behavior: 'smooth', block: 'center' });
      return false;
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
    addManualInlineRow,
    addManualRow,
    removeManualInlineRow,
    addBatch,
    removeBatch,
    retryBatchOverride,
    removeManualEntry,
    handleSubmitManualBatch,
    handleGenerateNacha,
    handleDownloadNacha,
    openEditRowModal,
    openBreakdownModal,
    toggleManualDraftSection,
    renderManualInlineRows,
  };
})();

document.addEventListener('DOMContentLoaded', () => {
  GenerateScreen.init();
});
