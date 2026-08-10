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
