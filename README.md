# 🏦 AMIPI NACHA ACH Payment System

An enterprise-grade B2B payment generation, validation, and security management system built with **FastAPI**, **PostgreSQL**, and a modern **Vanilla JavaScript & CSS Design Token** interface. Produces Chase-compliant NACHA fixed-width (94-character) files for banking transfers.

---

## 🌟 Key Features

- **NACHA 94-Character Line Generator**:
  - Builds NACHA files compliant with the Chase CCD credit spec: File Header (`1`), Batch Header (`5`), Entry Detail (`6`), Batch Control (`8`), File Control (`9`), and `9`-padded blocking lines to 10-record multiples.
  - Supports single-batch and multi-batch payment aggregation.
  - Record layout is verified byte-for-byte against AMIPI's real Chase transmit files.
  - *Not currently supported:* Addenda (`7`) records. All entries are written with addenda indicator `0`, matching every production transmit file to date. CTX/addenda payloads would require generator changes.
- **Spreadsheet Ingestion**:
  - Parses Excel (`.xlsx`) and CSV payment files, plus grouped QuickBooks report exports, with per-row validation (ABA routing check digit, SEC code whitelisting, account type validation).
  - Vendor names resolve by exact match → curated alias map → punctuation-insensitive match → scored word overlap. Genuinely ambiguous names are reported as row errors rather than guessed, because guessing means paying the wrong bank account.
  - Multiple invoices per vendor are merged into one entry and compressed into the 15-character NACHA ID field (`UDI261954/65/55`) without losing invoice identity.
- **Duplicate Transaction Defense**:
  - Deterministic SHA-256 fingerprint hashing flags duplicate payments across historical batches with explicit manual override.
  - Batches already written into a generated file cannot be reused, and payments in a generated file are immutable.
- **Dual-Control Maker-Checker Workflow**:
  - Standard users submit vendor bank detail change requests.
  - Administrators review, approve, or reject requests with automatic vendor record updates and audit logging.
- **Immutable Audit Logging**:
  - Tracks user actions, old vs. new values, timestamps, and originating IP addresses (honouring `X-Forwarded-For` behind the Render proxy) in PostgreSQL.
  - Append-only is enforced by a PostgreSQL trigger (`trg_audit_logs_immutable`): `UPDATE` and `DELETE` on `audit_logs` are rejected. The single exception is nullifying `user_id` when a user account is deleted, which preserves the audit row.
  - Full bank account numbers are never copied into audit details (last 4 only).
- **Security**:
  - Authentication required on every endpoint that moves money or exposes bank details.
  - Roles are server-assigned; self-registration cannot grant administrator access.
  - Login throttling, CORS allowlist, CSP and related response headers, and HTML escaping on all rendered database values.
- **Automated Testing Suite**:
  - **169 Pytest backend test cases** covering DB schema, security/pentests (SQLi, XSS, path traversal, JWT tampering, Unicode homograph spoofing), NACHA generation parity, and business logic.
  - **41 Playwright E2E test cases** in `frontend/tests/` validating user journeys, admin approvals, and file downloads.
  - **5 live browser verification tests** in `backend/tests_live/` (opt-in; excluded from the default run).

---

## 🏗 System Architecture

```
FirstProject/
├── backend/                  # FastAPI Python Application
│   ├── alembic/              # Database migration scripts
│   ├── app/
│   │   ├── api/v1/           # REST endpoints (auth, nacha, payments, vendors, remittances)
│   │   ├── core/             # Security, JWT, encryption, request context
│   │   ├── db/               # Async Engine & Session management
│   │   ├── models/           # SQLAlchemy ORM models (User, Vendor, Payment, NachaFile, AuditLog)
│   │   └── services/         # NACHA generation, spreadsheet parsing, email remittance
│   ├── tests/                # 169 hermetic Pytest cases (run by default)
│   ├── tests_live/           # Opt-in browser tests against a running server
│   ├── alembic.ini
│   ├── pytest.ini
│   └── .env.example
├── frontend/                 # Web Dashboard
│   ├── css/                  # CSS tokens & base layout
│   ├── js/                   # Dashboard API client, controllers, admin workflows
│   ├── tests/                # 41 Playwright E2E browser tests
│   ├── index.html            # Main SPA Dashboard
│   └── DESIGN_SYSTEM.md      # UI Tokens & styling reference
├── Chase Requirement/        # Bank reference specifications & sample CSV template
├── ACH Thru Soft/            # Real transmit file samples (vendor data ground truth)
└── README.md
```

---

## 🚀 Quick Start Guide

### Prerequisites
- **Python 3.12+**
- **Docker** (for PostgreSQL database)

### 1. Database Setup (Docker PostgreSQL)
```bash
docker run -d \
  --name amipi_postgres \
  -e POSTGRES_USER=amipi \
  -e POSTGRES_PASSWORD=amipipass \
  -e POSTGRES_DB=amipi_ach \
  -p 5432:5432 \
  postgres:16-alpine
```

### 2. Backend Setup
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Configure environment (see `.env.example`):

```bash
export DATABASE_URL="postgresql+asyncpg://amipi:amipipass@localhost:5432/amipi_ach"
export SYNC_DATABASE_URL="postgresql+psycopg2://amipi:amipipass@localhost:5432/amipi_ach"
export SECRET_KEY="<a long random value>"
export BANK_DETAILS_ENCRYPTION_KEY="<a long random value>"
```

> **Both secrets have insecure built-in defaults and the app warns loudly at startup if they are unset.**
> `SECRET_KEY` signs JWTs — leaving it at the default allows token forgery.
> `BANK_DETAILS_ENCRYPTION_KEY` encrypts vendor routing/account numbers at rest. **Changing it makes existing encrypted rows unreadable**, so set it before entering data and rotate only via a re-encryption migration.

Run migrations and start the server:
```bash
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8099 --reload
```
API documentation: `http://127.0.0.1:8099/api/v1/docs`

The frontend is served by the same process at `http://127.0.0.1:8099`.

### 3. Create the first administrator
Self-registration always creates a standard user, so provision the first admin directly:
```bash
python scripts/create_user.py        # follow the prompts
```

### 4. Frontend (standalone, optional)
```bash
cd frontend
python3 -m http.server 8000
```
When served separately, add its origin to `ALLOWED_ORIGINS`.

---

## 🧪 Running Automated Tests

### Backend (169 tests)
```bash
cd backend
export DATABASE_URL="postgresql+asyncpg://amipi:amipipass@localhost:5432/amipi_ach_test"
export SYNC_DATABASE_URL="postgresql+psycopg2://amipi:amipipass@localhost:5432/amipi_ach_test"
export SECRET_KEY="test-secret"
alembic upgrade head
pytest
```

> The suite `TRUNCATE`s every table, so it **refuses to run** unless the database name contains `test`, `_ci`, or `scratch`. This guard exists because it would otherwise wipe whatever `DATABASE_URL` points at.

### Frontend E2E (41 Playwright tests)
```bash
cd frontend
pytest
```

### Live browser verification (opt-in)
Requires a running server; excluded from the default run because `test_live_browser_e2e.py` targets the **production** deployment.
```bash
cd backend
pytest tests_live/test_live_ui_verification.py -v
```

---

## 🔒 Security Notes

- **OAuth2 + JWT authentication** with role-based access control (`user` vs `admin`). Roles are assigned server-side only.
- **Encrypted bank data at rest** via Fernet. Because Fernet is non-deterministic, bank-detail lookups compare decrypted values in memory rather than in SQL.
- **Login throttling**: 8 failed attempts per (IP, username) per 5 minutes, then HTTP 429. In-process — move to a shared store if running multiple workers.
- **Injection defenses**: parameterised queries via SQLAlchemy, HTML escaping on all rendered database values, CSV formula escaping.
- **Response headers**: CSP, `X-Frame-Options: DENY`, `X-Content-Type-Options`, `Referrer-Policy`, and HSTS over HTTPS.
- **CORS**: explicit allowlist, configurable via `ALLOWED_ORIGINS`.

### Known limitations
- Vendor list responses return full decrypted bank details to any authenticated user; per-role masking is not yet implemented.
- Remittance email delivery is **not wired to SMTP** — `send_single_remittance` marks records as sent without dispatching mail. Vendors without an email address are skipped and recorded in the audit log rather than being sent to a fabricated address.
- NACHA effective dates are not validated against a banking-holiday calendar, and the trace sequence is derived by parsing the previous file rather than from a database sequence (concurrent generation could collide).
- `SAMPLE_VENDORS` is reference data derived from historical transmit files. Two payees (`KIRA JEWELS INC`, `TWINKLEDIAM INC.`) are deliberately excluded because their bank details could not be verified. **Always confirm against AMIPI's bank records before generating a live payment file.**

---

## 📄 License
Internal Proprietary Enterprise System — AMIPI INC.
