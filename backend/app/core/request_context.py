"""
Per-request context.

Carries the caller's IP address from the HTTP middleware down to audit logging without
threading a ``Request`` object through every service function.

`AuditLog.ip_address` existed as a column and the README advertised IP tracking, but
no application code ever populated it, so the audit trail could not answer "where did
this change come from?" -- the key question after a suspicious bank-detail change.
"""
from contextvars import ContextVar
from typing import Optional

_client_ip: ContextVar[Optional[str]] = ContextVar("client_ip", default=None)


def set_client_ip(value: Optional[str]) -> None:
    _client_ip.set(value)


def get_client_ip() -> Optional[str]:
    return _client_ip.get()


def resolve_client_ip(request) -> Optional[str]:
    """
    Best-effort client IP.

    Honours X-Forwarded-For because the app runs behind Render/Netlify proxies, where
    ``request.client.host`` is the proxy rather than the caller. Truncated to the
    column width (45 chars, IPv6-safe).
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    real = request.headers.get("x-real-ip", "")
    if real:
        return real.strip()[:45]
    if getattr(request, "client", None):
        return (request.client.host or "")[:45] or None
    return None
