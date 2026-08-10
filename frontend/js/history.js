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

    const prevBtn = el('prevHistoryPageBtn');
    const nextBtn = el('nextHistoryPageBtn');
    if (prevBtn) prevBtn.addEventListener('click', () => changePage(-1));
    if (nextBtn) nextBtn.addEventListener('click', () => changePage(1));

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
      renderTable();
    } catch (err) {
      console.warn('Failed to load remittance payment history:', err);
      renderEmptyTable(err.message || 'Failed to load transaction history.');
    } finally {
      setLoading(false);
    }
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

      tr.innerHTML = `
        <td style="text-align: center;">
          <input type="checkbox" class="history-row-cb" data-remittance-id="${r.id}" ${isChecked ? 'checked' : ''} onchange="HistoryScreen.toggleRowSelection('${r.id}', this.checked)" />
        </td>
        <td class="font-mono">${globalIdx}</td>
        <td class="font-mono text-xs">${formattedEffDate}</td>
        <td class="font-bold">${r.vendor_name}</td>
        <td class="font-mono text-xs text-muted">${r.recipient_email}</td>
        <td class="font-mono font-bold">${amtFormatted}</td>
        <td class="font-mono text-xs">${r.invoice_reference || '—'}</td>
        <td>${statusBadge}</td>
        <td class="font-mono text-xs text-muted">${formattedSentDate}</td>
      `;

      tbody.appendChild(tr);
    });

    renderPaginationControls(filteredRemittances.length, totalPages);
    updateSelectAllCheckboxState();
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
  };
})();

document.addEventListener('DOMContentLoaded', () => {
  HistoryScreen.init();
});
