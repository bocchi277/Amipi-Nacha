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
  let manualDraftEntries = [];

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

  async function loadVendors() {
    const select = el('manualVendorSelect');
    if (!select) return;

    try {
      const vendors = await API.get('/vendors');
      loadedVendors = vendors || [];

      select.innerHTML = '<option value="">-- Select Vendor --</option>';
      loadedVendors.forEach(v => {
        const opt = document.createElement('option');
        opt.value = v.id;
        opt.textContent = `${v.name} (Routing: ${v.routing_number}, Acct: ...${v.account_number.slice(-4)})`;
        select.appendChild(opt);
      });
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

    const addManualBtn = el('addManualEntryBtn');
    if (addManualBtn) {
      addManualBtn.addEventListener('click', handleAddManualEntry);
    }

    const submitManualBtn = el('submitManualBatchBtn');
    if (submitManualBtn) {
      submitManualBtn.addEventListener('click', () => handleSubmitManualBatch(false));
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
    const tbody = el(tbodyId);
    if (!tbody) return;
    tbody.innerHTML = '';

    if (payments.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="7" class="text-center text-muted" style="padding: var(--space-xl);">
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

      tr.innerHTML = `
        <td class="font-mono">${idx + 1}</td>
        <td class="font-bold">${p.vendor_name}</td>
        <td class="font-mono">${p.routing_number || '—'}</td>
        <td class="font-mono">${p.account_number || '—'}</td>
        <td class="font-mono">${amtFormatted}</td>
        <td class="font-mono">${p.id_number || '—'}</td>
        <td>${dupBadge}</td>
      `;
      tbody.appendChild(tr);
    });
  }

  // ── Batch 2: Manual Payment Entry ─────────────────────────────
  function handleAddManualEntry() {
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
    if (!amountVal || isNaN(amountVal) || parseFloat(amountVal) <= 0) return showManualError('Please enter a valid positive amount.');
    if (!idNum) return showManualError('Invoice / ID Number is required.');
    if (!effDate) return showManualError('Effective date is required.');

    const vendorObj = loadedVendors.find(v => v.id === vendorId);
    if (!vendorObj) return showManualError('Selected vendor invalid.');

    manualDraftEntries.push({
      vendor_id: vendorId,
      vendor_name: vendorObj.name,
      routing_number: vendorObj.routing_number,
      account_number: vendorObj.account_number,
      amount: parseFloat(amountVal).toFixed(2),
      id_number: idNum,
      effective_date: effDate,
    });

    if (amtInput) amtInput.value = '';
    if (idInput) idInput.value = '';

    renderManualDraftTable();
  }

  function showManualError(msg) {
    const errBox = el('manualFormError');
    if (errBox) {
      errBox.textContent = msg;
      errBox.style.display = 'block';
    }
  }

  function renderManualDraftTable() {
    const tbody = el('manualDraftTableBody');
    const section = el('manualDraftSection');
    const submitBtn = el('submitManualBatchBtn');
    if (!tbody) return;

    tbody.innerHTML = '';

    if (manualDraftEntries.length === 0) {
      if (section) section.style.display = 'none';
      if (submitBtn) submitBtn.disabled = true;
      return;
    }

    if (section) section.style.display = 'block';
    if (submitBtn) submitBtn.disabled = false;

    let totalAmt = 0;

    manualDraftEntries.forEach((entry, idx) => {
      totalAmt += parseFloat(entry.amount);
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td class="font-mono">${idx + 1}</td>
        <td class="font-bold">${entry.vendor_name}</td>
        <td class="font-mono">${entry.routing_number}</td>
        <td class="font-mono">${entry.account_number}</td>
        <td class="font-mono">$${parseFloat(entry.amount).toFixed(2)}</td>
        <td class="font-mono">${entry.id_number}</td>
        <td class="font-mono">${entry.effective_date}</td>
        <td>
          <button type="button" class="btn btn-danger btn-sm" onclick="GenerateScreen.removeManualEntry(${idx})">Remove</button>
        </td>
      `;
      tbody.appendChild(tr);
    });

    if (el('manualDraftCount')) el('manualDraftCount').textContent = manualDraftEntries.length;
    if (el('manualDraftTotalAmount')) el('manualDraftTotalAmount').textContent = `$${totalAmt.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }

  function removeManualEntry(index) {
    manualDraftEntries.splice(index, 1);
    renderManualDraftTable();
  }

  async function handleSubmitManualBatch(overrideFlag = false) {
    if (manualDraftEntries.length === 0) return;

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
    } catch (err) {
      showManualError(err.message || 'Failed to submit manual batch.');
    } finally {
      setManualLoading(false);
    }
  }

  function setManualLoading(loading) {
    const btn = el('submitManualBatchBtn');
    const spinner = el('manualBatchSpinner');
    if (btn) btn.disabled = loading || manualDraftEntries.length === 0;
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
    const hasBatches = !!(batch1Id || batch2Id);
    btn.disabled = !hasBatches;
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
  };
})();

document.addEventListener('DOMContentLoaded', () => {
  GenerateScreen.init();
});
