/**
 * AMIPI NACHA ACH Payment System — Help & Downloadable Templates Controller
 *
 * Provides real file downloads for Batch 1 spreadsheet payment templates and vendor import templates,
 * formatted to match backend parser specs (spreadsheet_parser.py).
 */

const HelpScreen = (() => {
  function el(id) { return document.getElementById(id); }

  function init() {
    bindEvents();
  }

  function bindEvents() {
    // Help screen template buttons
    const btnPayHelp = el('downloadPaymentTemplateBtnHelp');
    if (btnPayHelp) btnPayHelp.addEventListener('click', downloadPaymentTemplate);

    const btnVenHelp = el('downloadVendorTemplateBtnHelp');
    if (btnVenHelp) btnVenHelp.addEventListener('click', downloadVendorTemplate);

    // Batch 1 Upload screen shortcut download buttons
    const btnPayUpload = el('downloadPaymentTemplateBtnUpload');
    if (btnPayUpload) btnPayUpload.addEventListener('click', downloadPaymentTemplate);

    // Variable insertion buttons
    const bVendor = el('btnVarVendor');
    const bAmt = el('btnVarAmount');
    const bInv = el('btnVarInvoice');
    const bDate = el('btnVarDate');
    const bComp = el('btnVarCompany');

    if (bVendor) bVendor.addEventListener('click', () => insertVar('{{vendor_name}}'));
    if (bAmt) bAmt.addEventListener('click', () => insertVar('{{amount}}'));
    if (bInv) bInv.addEventListener('click', () => insertVar('{{invoice_ref}}'));
    if (bDate) bDate.addEventListener('click', () => insertVar('{{effective_date}}'));
    if (bComp) bComp.addEventListener('click', () => insertVar('{{company_name}}'));

    // Live real-time preview listeners
    const subjInput = el('helpTmplSubject');
    const bodyInput = el('helpTmplBody');
    if (subjInput) subjInput.addEventListener('input', updateLivePreview);
    if (bodyInput) bodyInput.addEventListener('input', updateLivePreview);

    // Save and Reset buttons
    const saveBtn = el('saveHelpTmplBtn');
    const resetBtn = el('resetHelpTmplBtn');
    if (saveBtn) saveBtn.addEventListener('click', handleSaveTemplate);
    if (resetBtn) resetBtn.addEventListener('click', resetToDefault);

    // Load template data when switching to Help tab
    document.querySelectorAll('#mainTabs .tab').forEach(tab => {
      tab.addEventListener('click', () => {
        if (tab.dataset.view === 'help') {
          loadTemplateData();
        }
      });
    });

    // Initial load if starting on Help tab
    loadTemplateData();
  }

  async function loadTemplateData() {
    if (typeof API === 'undefined' || !API.isAuthenticated()) return;
    try {
      const data = await API.get('/remittances/template');
      if (el('helpTmplSubject')) el('helpTmplSubject').value = data.subject_template || '';
      if (el('helpTmplBody')) el('helpTmplBody').value = data.body_template || '';
      updateLivePreview();
    } catch (err) {
      console.warn('Failed to load email template:', err);
    }
  }

  function insertVar(tag) {
    const subjInput = el('helpTmplSubject');
    const bodyInput = el('helpTmplBody');

    const activeEl = document.activeElement === subjInput ? subjInput : bodyInput;
    if (!activeEl) return;

    const start = activeEl.selectionStart || activeEl.value.length;
    const end = activeEl.selectionEnd || activeEl.value.length;
    const text = activeEl.value;

    activeEl.value = text.substring(0, start) + tag + text.substring(end);
    activeEl.focus();
    activeEl.selectionStart = activeEl.selectionEnd = start + tag.length;

    updateLivePreview();
  }

  function updateLivePreview() {
    const subjVal = el('helpTmplSubject') ? el('helpTmplSubject').value : '';
    const bodyVal = el('helpTmplBody') ? el('helpTmplBody').value : '';

    const sampleContext = {
      '{{vendor_name}}': 'AMIPI INC',
      '{{amount}}': '53,413.06',
      '{{invoice_ref}}': 'INV-128753',
      '{{effective_date}}': '05-19-2026',
      '{{company_name}}': 'AMIPI INC',
    };

    let renderedSubj = subjVal;
    let renderedBody = bodyVal;

    Object.keys(sampleContext).forEach(key => {
      const val = sampleContext[key];
      renderedSubj = renderedSubj.replaceAll(key, val);
      renderedBody = renderedBody.replaceAll(key, val);
    });

    if (el('previewSubject')) el('previewSubject').textContent = renderedSubj || 'Payment Remittance Advice — AMIPI INC ($53,413.06)';
    if (el('previewBody')) el('previewBody').textContent = renderedBody || '—';

    // Format paragraphs
    const paragraphs = (renderedBody || '').split('\n\n');
    const htmlParagraphs = paragraphs
      .filter(p => p.trim())
      .map(p => `<p style="margin: 0 0 10px 0; font-size: 13px; line-height: 1.5; color: #1e293b;">${p.replace(/\n/g, '<br/>')}</p>`)
      .join('');

    // Generate Tabular Section matching sample template
    const sampleTableHtml = `
      <div style="margin-top: 14px; margin-bottom: 16px;">
        <table style="width: 100%; border-collapse: collapse; font-family: Arial, Helvetica, sans-serif; font-size: 12px; border: 1px solid #94a3b8;">
          <thead>
            <tr style="background-color: #8bbcdb; color: #0f172a;">
              <th colspan="4" style="text-align: right; padding: 6px 10px; font-weight: 600; font-size: 12px; border-bottom: 1px solid #64748b;">
                2 Payment Transaction records
              </th>
            </tr>
            <tr style="background-color: #e2e8f0; color: #1e293b; text-align: left; font-size: 11px;">
              <th style="padding: 6px 8px; border: 1px solid #cbd5e1; width: 25%; font-weight: 600;">Method of Payment</th>
              <th style="padding: 6px 8px; border: 1px solid #cbd5e1; width: 25%; font-weight: 600;">Invoice Date</th>
              <th style="padding: 6px 8px; border: 1px solid #cbd5e1; width: 25%; font-weight: 600;">Invoice #</th>
              <th style="padding: 6px 8px; border: 1px solid #cbd5e1; width: 25%; text-align: right; font-weight: 600;">Amount</th>
            </tr>
          </thead>
          <tbody>
            <tr style="background-color: #ffffff;">
              <td style="padding: 6px 8px; border: 1px solid #cbd5e1; color: #334155;">ACH/Wire</td>
              <td style="padding: 6px 8px; border: 1px solid #cbd5e1; color: #334155;">05-19-2026</td>
              <td style="padding: 6px 8px; border: 1px solid #cbd5e1; color: #1d4ed8; font-weight: 600;">128753</td>
              <td style="padding: 6px 8px; border: 1px solid #cbd5e1; text-align: right; font-family: monospace; color: #0f172a;">$22,094.82</td>
            </tr>
            <tr style="background-color: #f8fafc;">
              <td style="padding: 6px 8px; border: 1px solid #cbd5e1; color: #334155;">ACH/Wire</td>
              <td style="padding: 6px 8px; border: 1px solid #cbd5e1; color: #334155;">05-21-2026</td>
              <td style="padding: 6px 8px; border: 1px solid #cbd5e1; color: #1d4ed8; font-weight: 600;">128779</td>
              <td style="padding: 6px 8px; border: 1px solid #cbd5e1; text-align: right; font-family: monospace; color: #0f172a;">$31,318.24</td>
            </tr>
          </tbody>
          <tfoot>
            <tr style="background-color: #f1f5f9; font-weight: bold; border-top: 2px solid #64748b;">
              <td colspan="3" style="padding: 6px 8px; border: 1px solid #cbd5e1; font-weight: 700; color: #0f172a;">TOT</td>
              <td style="padding: 6px 8px; border: 1px solid #cbd5e1; text-align: right; font-family: monospace; color: #0f172a; font-size: 12px; font-weight: 700;">$53,413.06</td>
            </tr>
          </tfoot>
        </table>
        <p style="margin: 16px 0 4px 0; font-size: 12px; color: #64748b;">If you have any questions regarding this payment remittance, please contact Accounts Payable.</p>
        <p style="margin: 0; font-size: 12px; color: #334155; font-weight: 600;">AMIPI INC Accounts Payable</p>
      </div>
    `;

    const previewContainer = el('helpPreviewHtmlContainer');
    if (previewContainer) {
      previewContainer.innerHTML = htmlParagraphs + sampleTableHtml;
    }
  }

  function resetToDefault() {
    if (el('helpTmplSubject')) {
      el('helpTmplSubject').value = 'Payment Remittance Advice — {{vendor_name}} (${{amount}})';
    }
    if (el('helpTmplBody')) {
      el('helpTmplBody').value = `Dear {{vendor_name}},\n\nWe would like to inform you that we have processed the following payment and applied the invoices accordingly.\n\nPayment Amount: \${{amount}}\nEffective Date: {{effective_date}}\n\nInvoices applied:`;
    }
    updateLivePreview();
  }

  async function handleSaveTemplate() {
    const subjectVal = el('helpTmplSubject') ? el('helpTmplSubject').value.trim() : '';
    const bodyVal = el('helpTmplBody') ? el('helpTmplBody').value.trim() : '';

    const errBox = el('helpTmplError');
    const succBox = el('helpTmplSuccess');
    const spinner = el('helpTmplSpinner');
    const saveBtn = el('saveHelpTmplBtn');

    if (errBox) errBox.style.display = 'none';
    if (succBox) succBox.style.display = 'none';

    if (!subjectVal || !bodyVal) {
      if (errBox) {
        errBox.textContent = 'Both Subject Line and Message Content are required.';
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
        succBox.textContent = 'Remittance email template saved successfully! All future payment notifications will use this wording.';
        succBox.style.display = 'block';
        setTimeout(() => { succBox.style.display = 'none'; }, 4000);
      }
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

  function downloadPaymentTemplate() {

    const csvContent = [
      'Vendor Name,Routing Number,Account Number,Account Type,Amount,Invoice Number',
      'EXAMPLE VENDOR LLC,021000021,1234567890,Checking,1500.00,INV-1001',
      'GLOBAL METALS INC,026013356,9876543210,Checking,2750.50,INV-1002',
    ].join('\r\n');

    triggerFileDownload('payment_import_template.csv', csvContent, 'text/csv;charset=utf-8;');
  }

  function downloadVendorTemplate() {
    const csvContent = [
      'name,routing,account,type,email',
      'ACME SUPPLIES,021000021,999888777666,Checking,ap@acmesupplies.com',
      'GLOBAL METALS INC,026013356,112233445566,Checking,billing@globalmetals.com',
    ].join('\r\n');

    triggerFileDownload('vendor_import_template.csv', csvContent, 'text/csv;charset=utf-8;');
  }

  function triggerFileDownload(filename, content, mimeType) {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.setAttribute('href', url);
    link.setAttribute('download', filename);
    link.style.display = 'none';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }

  return {
    init,
    downloadPaymentTemplate,
    downloadVendorTemplate,
  };
})();

document.addEventListener('DOMContentLoaded', () => {
  HelpScreen.init();
});
