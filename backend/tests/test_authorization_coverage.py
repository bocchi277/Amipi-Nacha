"""
Authorization coverage, enforced by enumeration rather than by example.

`GET /vendors` was masked and `GET /vendors/{id}` was left completely unauthenticated,
returning every vendor's full decrypted routing and account number. That gap survived a
security pass because the pass tested the endpoints someone thought of, one at a time.

These tests instead walk every registered route, so a new endpoint has to be explicitly
classified. Adding one without authentication fails the suite.
"""
import inspect

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1.auth import get_current_user, require_admin
from app.main import app
from tests._helpers import create_admin_user, create_standard_user

# real_auth suppresses the autouse injected admin identity, which is required for
# any test asserting 401/403. asyncio is declared explicitly per pytest.ini.
# real_auth suppresses the autouse injected admin identity, which is required for
# any test asserting 401/403.
pytestmark = pytest.mark.real_auth


# Routes that are legitimately reachable without credentials.
PUBLIC_ALLOWLIST = {
    ("POST", "/api/v1/auth/login"),
    ("GET", "/health"),
    # Returns only {"status": "ok", "api_version": "v1"}. No data.
    ("GET", "/api/v1/status"),
    ("GET", "/"),
    # A blank CSV template with placeholder columns. Contains no customer data.
    ("GET", "/api/v1/vendors/sample-template"),
}

# Documentation and static asset routes are not part of the API surface.
IGNORED_PREFIXES = ("/api/v1/docs", "/api/v1/redoc", "/api/v1/openapi.json", "/static")


def _auth_dependencies(route) -> set[str]:
    """Names of the authentication dependencies a route resolves, at any nesting depth."""
    found: set[str] = set()

    def walk(dependant, depth: int = 0) -> None:
        if depth > 6:
            return
        call = getattr(dependant, "call", None)
        if call in (get_current_user, require_admin):
            found.add(call.__name__)
        for sub in getattr(dependant, "dependencies", []) or []:
            walk(sub, depth + 1)

    dependant = getattr(route, "dependant", None)
    if dependant is not None:
        walk(dependant)
    return found


def _api_routes():
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if any(path.startswith(p) for p in IGNORED_PREFIXES):
            continue
        if not getattr(route, "dependant", None):
            continue
        for method in sorted(methods - {"HEAD", "OPTIONS"}):
            yield method, path, route


def test_every_route_requires_authentication():
    """No endpoint may be reachable anonymously unless explicitly allowlisted."""
    unprotected = [
        f"{method} {path}"
        for method, path, route in _api_routes()
        if not _auth_dependencies(route) and (method, path) not in PUBLIC_ALLOWLIST
    ]
    assert not unprotected, (
        "these routes have no authentication dependency:\n  "
        + "\n  ".join(sorted(unprotected))
        + "\nAdd get_current_user/require_admin, or add to PUBLIC_ALLOWLIST with a reason."
    )


def test_every_state_changing_route_requires_an_administrator():
    """
    Writes to vendors, users and generated files must be administrator-only.

    Standard users act through the change-request workflow. The exceptions are that
    workflow's own submission endpoint and payment ingestion, which standard users
    perform as part of their job.
    """
    standard_user_may_write = {
        ("POST", "/api/v1/vendors/{vendor_id}/change-requests"),
        ("POST", "/api/v1/payments/upload"),
        ("POST", "/api/v1/payments/batches"),
        ("PUT", "/api/v1/payments/{payment_id}"),
        ("POST", "/api/v1/auth/login"),
        ("POST", "/api/v1/auth/logout"),
    }

    offenders = []
    for method, path, route in _api_routes():
        if method not in ("POST", "PUT", "PATCH", "DELETE"):
            continue
        if (method, path) in standard_user_may_write:
            continue
        if "require_admin" not in _auth_dependencies(route):
            offenders.append(f"{method} {path}")

    assert not offenders, (
        "these state-changing routes do not require an administrator:\n  "
        + "\n  ".join(sorted(offenders))
    )


# ---------------------------------------------------------------------------
# The specific leaks, kept as explicit regressions
# ---------------------------------------------------------------------------

def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


async def _token(client, username, password):
    r = await client.post("/api/v1/auth/login", data={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.asyncio
async def test_single_vendor_fetch_is_authenticated_and_masked(db_session):
    """
    Regression: this endpoint had no authentication dependency, so masking the list
    endpoint was pointless. A caller could list IDs as any user and then read every
    vendor's full bank details here, or read one anonymously with a known UUID.
    """
    async with _client() as client:
        from app.models import AccountType, Vendor

        vendor = Vendor(
            name="AUTHZ PROBE INC",
            routing_number="021000021",
            account_number="192837465",
            account_type=AccountType.CHECKING,
        )
        db_session.add(vendor)
        await create_admin_user(db_session, "authz_admin", "authz_admin@example.com", "AuthzAdmin123!")
        await create_standard_user(db_session, "authz_user", "authz_user@example.com", "AuthzUser123!")
        await db_session.commit()
        await db_session.refresh(vendor)
        vid = str(vendor.id)

        anon = await client.get(f"/api/v1/vendors/{vid}")
        assert anon.status_code == 401, f"anonymous read must be refused, got {anon.status_code}"

        user_headers = await _token(client, "authz_user", "AuthzUser123!")
        as_user = (await client.get(f"/api/v1/vendors/{vid}", headers=user_headers)).json()
        assert as_user["bank_details_masked"] is True
        assert "192837465" not in str(as_user["account_number"])
        assert "021000021" not in str(as_user["routing_number"])

        admin_headers = await _token(client, "authz_admin", "AuthzAdmin123!")
        as_admin = (await client.get(f"/api/v1/vendors/{vid}", headers=admin_headers)).json()
        assert as_admin["account_number"] == "192837465"
        assert as_admin["bank_details_masked"] is False


@pytest.mark.asyncio
async def test_vendor_update_does_not_return_unmasked_details_to_standard_users(db_session):
    """
    Regression: PUT was open to any authenticated user AND returned full bank details,
    so a standard user could read any vendor's real account number by submitting a
    no-op email change. It also allowed renaming a vendor, and vendor names are what
    spreadsheet rows match against, so a rename redirects future payments.
    """
    async with _client() as client:
        from app.models import AccountType, Vendor

        vendor = Vendor(
            name="UPDATE PROBE INC",
            routing_number="021000021",
            account_number="556677889",
            account_type=AccountType.CHECKING,
        )
        db_session.add(vendor)
        await create_standard_user(db_session, "upd_user", "upd_user@example.com", "UpdUser123!")
        await db_session.commit()
        await db_session.refresh(vendor)

        headers = await _token(client, "upd_user", "UpdUser123!")
        r = await client.put(
            f"/api/v1/vendors/{vendor.id}", headers=headers, json={"email": "x@example.com"}
        )
        assert r.status_code == 403, f"standard users must not update vendors, got {r.status_code}"
        assert "556677889" not in r.text

        rename = await client.put(
            f"/api/v1/vendors/{vendor.id}", headers=headers, json={"name": "SOMEONE ELSE INC"}
        )
        assert rename.status_code == 403


@pytest.mark.asyncio
async def test_masked_reference_cannot_be_written_back_as_the_nacha_id(db_session):
    """
    The UI prefilled the reference field from `account_number`, which is masked to
    '•••••7465' for standard users, and saved '•7465'. That value would then be written
    into the NACHA identification field.
    """
    async with _client() as client:
        from app.models import AccountType, Vendor

        vendor = Vendor(
            name="REFERENCE PROBE INC",
            routing_number="021000021",
            account_number="192837465",
            account_type=AccountType.CHECKING,
        )
        db_session.add(vendor)
        await create_admin_user(db_session, "ref_admin", "ref_admin@example.com", "RefAdmin123!")
        await db_session.commit()
        await db_session.refresh(vendor)

        headers = await _token(client, "ref_admin", "RefAdmin123!")
        bad = await client.put(
            f"/api/v1/vendors/{vendor.id}", headers=headers, json={"default_id_number": "\u20227465"}
        )
        assert bad.status_code == 422, f"a masked value must be rejected, got {bad.status_code}"

        good = await client.put(
            f"/api/v1/vendors/{vendor.id}", headers=headers, json={"default_id_number": "INV-7788"}
        )
        assert good.status_code == 200
        assert good.json()["default_id_number"] == "INV-7788"


@pytest.mark.asyncio
async def test_masking_never_reveals_more_digits_than_it_promises(db_session):
    """
    `account_number` is masked to the last 4, but `default_id_number` returned the last
    5 of the same account, so the field beside the mask leaked an extra digit.
    """
    async with _client() as client:
        from app.models import AccountType, Vendor

        vendor = Vendor(
            name="DIGIT PROBE INC",
            routing_number="021000021",
            account_number="192837465",
            account_type=AccountType.CHECKING,
            default_id_number="37465",  # the account tail, the house convention
        )
        db_session.add(vendor)
        await create_standard_user(db_session, "digit_user", "digit_user@example.com", "DigitUser123!")
        await db_session.commit()

        headers = await _token(client, "digit_user", "DigitUser123!")
        rows = (await client.get("/api/v1/vendors", headers=headers)).json()
        row = next(r for r in rows if r["name"] == "DIGIT PROBE INC")

        for field in ("account_number", "routing_number", "default_id_number"):
            digits = [c for c in str(row.get(field) or "") if c.isdigit()]
            assert len(digits) <= 4, (
                f"{field}={row.get(field)!r} reveals {len(digits)} digits; masking promises 4"
            )
