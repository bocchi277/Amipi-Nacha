"""
Remittance Email Template Manager.

Supports dynamic placeholder substitution for vendor remittance notifications.
Placeholders:
  {{vendor_name}}
  {{amount}}
  {{invoice_ref}}
  {{effective_date}}
  {{company_name}}
"""
from typing import Any

DEFAULT_SUBJECT_TEMPLATE = "Payment Remittance Advice — {{vendor_name}} (${{amount}})"

DEFAULT_BODY_TEMPLATE = (
    "Dear {{vendor_name}},\n\n"
    "Please be advised that an ACH payment of ${{amount}} has been scheduled for effective date {{effective_date}}.\n\n"
    "Payment Details:\n"
    "• Payee / Vendor Name: {{vendor_name}}\n"
    "• Payment Amount ($):  ${{amount}}\n"
    "• Invoice Reference:   {{invoice_ref}}\n"
    "• Effective Date:      {{effective_date}}\n\n"
    "If you have any questions regarding this remittance, please contact Accounts Payable.\n\n"
    "Thank you,\n"
    "{{company_name}} Accounts Payable"
)

# Active template settings in memory
ACTIVE_TEMPLATE = {
    "subject": DEFAULT_SUBJECT_TEMPLATE,
    "body": DEFAULT_BODY_TEMPLATE,
}

AVAILABLE_PLACEHOLDERS = [
    {"name": "{{vendor_name}}", "description": "Vendor or Payee Name"},
    {"name": "{{amount}}", "description": "Formatted payment dollar amount (e.g. 700.75)"},
    {"name": "{{invoice_ref}}", "description": "Invoice reference number or ID"},
    {"name": "{{effective_date}}", "description": "ACH Effective Entry Date"},
    {"name": "{{company_name}}", "description": "Originating Company Name (e.g. AMIPI INC)"},
]


def render_email_template(subject_tmpl: str, body_tmpl: str, context: dict[str, Any]) -> tuple[str, str]:
    """Render subject and body by replacing {{key}} placeholders with context values."""
    rendered_subject = subject_tmpl or DEFAULT_SUBJECT_TEMPLATE
    rendered_body = body_tmpl or DEFAULT_BODY_TEMPLATE

    for key, val in context.items():
        placeholder = f"{{{{{key}}}}}"
        val_str = str(val) if val is not None else ""
        rendered_subject = rendered_subject.replace(placeholder, val_str)
        rendered_body = rendered_body.replace(placeholder, val_str)

    return rendered_subject, rendered_body
