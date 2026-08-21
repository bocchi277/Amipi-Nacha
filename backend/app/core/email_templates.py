"""
Remittance Email Template Manager.

Supports dynamic placeholder substitution and tabular sub-invoice breakdown
for corporate vendor remittance notifications (HTML & Plain Text).
"""
from decimal import Decimal
from typing import Any, Optional

DEFAULT_SUBJECT_TEMPLATE = "Payment Remittance Advice — {{vendor_name}} (${{amount}})"

DEFAULT_BODY_TEMPLATE = (
    "Dear {{vendor_name}},\n\n"
    "We would like to inform you that we have processed the following payment and applied the invoices accordingly.\n\n"
    "Payment Amount: ${{amount}}\n"
    "Effective Date: {{effective_date}}\n\n"
    "Invoices applied:"
)

AVAILABLE_PLACEHOLDERS = [
    {"name": "{{vendor_name}}", "description": "Vendor or Payee Name"},
    {"name": "{{amount}}", "description": "Formatted payment dollar amount (e.g. 53,413.06)"},
    {"name": "{{effective_date}}", "description": "ACH Effective Entry Date (e.g. 05-19-2026)"},
    {"name": "{{invoice_ref}}", "description": "Primary invoice reference or ID"},
    {"name": "{{company_name}}", "description": "Originating Company Name (e.g. AMIPI INC)"},
    {"name": "{{payment_method}}", "description": "Payment Method (e.g. ACH/Wire or ACH Credit)"},
    {"name": "{{deposit_ref}}", "description": "Deposit or Trace Reference Number"},
]

# Active template settings in memory
ACTIVE_TEMPLATE = {
    "subject": DEFAULT_SUBJECT_TEMPLATE,
    "body": DEFAULT_BODY_TEMPLATE,
    "company_name": "AMIPI INC",
}


def build_invoice_table_html(
    invoice_items: Optional[list[dict[str, Any]]],
    total_amount: str,
    payment_method: str = "ACH/Wire",
    effective_date: str = "",
    default_ref: str = "N/A",
    deposit_ref: str = "12970",
    deposit_source: str = "Sunrise",
) -> str:
    """
    Generate the bottom tabular section of the remittance email in clean,
    Outlook-compatible inline-styled HTML.
    """
    # Normalize invoice items
    items = []
    if invoice_items and len(invoice_items) > 0:
        for itm in invoice_items:
            inv_num = str(itm.get("invoice_number") or itm.get("invoice_ref") or default_ref)
            inv_dt = str(itm.get("invoice_date") or effective_date or "—")
            try:
                amt_val = float(itm.get("amount", 0))
                amt_str = f"${amt_val:,.2f}"
            except (ValueError, TypeError):
                amt_str = f"${itm.get('amount', '0.00')}"
            items.append({
                "method": str(itm.get("method") or payment_method),
                "date": inv_dt,
                "number": inv_num,
                "amount": amt_str,
            })
    else:
        items.append({
            "method": payment_method,
            "date": effective_date or "—",
            "number": default_ref,
            "amount": f"${total_amount}" if not str(total_amount).startswith("$") else str(total_amount),
        })

    record_count = len(items)
    records_label = f"{record_count} Payment Transaction record{'s' if record_count != 1 else ''}"

    rows_html = ""
    for idx, itm in enumerate(items):
        bg = "#ffffff" if idx % 2 == 0 else "#f8fafc"
        rows_html += f"""
        <tr style="background-color: {bg};">
          <td style="padding: 7px 10px; border: 1px solid #cbd5e1; color: #334155; font-size: 12px;">{itm['method']}</td>
          <td style="padding: 7px 10px; border: 1px solid #cbd5e1; color: #334155; font-size: 12px;">{itm['date']}</td>
          <td style="padding: 7px 10px; border: 1px solid #cbd5e1; color: #1d4ed8; font-weight: 600; font-size: 12px;">{itm['number']}</td>
          <td style="padding: 7px 10px; border: 1px solid #cbd5e1; text-align: right; font-family: 'Courier New', Courier, monospace; color: #0f172a; font-size: 12px;">{itm['amount']}</td>
        </tr>
        """

    tot_amt = f"${total_amount}" if not str(total_amount).startswith("$") else str(total_amount)

    table_html = f"""
    <div style="margin-top: 14px; margin-bottom: 20px;">
      <table style="width: 100%; max-width: 680px; border-collapse: collapse; font-family: Arial, Helvetica, sans-serif; font-size: 12px; border: 1px solid #94a3b8;">
        <thead>
          <tr style="background-color: #8bbcdb; color: #0f172a;">
            <th colspan="4" style="text-align: right; padding: 6px 12px; font-weight: 600; font-size: 12px; border-bottom: 1px solid #64748b; letter-spacing: 0.2px;">
              {records_label}
            </th>
          </tr>
          <tr style="background-color: #e2e8f0; color: #1e293b; text-align: left; font-size: 12px;">
            <th style="padding: 8px 10px; border: 1px solid #cbd5e1; width: 25%; font-weight: 600;">Method of Payment</th>
            <th style="padding: 8px 10px; border: 1px solid #cbd5e1; width: 25%; font-weight: 600;">Invoice Date</th>
            <th style="padding: 8px 10px; border: 1px solid #cbd5e1; width: 25%; font-weight: 600;">Invoice #</th>
            <th style="padding: 8px 10px; border: 1px solid #cbd5e1; width: 25%; text-align: right; font-weight: 600;">Amount</th>
          </tr>
        </thead>
        <tbody>
          {rows_html}
        </tbody>
        <tfoot>
          <tr style="background-color: #f1f5f9; font-weight: bold; border-top: 2px solid #64748b;">
            <td colspan="3" style="padding: 8px 10px; border: 1px solid #cbd5e1; font-weight: 700; color: #0f172a;">TOT</td>
            <td style="padding: 8px 10px; border: 1px solid #cbd5e1; text-align: right; font-family: 'Courier New', Courier, monospace; color: #0f172a; font-size: 13px; font-weight: 700;">{tot_amt}</td>
          </tr>
        </tfoot>
      </table>
    </div>
    """
    return table_html


def build_invoice_table_text(
    invoice_items: Optional[list[dict[str, Any]]],
    total_amount: str,
    payment_method: str = "ACH/Wire",
    effective_date: str = "",
    default_ref: str = "N/A",
    deposit_ref: str = "12970",
    deposit_source: str = "Sunrise",
) -> str:
    """Generate plaintext ASCII table for email fallback."""
    items = []
    if invoice_items and len(invoice_items) > 0:
        for itm in invoice_items:
            inv_num = str(itm.get("invoice_number") or itm.get("invoice_ref") or default_ref)
            inv_dt = str(itm.get("invoice_date") or effective_date or "—")
            try:
                amt_val = float(itm.get("amount", 0))
                amt_str = f"${amt_val:,.2f}"
            except (ValueError, TypeError):
                amt_str = f"${itm.get('amount', '0.00')}"
            items.append((str(itm.get("method") or payment_method), inv_dt, inv_num, amt_str))
    else:
        amt_str = f"${total_amount}" if not str(total_amount).startswith("$") else str(total_amount)
        items.append((payment_method, effective_date or "—", default_ref, amt_str))

    tot_amt = f"${total_amount}" if not str(total_amount).startswith("$") else str(total_amount)

    lines = [
        "-" * 68,
        f"{'Method of Payment':<18} {'Invoice Date':<14} {'Invoice #':<16} {'Amount':>16}",
        "-" * 68,
    ]
    for m, d, n, a in items:
        lines.append(f"{m:<18} {d:<14} {n:<16} {a:>16}")
    lines.append("-" * 68)
    lines.append(f"{'TOT':<48} {tot_amt:>16}")
    lines.append("-" * 68)

    return "\n".join(lines)


def render_email_template(
    subject_tmpl: str,
    body_tmpl: str,
    context: dict[str, Any],
    invoice_items: Optional[list[dict[str, Any]]] = None,
) -> tuple[str, str, str]:
    """
    Render subject, plaintext body, and full HTML body with tabular invoice breakdown.

    Returns:
      (rendered_subject, rendered_body_text, rendered_body_html)
    """
    rendered_subject = subject_tmpl or DEFAULT_SUBJECT_TEMPLATE
    body_content = body_tmpl or DEFAULT_BODY_TEMPLATE

    # Substitute dynamic placeholders in subject and body text
    for key, val in context.items():
        placeholder = f"{{{{{key}}}}}"
        val_str = str(val) if val is not None else ""
        rendered_subject = rendered_subject.replace(placeholder, val_str)
        body_content = body_content.replace(placeholder, val_str)

    amt_str = str(context.get("amount", "0.00"))
    eff_date = str(context.get("effective_date", ""))
    inv_ref = str(context.get("invoice_ref", "N/A"))
    company = str(context.get("company_name", "AMIPI INC"))
    pay_method = str(context.get("payment_method", "ACH/Wire"))
    dep_ref = str(context.get("deposit_ref", "12970"))
    dep_source = str(context.get("deposit_source", "Sunrise"))

    # Build tabular sections
    table_html = build_invoice_table_html(
        invoice_items=invoice_items,
        total_amount=amt_str,
        payment_method=pay_method,
        effective_date=eff_date,
        default_ref=inv_ref,
        deposit_ref=dep_ref,
        deposit_source=dep_source,
    )

    table_text = build_invoice_table_text(
        invoice_items=invoice_items,
        total_amount=amt_str,
        payment_method=pay_method,
        effective_date=eff_date,
        default_ref=inv_ref,
        deposit_ref=dep_ref,
        deposit_source=dep_source,
    )

    # Convert body text linebreaks to HTML paragraphs/breaks
    paragraphs = body_content.split("\n\n")
    html_paragraphs = "".join(f"<p style=\"margin: 0 0 12px 0; font-size: 14px; line-height: 1.5; color: #1e293b;\">{p.replace(chr(10), '<br/>')}</p>" for p in paragraphs if p.strip())

    full_html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{rendered_subject}</title>
</head>
<body style="margin: 0; padding: 24px; font-family: Arial, Helvetica, sans-serif; background-color: #f8fafc; color: #1e293b;">
  <div style="max-width: 720px; margin: 0 auto; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 32px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
    <div style="border-bottom: 2px solid #2563eb; padding-bottom: 12px; margin-bottom: 20px;">
      <table style="width: 100%; border-collapse: collapse;">
        <tr>
          <td style="font-size: 18px; font-weight: 700; color: #0f172a; font-family: Arial, Helvetica, sans-serif;">{company}</td>
          <td style="text-align: right; font-size: 12px; font-weight: 600; color: #2563eb; text-transform: uppercase; letter-spacing: 0.5px; font-family: Arial, Helvetica, sans-serif;">Payment Remittance Advice</td>
        </tr>
      </table>
    </div>
    {html_paragraphs}
    {table_html}
    <div style="margin-top: 24px; padding-top: 16px; border-top: 1px solid #e2e8f0;">
      <p style="margin: 0 0 4px 0; font-size: 13px; color: #64748b; line-height: 1.4;">If you have any questions regarding this payment remittance, please contact Accounts Payable.</p>
      <p style="margin: 0; font-size: 13px; color: #1e293b; font-weight: 600;">{company} Accounts Payable</p>
    </div>
  </div>
</body>
</html>"""

    full_text = f"{body_content}\n\n{table_text}\n\nIf you have any questions regarding this payment remittance, please contact Accounts Payable.\n\n{company} Accounts Payable"

    return rendered_subject, full_text, full_html
