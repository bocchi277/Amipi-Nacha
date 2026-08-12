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
      '{{vendor_name}}': 'ARTN DESIGN INC',
      '{{amount}}': '700.75',
      '{{invoice_ref}}': 'ACH/1139',
      '{{effective_date}}': '2026-08-12',
      '{{company_name}}': 'AMIPI INC',
    };

    let renderedSubj = subjVal;
    let renderedBody = bodyVal;

    Object.keys(sampleContext).forEach(key => {
      const val = sampleContext[key];
      renderedSubj = renderedSubj.replaceAll(key, val);
      renderedBody = renderedBody.replaceAll(key, val);
    });

    if (el('previewSubject')) el('previewSubject').textContent = renderedSubj || '—';
    if (el('previewBody')) el('previewBody').textContent = renderedBody || '—';
  }

  function resetToDefault() {
    if (el('helpTmplSubject')) {
      el('helpTmplSubject').value = 'Payment Remittance Advice — {{vendor_name}} (${{amount}})';
    }
    if (el('helpTmplBody')) {
      el('helpTmplBody').value = `Dear {{vendor_name}},\n\nPlease be advised that an ACH payment of \${{amount}} has been scheduled for effective date {{effective_date}}.\n\nPayment Details:\n• Payee / Vendor Name: {{vendor_name}}\n• Payment Amount ($):  \${{amount}}\n• Invoice Reference:   {{invoice_ref}}\n• Effective Date:      {{effective_date}}\n\nIf you have any questions regarding this remittance, please contact Accounts Payable.\n\nThank you,\n{{company_name}} Accounts Payable`;
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
