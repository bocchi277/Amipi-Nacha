/**
 * AMIPI NACHA ACH Payment System — Transaction Table & Payment History Controller
 *
 * Accessible to all logged-in users. Provides multi-field filtering (vendor, status,
 * date range, text search), client-side pagination, multi-select checkboxes,
 * and a bulk-resend remittance email workflow with an explicit confirmation step.
 */

const HistoryScreen = (() => {
  let allRemittances = [];
  let filteredRemittances = [];
  let selectedRemittanceIds = new Set();
  let loadedVendors = [];

  // Pagination state
  let currentPage = 1;
  const pageSize = 10;

  let historyToDelete = [];

  function isAdmin() {
    const user = API.getUser();
    return user && String(user.role).toLowerCase() === 'admin';
  }

  function el(id) { return document.getElementById(id); }

  function init() {
    bindEvents();
  }

  function bindEvents() {

    const selectAllCb = el('historySelectAllCb');
    if (selectAllCb) selectAllCb.addEventListener('change', handleSelectAll);

    const bulkBtn = el('bulkResendBtn');
    if (bulkBtn) bulkBtn.addEventListener('click', openConfirmModal);

    const cancelModalBtn = el('cancelBulkResendModalBtn');
    const closeModalBtn = el('closeBulkResendModalBtn');
    if (cancelModalBtn) cancelModalBtn.addEventListener('click', hideConfirmModal);
    if (closeModalBtn) closeModalBtn.addEventListener('click', hideConfirmModal);

    const confirmSendBtn = el('confirmBulkResendBtn');
    if (confirmSendBtn) confirmSendBtn.addEventListener('click', handleExecuteBulkResend);

    // Email Template Modal listeners
    const openTmplBtn = el('openEmailTemplateModalBtn');
    const closeTmplBtn = el('closeEmailTemplateModalBtn');
    const resetTmplBtn = el('resetDefaultTmplBtn');
    const tmplForm = el('emailTemplateForm');

    if (openTmplBtn) openTmplBtn.addEventListener('click', openEmailTemplateModal);
    if (closeTmplBtn) closeTmplBtn.addEventListener('click', hideEmailTemplateModal);
    if (resetTmplBtn) resetTmplBtn.addEventListener('click', resetEmailTemplateToDefault);
    if (tmplForm) tmplForm.addEventListener('submit', handleSaveEmailTemplate);

    const prevBtn = el('prevHistoryPageBtn');
    const nextBtn = el('nextHistoryPageBtn');
    if (prevBtn) prevBtn.addEventListener('click', () => changePage(-1));
    if (nextBtn) nextBtn.addEventListener('click', () => changePage(1));

    // Prototype Top Action Bar Event Listeners
    const exportCsvBtn = el('historyExportCsvBtn');
    const exportExcelBtn = el('historyExportExcelBtn');
    const saveJsonBtn = el('historySaveJsonBtn');
    const loadJsonBtn = el('historyLoadJsonBtn');

    if (exportCsvBtn) exportCsvBtn.addEventListener('click', handleExportCSV);
    if (exportExcelBtn) exportExcelBtn.addEventListener('click', handleExportExcel);
    if (saveJsonBtn) saveJsonBtn.addEventListener('click', handleSaveJSON);
    if (loadJsonBtn) loadJsonBtn.addEventListener('click', handleLoadJSON);

    // Delete History Modal Event Listeners
    const bulkDeleteHistoryBtn = el('bulkDeleteHistoryBtn');
    const closeDeleteHistoryBtn = el('closeDeleteHistoryModalBtn');
    const cancelDeleteHistoryBtn = el('cancelDeleteHistoryModalBtn');
    const executeDeleteHistoryBtn = el('executeDeleteHistoryBtn');

    if (bulkDeleteHistoryBtn) bulkDeleteHistoryBtn.addEventListener('click', openConfirmDeleteSelectionHistory);
    if (closeDeleteHistoryBtn) closeDeleteHistoryBtn.addEventListener('click', hideDeleteHistoryModal);
    if (cancelDeleteHistoryBtn) cancelDeleteHistoryBtn.addEventListener('click', hideDeleteHistoryModal);
    if (executeDeleteHistoryBtn) executeDeleteHistoryBtn.addEventListener('click', executeHistoryDeletion);

    // Last NACHA File Viewer Modal Listeners
    const viewLastNachaBtn = el('historyViewLastNachaBtn');
    const closeLastNachaBtn = el('closeLastNachaModalBtn');
    const cancelLastNachaBtn = el('cancelLastNachaModalBtn');
    const copyLastNachaBtn = el('lastNachaCopyBtn');
    const downloadLastNachaBtn = el('lastNachaDownloadBtn');

    if (viewLastNachaBtn) viewLastNachaBtn.addEventListener('click', openLastNachaFileModal);
    if (closeLastNachaBtn) closeLastNachaBtn.addEventListener('click', hideLastNachaFileModal);
    if (cancelLastNachaBtn) cancelLastNachaBtn.addEventListener('click', hideLastNachaFileModal);
    if (copyLastNachaBtn) copyLastNachaBtn.addEventListener('click', handleCopyLastNacha);
    if (downloadLastNachaBtn) downloadLastNachaBtn.addEventListener('click', handleDownloadLastNacha);

    // Per-column filter inputs — instant client-side filtering
    const filterInputIds = [
      'colFilterEffDate', 'colFilterVendor', 'colFilterEmail',
      'colFilterAmount', 'colFilterInvoice', 'colFilterGeneratedBy',
      'colFilterSentAt',
    ];
    filterInputIds.forEach(id => {
      const input = el(id);
      if (input) input.addEventListener('input', applyColumnFilters);
    });
    const statusFilter = el('colFilterStatus');
    if (statusFilter) statusFilter.addEventListener('change', applyColumnFilters);

    const clearFiltersBtn = el('clearAllColFilters');
    if (clearFiltersBtn) clearFiltersBtn.addEventListener('click', clearColumnFilters);

    // Auto-load when switching to view-history tab
    document.querySelectorAll('#mainTabs .tab').forEach(tab => {
      tab.addEventListener('click', () => {
        if (tab.dataset.view === 'history') {
          loadData();
        }
      });
    });
  }

  // ── Email Template Management ──────────────────────────────────
  let activeTemplateData = null;

  async function openEmailTemplateModal() {
    const modal = el('emailTemplateModal');
    const errBox = el('emailTmplError');
    const succBox = el('emailTmplSuccess');
    if (errBox) errBox.style.display = 'none';
    if (succBox) succBox.style.display = 'none';

    try {
      const data = await API.get('/remittances/template');
      activeTemplateData = data;
      if (el('tmplSubjectInput')) el('tmplSubjectInput').value = data.subject_template || '';
      if (el('tmplBodyInput')) el('tmplBodyInput').value = data.body_template || '';
    } catch (err) {
      console.warn('Failed to load email template:', err);
    }

    if (modal) {
      modal.classList.add('active');
      modal.style.display = 'flex';
    }
  }

  function hideEmailTemplateModal() {
    const modal = el('emailTemplateModal');
    if (modal) {
      modal.classList.remove('active');
      modal.style.display = 'none';
    }
  }

  function insertPlaceholder(tag) {
    const bodyInput = el('tmplBodyInput');
    const subjectInput = el('tmplSubjectInput');
    
    // Insert into focused input, defaulting to body textarea
    const activeEl = document.activeElement === subjectInput ? subjectInput : bodyInput;
    if (!activeEl) return;

    const start = activeEl.selectionStart || activeEl.value.length;
    const end = activeEl.selectionEnd || activeEl.value.length;
    const text = activeEl.value;

    activeEl.value = text.substring(0, start) + tag + text.substring(end);
    activeEl.focus();
    activeEl.selectionStart = activeEl.selectionEnd = start + tag.length;
  }

  function resetEmailTemplateToDefault() {
    if (el('tmplSubjectInput')) {
      el('tmplSubjectInput').value = 'Payment Remittance Advice — {{vendor_name}} (${{amount}})';
    }
    if (el('tmplBodyInput')) {
      el('tmplBodyInput').value = `Dear {{vendor_name}},\n\nPlease be advised that an ACH payment of \${{amount}} has been scheduled for effective date {{effective_date}}.\n\nPayment Details:\n• Payee / Vendor Name: {{vendor_name}}\n• Payment Amount ($):  \${{amount}}\n• Invoice Reference:   {{invoice_ref}}\n• Effective Date:      {{effective_date}}\n\nIf you have any questions regarding this remittance, please contact Accounts Payable.\n\nThank you,\n{{company_name}} Accounts Payable`;
    }
  }

  async function handleSaveEmailTemplate(e) {
    if (e) e.preventDefault();

    const subjectVal = el('tmplSubjectInput').value.trim();
    const bodyVal = el('tmplBodyInput').value.trim();
    const errBox = el('emailTmplError');
    const succBox = el('emailTmplSuccess');
    const spinner = el('tmplSpinner');
    const saveBtn = el('saveEmailTmplBtn');

    if (errBox) errBox.style.display = 'none';
    if (succBox) succBox.style.display = 'none';

    if (!subjectVal || !bodyVal) {
      if (errBox) {
        errBox.textContent = 'Both Subject Line and Body Template are required.';
        errBox.style.display = 'block';
      }
      return;
    }

    if (saveBtn) saveBtn.disabled = true;
    if (spinner) spinner.style.display = 'inline-block';

    try {
      await API.put('/remittances/template', {
        subject_template: subjectVal,
        body_template: bodyVal,
      });

      if (succBox) {
        succBox.textContent = 'Email template updated successfully! All future remittances will use this template.';
        succBox.style.display = 'block';
      }

      setTimeout(() => {
        hideEmailTemplateModal();
      }, 1800);
    } catch (err) {
      if (errBox) {
        errBox.textContent = err.message || 'Failed to save email template.';
        errBox.style.display = 'block';
      }
    } finally {
      if (saveBtn) saveBtn.disabled = false;
      if (spinner) spinner.style.display = 'none';
    }
  }


  // ── Debounce Utility ──────────────────────────────────────────
  function debounce(fn, delay) {
    let timer;
    return function (...args) {
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(this, args), delay);
    };
  }

  // ── Per-Column Client-Side Filtering ────────────────────────────
  function applyColumnFilters() {
    const effDate = (el('colFilterEffDate') ? el('colFilterEffDate').value : '').trim().toLowerCase();
    const vendor = (el('colFilterVendor') ? el('colFilterVendor').value : '').trim().toLowerCase();
    const email = (el('colFilterEmail') ? el('colFilterEmail').value : '').trim().toLowerCase();
    const amount = (el('colFilterAmount') ? el('colFilterAmount').value : '').trim().toLowerCase();
    const invoice = (el('colFilterInvoice') ? el('colFilterInvoice').value : '').trim().toLowerCase();
    const generatedBy = (el('colFilterGeneratedBy') ? el('colFilterGeneratedBy').value : '').trim().toLowerCase();
    const status = (el('colFilterStatus') ? el('colFilterStatus').value : '').trim().toLowerCase();
    const sentAt = (el('colFilterSentAt') ? el('colFilterSentAt').value : '').trim().toLowerCase();

    filteredRemittances = allRemittances.filter(r => {
      if (effDate && !(r.effective_date || '').toLowerCase().includes(effDate)) return false;
      if (vendor && !(r.vendor_name || '').toLowerCase().includes(vendor)) return false;
      if (email && !(r.recipient_email || '').toLowerCase().includes(email)) return false;
      if (amount) {
        const cleanTerm = amount.replace(/[$, ]/g, '');
        const rawAmt = String(r.amount || '');
        const formattedAmt = parseFloat(r.amount || 0).toFixed(2);
        if (!rawAmt.includes(cleanTerm) && !formattedAmt.includes(cleanTerm)) return false;
      }
      if (invoice) {
        const mainMatch = (r.invoice_reference || '').toLowerCase().includes(invoice);
        const breakdownMatch = Array.isArray(r.invoice_breakdown) && r.invoice_breakdown.some(item => (item.invoice_number || '').toLowerCase().includes(invoice));
        if (!mainMatch && !breakdownMatch) return false;
      }
      if (generatedBy && !(r.created_by_username || '').toLowerCase().includes(generatedBy)) return false;
      if (status && (r.status || '').toLowerCase() !== status) return false;
      if (sentAt && !(r.sent_at || '').toLowerCase().includes(sentAt)) return false;
      return true;
    });

    currentPage = 1;
    selectedRemittanceIds.clear();
    updateBulkBar();
    updateKPIs();
    renderTable();
  }

  function clearColumnFilters() {
    ['colFilterEffDate', 'colFilterVendor', 'colFilterEmail',
     'colFilterAmount', 'colFilterInvoice', 'colFilterGeneratedBy',
     'colFilterSentAt'].forEach(id => {
      const input = el(id);
      if (input) input.value = '';
    });
    const statusSel = el('colFilterStatus');
    if (statusSel) statusSel.value = '';

    applyColumnFilters();
  }

  async function loadVendorsDropdown() {
    // No longer needed — vendor filter is now a text search input in the table header
  }

  async function loadData() {
    if (!API.isAuthenticated()) return;

    setLoading(true);
    selectedRemittanceIds.clear();
    updateBulkBar();

    // Fetch all data with a 12-month lookback from the server
    const twelveMonthsAgo = new Date();
    twelveMonthsAgo.setMonth(twelveMonthsAgo.getMonth() - 12);
    const startDate = twelveMonthsAgo.toISOString().substring(0, 10);

    try {
      const data = await API.get(`/remittances?start_date=${startDate}`);
      allRemittances = data || [];
      applyColumnFilters();
    } catch (err) {
      console.warn('Failed to load remittance payment history:', err);
      renderEmptyTable(err.message || 'Failed to load transaction history.');
    } finally {
      setLoading(false);
    }
  }

  function updateKPIs() {
    const totalPayments = filteredRemittances.length;
    const uniqueVendors = new Set(filteredRemittances.map(r => r.vendor_name)).size;
    const totalAmount = filteredRemittances.reduce((sum, r) => sum + (parseFloat(r.amount) || 0), 0);

    if (el('kpiTotalPayments')) el('kpiTotalPayments').textContent = totalPayments;
    if (el('kpiTotalVendors')) el('kpiTotalVendors').textContent = uniqueVendors;
    if (el('kpiTotalAmount')) el('kpiTotalAmount').textContent = `$${totalAmount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    if (el('historyRecordCountBadge')) el('historyRecordCountBadge').textContent = `${totalPayments} records`;
  }

  function handleExportCSV() {
    if (filteredRemittances.length === 0) {
      alert('No remittance records to export.');
      return;
    }
    const headers = ['ID', 'Effective Date', 'Vendor Name', 'Recipient Email', 'Amount ($)', 'Invoice Reference', 'Status', 'Sent At'];
    const rows = filteredRemittances.map(r => [
      r.id,
      r.effective_date ? r.effective_date.substring(0, 10) : '',
      `"${(r.vendor_name || '').replace(/"/g, '""')}"`,
      r.recipient_email || '',
      r.amount,
      `"${(r.invoice_reference || '').replace(/"/g, '""')}"`,
      r.status,
      r.sent_at || '',
    ]);

    const csvContent = [headers.join(','), ...rows.map(row => row.join(','))].join('\n');
    downloadFile(csvContent, 'payment_history_export.csv', 'text/csv;charset=utf-8;');
  }

  function handleExportExcel() {
    if (filteredRemittances.length === 0) {
      alert('No remittance records to export.');
      return;
    }

    if (typeof XLSX === 'undefined') {
      alert('Excel library not loaded. Falling back to CSV export.');
      handleExportCSV();
      return;
    }

    const headers = ['#', 'Effective Date', 'Vendor Name', 'Recipient Email', 'Amount ($)', 'Invoice Reference', 'Generated By', 'Status', 'Sent At'];
    const rows = filteredRemittances.map((r, i) => [
      i + 1,
      r.effective_date ? r.effective_date.substring(0, 10) : '',
      r.vendor_name || '',
      r.recipient_email || '',
      parseFloat(r.amount) || 0,
      r.invoice_reference || '',
      r.created_by_username || 'admin',
      r.status || '',
      r.sent_at ? r.sent_at.substring(0, 16).replace('T', ' ') : '',
    ]);

    const wsData = [headers, ...rows];
    const ws = XLSX.utils.aoa_to_sheet(wsData);

    // Set column widths for readability
    ws['!cols'] = [
      { wch: 5 },   // #
      { wch: 14 },  // Effective Date
      { wch: 28 },  // Vendor Name
      { wch: 30 },  // Recipient Email
      { wch: 14 },  // Amount
      { wch: 20 },  // Invoice Reference
      { wch: 14 },  // Generated By
      { wch: 10 },  // Status
      { wch: 20 },  // Sent At
    ];

    // Format the Amount column as number with 2 decimal places
    for (let rowIdx = 1; rowIdx <= rows.length; rowIdx++) {
      const cellRef = XLSX.utils.encode_cell({ c: 4, r: rowIdx });
      if (ws[cellRef] && typeof ws[cellRef].v === 'number') {
        ws[cellRef].z = '#,##0.00';
      }
    }

    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, 'Payment History');
    XLSX.writeFile(wb, 'payment_history_export.xlsx');
  }

  function handleSaveJSON() {
    if (filteredRemittances.length === 0) {
      alert('No history data available to save.');
      return;
    }
    const jsonContent = JSON.stringify(filteredRemittances, null, 2);
    downloadFile(jsonContent, 'amipi_payment_history.json', 'application/json;');
  }

  function handleLoadJSON() {
    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.accept = '.json';
    fileInput.onchange = e => {
      const file = e.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = evt => {
        try {
          const loadedData = JSON.parse(evt.target.result);
          if (Array.isArray(loadedData)) {
            allRemittances = loadedData;
            filteredRemittances = [...allRemittances];
            updateKPIs();
            renderTable();
            alert(`Loaded ${loadedData.length} records from backup JSON.`);
          } else {
            alert('Invalid JSON structure. Expected an array of payment records.');
          }
        } catch (err) {
          alert('Failed to parse JSON file.');
        }
      };
      reader.readAsText(file);
    };
    fileInput.click();
  }

  function handleClearHistory() {
    if (confirm('Are you sure you want to clear the visible payment history view?')) {
      filteredRemittances = [];
      updateKPIs();
      renderEmptyTable('Payment history cleared.');
    }
  }

  function downloadFile(content, fileName, contentType) {
    const blob = new Blob([content], { type: contentType });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    link.href = url;
    link.download = fileName;
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }



  function setLoading(loading) {
    const spinner = el('historySpinner');
    const tableWrap = el('historyTableWrap');
    if (spinner) spinner.style.display = loading ? 'block' : 'none';
    if (tableWrap) tableWrap.style.opacity = loading ? '0.5' : '1';
  }

  function renderTable() {
    const tbody = el('historyTableBody');
    if (!tbody) return;

    tbody.innerHTML = '';

    if (filteredRemittances.length === 0) {
      renderEmptyTable('No payment transactions or remittance records found matching the selected filters.');
      return;
    }

    const totalPages = Math.ceil(filteredRemittances.length / pageSize) || 1;
    if (currentPage > totalPages) currentPage = totalPages;

    const startIdx = (currentPage - 1) * pageSize;
    const endIdx = startIdx + pageSize;
    const pageItems = filteredRemittances.slice(startIdx, endIdx);

    pageItems.forEach((r, i) => {
      const globalIdx = startIdx + i + 1;
      const tr = document.createElement('tr');
      tr.setAttribute('data-remittance-id', r.id);

      const isChecked = selectedRemittanceIds.has(r.id);
      const isSent = r.status === 'sent';
      const statusBadge = isSent
        ? `<span class="badge badge-success">Sent (x${r.resend_count || 1})</span>`
        : `<span class="badge badge-warning">Pending</span>`;

      const amtFormatted = `$${parseFloat(r.amount).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
      const formattedEffDate = r.effective_date ? r.effective_date.substring(0, 10) : '—';
      const formattedSentDate = r.sent_at ? r.sent_at.substring(0, 16).replace('T', ' ') : '—';

      let breakdownBadge = '';
      if (r.invoice_breakdown && r.invoice_breakdown.length > 1) {
        breakdownBadge = `<button type="button" class="btn btn-secondary btn-sm" onclick="HistoryScreen.openHistoryBreakdownModal(${globalIdx})" style="padding: 1px 6px; font-size: 10px; margin-left: 6px; vertical-align: middle; display: inline-flex; align-items: center; gap: 3px;" title="View itemized price breakdown">
          <span>${r.invoice_breakdown.length} Invoices</span>
          <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-search"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
        </button>`;
      }

      tr.innerHTML = `
        <td style="text-align: center;">
          <input type="checkbox" class="history-row-cb" data-remittance-id="${r.id}" ${isChecked ? 'checked' : ''} onchange="HistoryScreen.toggleRowSelection('${r.id}', this.checked)" />
        </td>
        <td class="font-mono">${globalIdx}</td>
        <td class="font-mono text-xs">${formattedEffDate}</td>
        <td class="font-bold">${r.vendor_name}</td>
        <td class="font-mono text-xs text-muted" id="email-cell-${r.id}">
          <div id="email-display-${r.id}" style="display: inline-flex; align-items: center; gap: 6px;">
            <span>${r.recipient_email}</span>
            <button type="button" class="btn btn-secondary btn-sm" onclick="HistoryScreen.editRowEmail('${r.id}')" style="padding: 1px 4px; font-size: 10px; line-height: 1;" title="Edit Recipient Email Address">
              <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-pencil"><path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/></svg>
            </button>
          </div>
          <div id="email-edit-${r.id}" style="display: none; align-items: center; gap: 4px;">
            <input type="email" class="form-input form-input-sm" id="email-input-${r.id}" value="${r.recipient_email}" style="padding: 2px 6px; font-size: 11px; width: 175px;" onkeydown="if(event.key==='Enter'){HistoryScreen.saveRowEmail('${r.id}');}if(event.key==='Escape'){HistoryScreen.cancelRowEmailEdit('${r.id}');}" />
            <button type="button" class="btn btn-primary btn-sm" onclick="HistoryScreen.saveRowEmail('${r.id}')" style="padding: 2px 6px; font-size: 10px;" title="Save Email">✓</button>
            <button type="button" class="btn btn-secondary btn-sm" onclick="HistoryScreen.cancelRowEmailEdit('${r.id}')" style="padding: 2px 6px; font-size: 10px;" title="Cancel">✕</button>
          </div>
        </td>
        <td class="font-mono font-bold">${amtFormatted} ${breakdownBadge}</td>
        <td class="font-mono text-xs">${r.invoice_reference || '—'}</td>
        <td class="font-mono text-xs"><span class="badge badge-secondary" style="background: #F1F5F9; color: #475569; border: 1px solid #E2E8F0; padding: 2px 6px;">${r.created_by_username || 'admin'}</span></td>
        <td>${statusBadge}</td>
        <td class="font-mono text-xs text-muted">${formattedSentDate}</td>
        <td style="text-align: right; white-space: nowrap;">
          <button type="button" class="btn btn-secondary btn-sm" onclick="HistoryScreen.sendSingleRemittanceEmail('${r.id}')" style="padding: 2px 6px; font-size: 10px; margin-right: 4px; display: inline-flex; align-items: center; gap: 3px;" title="Send Remittance Email to ${r.recipient_email}">
            <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-mail"><rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/></svg>
            <span>${isSent ? 'Resend' : 'Send'}</span>
          </button>
          ${isAdmin() ? `
          <button type="button" class="btn btn-sm" onclick="HistoryScreen.openConfirmDeleteSingleHistory('${r.id}')" style="background: #fef2f2; color: #dc2626; border: 1px solid #fecaca; padding: 2px 6px; font-weight: 600; font-size: 10px;" title="Delete Record (Admin Only)">
            🗑 Delete
          </button>` : ''}
        </td>
      `;

      tbody.appendChild(tr);
    });

    renderPaginationControls(filteredRemittances.length, totalPages);
    updateSelectAllCheckboxState();
  }

  function openHistoryBreakdownModal(globalIdx) {
    const r = filteredRemittances[globalIdx - 1];
    if (!r || !r.invoice_breakdown || r.invoice_breakdown.length === 0) return;

    if (el('breakdownVendorTitle')) el('breakdownVendorTitle').textContent = `Invoice Breakdown — ${r.vendor_name}`;
    if (el('breakdownTotalSubtitle')) el('breakdownTotalSubtitle').textContent = `Total Payment Amount: $${parseFloat(r.amount).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} (${r.invoice_breakdown.length} Invoices)`;

    const tbody = el('breakdownTableBody');
    if (tbody) {
      tbody.innerHTML = '';
      r.invoice_breakdown.forEach((item, i) => {
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

  function renderEmptyTable(message) {
    const tbody = el('historyTableBody');
    if (!tbody) return;
    tbody.innerHTML = `
      <tr>
        <td colspan="11" class="text-center text-muted" style="padding: var(--space-xl);">
          ${message}
        </td>
      </tr>
    `;
    renderPaginationControls(0, 1);
  }

  function renderPaginationControls(totalCount, totalPages) {
    const infoDisplay = el('historyPageInfoDisplay');
    const prevBtn = el('prevHistoryPageBtn');
    const nextBtn = el('nextHistoryPageBtn');

    if (infoDisplay) {
      if (totalCount === 0) {
        infoDisplay.textContent = 'Showing 0 records';
      } else {
        const start = (currentPage - 1) * pageSize + 1;
        const end = Math.min(currentPage * pageSize, totalCount);
        infoDisplay.textContent = `Page ${currentPage} of ${totalPages} (Showing ${start}-${end} of ${totalCount} records)`;
      }
    }

    if (prevBtn) prevBtn.disabled = currentPage <= 1;
    if (nextBtn) nextBtn.disabled = currentPage >= totalPages;
  }

  function changePage(delta) {
    currentPage += delta;
    renderTable();
  }

  // ── Multi-Select Checkboxes ──────────────────────────────────
  function toggleRowSelection(remittanceId, isChecked) {
    if (isChecked) {
      selectedRemittanceIds.add(remittanceId);
    } else {
      selectedRemittanceIds.delete(remittanceId);
    }
    updateBulkBar();
    updateSelectAllCheckboxState();
  }

  function handleSelectAll(e) {
    const isChecked = e.target.checked;
    const startIdx = (currentPage - 1) * pageSize;
    const pageItems = filteredRemittances.slice(startIdx, startIdx + pageSize);

    pageItems.forEach(r => {
      if (isChecked) {
        selectedRemittanceIds.add(r.id);
      } else {
        selectedRemittanceIds.delete(r.id);
      }
    });

    document.querySelectorAll('.history-row-cb').forEach(cb => {
      cb.checked = isChecked;
    });

    updateBulkBar();
  }

  function updateSelectAllCheckboxState() {
    const selectAllCb = el('historySelectAllCb');
    if (!selectAllCb) return;

    const startIdx = (currentPage - 1) * pageSize;
    const pageItems = filteredRemittances.slice(startIdx, startIdx + pageSize);
    if (pageItems.length === 0) {
      selectAllCb.checked = false;
      return;
    }

    const allChecked = pageItems.every(r => selectedRemittanceIds.has(r.id));
    selectAllCb.checked = allChecked;
  }

  function updateBulkBar() {
    const bar = el('historyBulkBar');
    const countDisplay = el('historySelectedCount');
    const amtDisplay = el('historySelectedAmount');
    const bulkDeleteBtn = el('bulkDeleteHistoryBtn');
    if (!bar) return;

    const count = selectedRemittanceIds.size;
    if (count > 0) {
      bar.style.display = 'flex';
      if (countDisplay) countDisplay.textContent = count;

      let totalAmt = 0;
      allRemittances.forEach(r => {
        if (selectedRemittanceIds.has(r.id)) {
          totalAmt += parseFloat(r.amount);
        }
      });

      if (amtDisplay) amtDisplay.textContent = '$' + totalAmt.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      if (bulkDeleteBtn) bulkDeleteBtn.style.display = isAdmin() ? 'inline-block' : 'none';
    } else {
      bar.style.display = 'none';
    }
  }

  // ── History Deletion Workflow (Admin Only) ───────────────────
  function openConfirmDeleteSingleHistory(id) {
    const item = allRemittances.find(r => r.id === id);
    if (!item) return;
    historyToDelete = [item];
    showDeleteHistoryConfirmationModal();
  }

  function openConfirmDeleteSelectionHistory() {
    if (selectedRemittanceIds.size === 0) return;
    historyToDelete = allRemittances.filter(r => selectedRemittanceIds.has(r.id));
    showDeleteHistoryConfirmationModal();
  }

  function showDeleteHistoryConfirmationModal() {
    const modal = el('confirmDeleteHistoryModal');
    const warningBox = el('pendingDeletionSevereWarning');
    const msgEl = el('confirmDeleteHistoryMessage');
    const titleEl = el('confirmDeleteHistoryTitle');
    const listEl = el('deleteHistoryListText');

    if (!modal) return;

    if (warningBox) warningBox.style.display = 'none';

    const count = historyToDelete.length;
    const vendorName = count === 1 ? historyToDelete[0].vendor_name : '';
    const hasPending = historyToDelete.some(r => String(r.status).toLowerCase() === 'pending');

    if (titleEl) {
      titleEl.textContent = count === 1 ? 'Delete Payment Record' : 'Delete Selected Records';
    }

    if (msgEl) {
      let text = count === 1
        ? `Are you sure you want to delete the payment record for <strong>${vendorName}</strong>?`
        : `Are you sure you want to delete <strong>${count} selected payment records</strong>?`;

      if (hasPending) {
        text += ` <span style="color: #dc2626; font-size: 12px; font-weight: 500;">(Remittance email will not be sent).</span>`;
      }
      msgEl.innerHTML = text;
    }

    if (listEl) {
      if (count > 1) {
        listEl.style.display = 'block';
        listEl.innerHTML = historyToDelete.map(r => `• ${r.vendor_name} — $${r.amount}`).join('<br/>');
      } else {
        listEl.style.display = 'none';
      }
    }

    modal.classList.add('active');
    modal.style.display = 'flex';
  }

  function hideDeleteHistoryModal() {
    const modal = el('confirmDeleteHistoryModal');
    if (modal) {
      modal.classList.remove('active');
      modal.style.display = 'none';
    }
  }

  async function executeHistoryDeletion() {
    if (historyToDelete.length === 0) return;

    const spinner = el('executeDeleteHistorySpinner');
    const executeBtn = el('executeDeleteHistoryBtn');

    if (executeBtn) executeBtn.disabled = true;
    if (spinner) spinner.style.display = 'inline-block';

    try {
      if (historyToDelete.length === 1) {
        await API.del(`/remittances/${historyToDelete[0].id}`);
      } else {
        const remittance_ids = historyToDelete.map(r => r.id);
        await API.post('/remittances/bulk-delete', { remittance_ids });
      }

      hideDeleteHistoryModal();
      selectedRemittanceIds.clear();
      updateBulkBar();
      await loadData();
    } catch (err) {
      alert(err.message || 'Failed to delete transaction history record(s).');
    } finally {
      if (executeBtn) executeBtn.disabled = false;
      if (spinner) spinner.style.display = 'none';
    }
  }

  // ── Confirmation Modal & Bulk Resend Workflow ────────────────
  function openConfirmModal() {
    if (selectedRemittanceIds.size === 0) return;

    const modal = el('bulkResendConfirmModal');
    const countSpan = el('confirmModalCount');
    const amtSpan = el('confirmModalTotalAmount');
    const listContainer = el('confirmModalVendorList');
    const errBox = el('confirmModalError');

    if (errBox) errBox.style.display = 'none';

    const selectedList = allRemittances.filter(r => selectedRemittanceIds.has(r.id));

    if (countSpan) countSpan.textContent = selectedList.length;

    let totalAmt = 0;
    if (listContainer) listContainer.innerHTML = '';

    selectedList.forEach(r => {
      totalAmt += parseFloat(r.amount);
      if (listContainer) {
        const item = document.createElement('div');
        item.style.padding = '6px 10px';
        item.style.borderBottom = '1px solid var(--color-border)';
        item.style.fontSize = 'var(--text-xs)';
        item.innerHTML = `
          <strong>${r.vendor_name}</strong> &lt;${r.recipient_email}&gt; — 
          <span class="font-mono font-bold">$${parseFloat(r.amount).toFixed(2)}</span> 
          (Ref: ${r.invoice_reference || 'N/A'})
        `;
        listContainer.appendChild(item);
      }
    });

    if (amtSpan) amtSpan.textContent = `$${totalAmt.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

    if (modal) {
      modal.classList.add('active');
      modal.style.display = 'flex';
    }
  }

  function hideConfirmModal() {
    const modal = el('bulkResendConfirmModal');
    if (modal) {
      modal.classList.remove('active');
      modal.style.display = 'none';
    }
  }

  async function handleExecuteBulkResend() {
    const ids = Array.from(selectedRemittanceIds);
    if (ids.length === 0) return;

    const spinner = el('resendSpinner');
    const confirmBtn = el('confirmBulkResendBtn');
    const errBox = el('confirmModalError');

    if (confirmBtn) confirmBtn.disabled = true;
    if (spinner) spinner.style.display = 'inline-block';
    if (errBox) errBox.style.display = 'none';

    try {
      const response = await API.post('/remittances/bulk-resend', {
        remittance_ids: ids,
      });

      hideConfirmModal();

      // Show alert notice
      const globalAlert = el('historyGlobalAlert');
      if (globalAlert) {
        globalAlert.className = 'alert alert-success show';
        globalAlert.textContent = response.message || `Successfully resent ${response.success_count} remittance email(s).`;
        globalAlert.style.display = 'block';
        setTimeout(() => { globalAlert.style.display = 'none'; }, 4000);
      }

      // Reload history data to show updated 'SENT' status
      await loadData();
    } catch (err) {
      if (errBox) {
        errBox.textContent = err.message || 'Failed to dispatch bulk remittance emails.';
        errBox.style.display = 'block';
      }
    } finally {
      if (confirmBtn) confirmBtn.disabled = false;
      if (spinner) spinner.style.display = 'none';
    }
  }

  // ── Last NACHA File Modal Workflow ─────────────────────────────
  let cachedLatestNacha = null;

  async function openLastNachaFileModal() {
    const modal = el('lastNachaFileModal');
    const errBox = el('lastNachaModalError');
    const rawBox = el('lastNachaRawContent');
    const filenameEl = el('lastNachaFilename');
    const dateEl = el('lastNachaCreationDate');
    const amountEl = el('lastNachaTotalAmount');
    const countEl = el('lastNachaEntryCount');
    const hashEl = el('lastNachaEntryHash');

    if (!modal) return;
    if (errBox) errBox.style.display = 'none';
    if (rawBox) rawBox.textContent = 'Loading latest NACHA file content...';

    modal.classList.add('active');
    modal.style.display = 'flex';

    try {
      const latest = await API.get('/nacha/latest');
      cachedLatestNacha = latest;

      if (filenameEl) filenameEl.textContent = latest.filename || 'NACHA.ach';
      if (dateEl) dateEl.textContent = `${latest.file_creation_date || ''} ${latest.file_creation_time || ''}`.trim() || '—';
      if (amountEl) amountEl.textContent = `$${parseFloat(latest.total_credit_amount || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
      if (countEl) countEl.textContent = latest.total_entry_count || 0;
      if (hashEl) hashEl.textContent = latest.entry_hash || '—';

      if (rawBox && latest.raw_content) {
        const lines = latest.raw_content.split('\n');
        rawBox.textContent = lines.map((line, idx) => `${String(idx + 1).padStart(2, '0')}: ${line}`).join('\n');
      }
    } catch (err) {
      if (errBox) {
        errBox.textContent = err.message || 'No NACHA ACH files have been generated yet.';
        errBox.style.display = 'block';
      }
      if (rawBox) rawBox.textContent = 'No NACHA file data available.';
    }
  }

  function hideLastNachaFileModal() {
    const modal = el('lastNachaFileModal');
    if (modal) {
      modal.classList.remove('active');
      modal.style.display = 'none';
    }
  }

  function handleCopyLastNacha() {
    if (!cachedLatestNacha || !cachedLatestNacha.raw_content) return;
    navigator.clipboard.writeText(cachedLatestNacha.raw_content).then(() => {
      const copyBtn = el('lastNachaCopyBtn');
      if (copyBtn) {
        const origText = copyBtn.innerHTML;
        copyBtn.innerHTML = '✓ Copied!';
        setTimeout(() => { copyBtn.innerHTML = origText; }, 2000);
      }
    }).catch(err => {
      alert('Failed to copy to clipboard: ' + err);
    });
  }

  function handleDownloadLastNacha() {
    if (!cachedLatestNacha || !cachedLatestNacha.raw_content) return;
    const blob = new Blob([cachedLatestNacha.raw_content], { type: 'text/plain;charset=utf-8;' });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    link.setAttribute('href', url);
    link.setAttribute('download', cachedLatestNacha.filename || 'NACHA_file.ach');
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  // ── Inline Email Editing & Single Dispatch Handlers ─────────
  function editRowEmail(id) {
    const disp = el(`email-display-${id}`);
    const edit = el(`email-edit-${id}`);
    const input = el(`email-input-${id}`);
    if (disp) disp.style.display = 'none';
    if (edit) edit.style.display = 'inline-flex';
    if (input) {
      input.focus();
      input.select();
    }
  }

  function cancelRowEmailEdit(id) {
    const disp = el(`email-display-${id}`);
    const edit = el(`email-edit-${id}`);
    if (disp) disp.style.display = 'inline-flex';
    if (edit) edit.style.display = 'none';
  }

  async function saveRowEmail(id) {
    const input = el(`email-input-${id}`);
    if (!input) return;
    const newEmail = input.value.trim();

    if (!newEmail || !newEmail.includes('@') || !newEmail.includes('.')) {
      alert('Please enter a valid email address.');
      return;
    }

    try {
      const updated = await API.patch(`/remittances/${id}/email`, { recipient_email: newEmail });
      const item = allRemittances.find(r => r.id === id);
      if (item) item.recipient_email = updated.recipient_email;
      const filteredItem = filteredRemittances.find(r => r.id === id);
      if (filteredItem) filteredItem.recipient_email = updated.recipient_email;

      renderTable();

      const globalAlert = el('historyGlobalAlert');
      if (globalAlert) {
        globalAlert.className = 'alert alert-success show';
        globalAlert.textContent = `Email for "${updated.vendor_name}" updated to "${updated.recipient_email}".`;
        globalAlert.style.display = 'block';
        setTimeout(() => { globalAlert.style.display = 'none'; }, 3500);
      }
    } catch (err) {
      alert(err.message || 'Failed to update remittance email.');
    }
  }

  async function sendSingleRemittanceEmail(id) {
    const item = allRemittances.find(r => r.id === id);
    if (!item) return;

    if (!confirm(`Send remittance advice email to "${item.vendor_name}" at <${item.recipient_email}>?`)) return;

    try {
      const response = await API.post('/remittances/bulk-resend', {
        remittance_ids: [id],
      });

      const globalAlert = el('historyGlobalAlert');
      if (globalAlert) {
        globalAlert.className = 'alert alert-success show';
        globalAlert.textContent = response.message || `Remittance email successfully sent to ${item.vendor_name} <${item.recipient_email}>.`;
        globalAlert.style.display = 'block';
        setTimeout(() => { globalAlert.style.display = 'none'; }, 4000);
      }

      await loadData();
    } catch (err) {
      alert(err.message || 'Failed to send remittance email.');
    }
  }

  return {
    init,
    loadData,
    toggleRowSelection,
    insertPlaceholder,
    openHistoryBreakdownModal,
    openConfirmDeleteSingleHistory,
    openLastNachaFileModal,
    editRowEmail,
    cancelRowEmailEdit,
    saveRowEmail,
    sendSingleRemittanceEmail,
  };
})();

document.addEventListener('DOMContentLoaded', () => {
  HistoryScreen.init();
});
