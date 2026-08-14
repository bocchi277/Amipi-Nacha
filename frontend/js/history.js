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

  function el(id) { return document.getElementById(id); }

  function init() {
    bindEvents();
  }

  function bindEvents() {
    const applyBtn = el('applyHistoryFiltersBtn');
    if (applyBtn) applyBtn.addEventListener('click', loadData);

    const resetBtn = el('resetHistoryFiltersBtn');
    if (resetBtn) resetBtn.addEventListener('click', resetFilters);

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
    const clearHistoryBtn = el('clearHistoryBtn');

    if (exportCsvBtn) exportCsvBtn.addEventListener('click', handleExportCSV);
    if (exportExcelBtn) exportExcelBtn.addEventListener('click', handleExportExcel);
    if (saveJsonBtn) saveJsonBtn.addEventListener('click', handleSaveJSON);
    if (loadJsonBtn) loadJsonBtn.addEventListener('click', handleLoadJSON);
    if (clearHistoryBtn) clearHistoryBtn.addEventListener('click', handleClearHistory);

    // Auto-load when switching to view-history tab
    document.querySelectorAll('#mainTabs .tab').forEach(tab => {
      tab.addEventListener('click', () => {
        if (tab.dataset.view === 'history') {
          loadVendorsDropdown();
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

    if (modal) modal.classList.add('active');
  }

  function hideEmailTemplateModal() {
    const modal = el('emailTemplateModal');
    if (modal) modal.classList.remove('active');
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


  async function loadVendorsDropdown() {
    const select = el('historyVendorFilter');
    if (!select || select.options.length > 1) return;

    try {
      const vendors = await API.get('/vendors');
      loadedVendors = vendors || [];
      select.innerHTML = '<option value="">All Vendors</option>';
      loadedVendors.forEach(v => {
        const opt = document.createElement('option');
        opt.value = v.id;
        opt.textContent = v.name;
        select.appendChild(opt);
      });
    } catch (err) {
      console.warn('Failed to load vendors for history filter:', err);
    }
  }

  async function loadData() {
    if (!API.isAuthenticated()) return;

    setLoading(true);
    selectedRemittanceIds.clear();
    updateBulkBar();

    const vendorId = el('historyVendorFilter') ? el('historyVendorFilter').value : '';
    const statusVal = el('historyStatusFilter') ? el('historyStatusFilter').value : '';
    const startDate = el('historyStartDate') ? el('historyStartDate').value : '';
    const endDate = el('historyEndDate') ? el('historyEndDate').value : '';
    const search = el('historySearchInput') ? el('historySearchInput').value.trim() : '';

    const params = new URLSearchParams();
    if (vendorId) params.append('vendor_id', vendorId);
    if (statusVal) params.append('status', statusVal);
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);
    if (search) params.append('search', search);

    const queryString = params.toString() ? `?${params.toString()}` : '';

    try {
      const data = await API.get(`/remittances${queryString}`);
      allRemittances = data || [];
      filteredRemittances = [...allRemittances];
      currentPage = 1;
      updateKPIs();
      renderTable();
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
    handleExportCSV();
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

  function resetFilters() {
    if (el('historyVendorFilter')) el('historyVendorFilter').value = '';
    if (el('historyStatusFilter')) el('historyStatusFilter').value = '';
    if (el('historyStartDate')) el('historyStartDate').value = '';
    if (el('historyEndDate')) el('historyEndDate').value = '';
    if (el('historySearchInput')) el('historySearchInput').value = '';
    loadData();
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
        <td class="font-mono text-xs text-muted">${r.recipient_email}</td>
        <td class="font-mono font-bold">${amtFormatted} ${breakdownBadge}</td>
        <td class="font-mono text-xs">${r.invoice_reference || '—'}</td>
        <td>${statusBadge}</td>
        <td class="font-mono text-xs text-muted">${formattedSentDate}</td>
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
        <td colspan="9" class="text-center text-muted" style="padding: var(--space-xl);">
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

      if (amtDisplay) amtDisplay.textContent = totalAmt.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    } else {
      bar.style.display = 'none';
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

    if (modal) modal.classList.add('active');
  }

  function hideConfirmModal() {
    const modal = el('bulkResendConfirmModal');
    if (modal) modal.classList.remove('active');
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

  return {
    init,
    loadData,
    toggleRowSelection,
    insertPlaceholder,
    openHistoryBreakdownModal,
  };
})();

document.addEventListener('DOMContentLoaded', () => {
  HistoryScreen.init();
});
