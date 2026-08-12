/**
 * AMIPI NACHA ACH Payment System — Security Audit Trail Controller (Admin Only)
 *
 * Fetches filterable, immutable audit logs from GET /api/v1/audit-logs
 * and renders formatted action badges, user info, and JSON details payload.
 */

const AuditScreen = (() => {
  let loadedLogs = [];

  function el(id) { return document.getElementById(id); }

  function init() {
    bindEvents();
  }

  function bindEvents() {
    const refreshBtn = el('refreshAuditLogsBtn');
    if (refreshBtn) refreshBtn.addEventListener('click', loadAuditLogs);

    const filterInput = el('auditActionFilter');
    if (filterInput) filterInput.addEventListener('input', filterAndRenderLogs);

    // Auto-reload when switching to view-audit-logs tab
    document.querySelectorAll('#mainTabs .tab').forEach(tab => {
      tab.addEventListener('click', () => {
        if (tab.dataset.view === 'audit-logs') {
          loadAuditLogs();
        }
      });
    });
  }

  async function loadAuditLogs() {
    if (typeof API === 'undefined' || !API.isAuthenticated()) return;

    const user = API.getUser();
    const isAdmin = user && user.role === 'admin';

    const deniedBox = el('auditAccessDeniedBox');
    const container = el('auditContainer');

    if (!isAdmin) {
      if (deniedBox) deniedBox.style.display = 'block';
      if (container) container.style.display = 'none';
      return;
    }

    if (deniedBox) deniedBox.style.display = 'none';
    if (container) container.style.display = 'block';

    setLoading(true);

    try {
      const data = await API.get('/audit-logs?limit=200');
      loadedLogs = data || [];
      filterAndRenderLogs();
    } catch (err) {
      console.warn('Failed to load audit logs:', err);
      renderEmptyTable(err.message || 'Failed to retrieve security audit trail logs.');
    } finally {
      setLoading(false);
    }
  }

  function setLoading(loading) {
    const spinner = el('auditSpinner');
    if (spinner) spinner.style.display = loading ? 'inline-block' : 'none';
  }

  function filterAndRenderLogs() {
    const filterInput = el('auditActionFilter');
    const term = filterInput ? filterInput.value.trim().toLowerCase() : '';

    const filtered = loadedLogs.filter(l =>
      (l.action && l.action.toLowerCase().includes(term)) ||
      (l.username && l.username.toLowerCase().includes(term)) ||
      (l.entity_type && l.entity_type.toLowerCase().includes(term))
    );

    renderAuditTable(filtered);
  }

  function renderAuditTable(logs) {
    const tbody = el('auditTableBody');
    if (!tbody) return;

    tbody.innerHTML = '';

    if (logs.length === 0) {
      renderEmptyTable('No audit logs found matching the selected filter.');
      return;
    }

    logs.forEach((l, idx) => {
      const tr = document.createElement('tr');
      tr.style.borderBottom = '1px solid var(--border-color, #e2e8f0)';
      tr.style.background = idx % 2 === 0 ? 'var(--color-surface, #ffffff)' : 'var(--color-surface-alt, #f8fafc)';

      const timeFormatted = l.timestamp ? l.timestamp.substring(0, 19).replace('T', ' ') : '—';
      const actionBadge = getActionBadge(l.action);

      let detailsHtml = '—';
      if (l.details && Object.keys(l.details).length > 0) {
        const detailsStr = Object.entries(l.details)
          .map(([k, v]) => `<strong>${k}:</strong> ${typeof v === 'object' ? JSON.stringify(v) : v}`)
          .join(' | ');
        detailsHtml = `<span style="font-family: monospace; font-size: 11px; color: var(--color-text-muted);">${detailsStr}</span>`;
      }

      tr.innerHTML = `
        <td style="padding: 10px 16px;" class="font-mono text-xs text-muted">${timeFormatted}</td>
        <td style="padding: 10px 16px;"><strong>${l.username}</strong></td>
        <td style="padding: 10px 16px;">${actionBadge}</td>
        <td style="padding: 10px 16px;" class="font-mono text-xs">${l.entity_type || 'System'} ${l.entity_id ? '(' + l.entity_id.substring(0, 8) + '...)' : ''}</td>
        <td style="padding: 10px 16px;">${detailsHtml}</td>
      `;

      tbody.appendChild(tr);
    });
  }

  function renderEmptyTable(msg) {
    const tbody = el('auditTableBody');
    if (!tbody) return;
    tbody.innerHTML = `
      <tr>
        <td colspan="5" style="padding: 24px; text-align: center; color: var(--color-text-muted);">
          ${msg}
        </td>
      </tr>
    `;
  }

  function getActionBadge(action) {
    if (!action) return '<span class="badge badge-secondary">EVENT</span>';

    const actUpper = action.toUpperCase();
    if (actUpper.includes('APPROVED') || actUpper.includes('GENERATED')) {
      return `<span class="badge badge-success">${action}</span>`;
    }
    if (actUpper.includes('REJECTED') || actUpper.includes('FAILED')) {
      return `<span class="badge badge-danger">${action}</span>`;
    }
    if (actUpper.includes('REQUESTED') || actUpper.includes('PENDING')) {
      return `<span class="badge badge-warning">${action}</span>`;
    }
    return `<span class="badge badge-primary">${action}</span>`;
  }

  return {
    init,
    loadAuditLogs,
  };
})();

document.addEventListener('DOMContentLoaded', () => {
  AuditScreen.init();
});
