# 🏦 AMIPI NACHA ACH Payment System

An enterprise-grade B2B payment generation, validation, and security management system built with **FastAPI**, **PostgreSQL**, and a modern **Vanilla JavaScript & CSS Design Token** interface. Fully compliant with NACHA fixed-width line standards for banking transfers.

---

## 🌟 Key Features

- **NACHA 94-Character Line Generator**:
  - Automatically builds NACHA files compliant with banking specs: File Header (`1`), Batch Header (`5`), Entry Detail (`6`), Addenda (`7`), Batch Control (`8`), File Control (`9`), and `9`-padded blocking lines to 10-record multiples.
  - Supports single-batch and multi-batch payment aggregation.
- **Spreadsheet Ingestion**:
  - Parses Excel (`.xlsx`) and CSV payment files with per-row validation (routing number checksums, SEC code whitelisting, account type validation).
- **Duplicate Transaction Defense**:
  - Deterministic SHA-256 fingerprint hashing flags duplicate payments across historical batches with manual override options.
- **Dual-Control Maker-Checker Workflow**:
  - Standard users submit vendor bank detail change requests.
  - Administrators review, approve, or reject requests with automatic vendor record updates and audit logging.
- **Immutable Audit Logging**:
  - Tracks user actions, old vs. new values, timestamps, and IP addresses in PostgreSQL.
- **Automated Testing Suite**:
  - **117 Pytest backend test cases** covering DB schemas, security/pentests (SQLi, XSS, Path Traversal, JWT tampering), and business logic.
  - **25 Playwright E2E test cases** validating user journeys, admin approvals, and file downloads.

---

## 🏗 System Architecture

```
FirstProject/
├── backend/                  # FastAPI Python Application
│   ├── alembic/              # Database migration scripts
│   ├── app/
│   │   ├── api/v1/           # REST endpoints (auth, nacha, payments, vendors, remittances)
│   │   ├── core/             # Security & JWT logic
│   │   ├── db/               # Async Engine & Session management
│   │   ├── models/           # SQLAlchemy ORM models (User, Vendor, Payment, NachaFile, AuditLog)
│   │   └── services/         # NACHA generation & email remittance services
│   ├── tests/                # 117 Pytest backend test cases
│   ├── alembic.ini
│   └── .env.example
├── frontend/                 # Web Dashboard
│   ├── css/                  # CSS tokens & base layout
│   ├── js/                   # Dashboard API client, controllers, and admin approval workflows
│   ├── tests/                # 25 Playwright E2E browser tests
│   ├── index.html            # Main SPA Dashboard
│   └── DESIGN_SYSTEM.md      # UI Tokens & styling reference
├── Chase Requirement/        # Bank reference specifications & sample CSV template
├── ACH Thru Soft/            # Transmit file samples
└── README.md
```

---

## 🚀 Quick Start Guide

### Prerequisites
- **Python 3.12+**
- **Docker** (for PostgreSQL database)

### 1. Database Setup (Docker PostgreSQL)
Start the PostgreSQL container:
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
Navigate to `backend` and install dependencies:
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt # or install fastapi uvicorn sqlalchemy asyncpg alembic pytest pytest-asyncio
```

Run database migrations:
```bash
alembic upgrade head
```

Start the FastAPI server:
```bash
uvicorn app.main:app --host 127.0.0.1 --port 8099 --reload
```
API Documentation will be available at `http://127.0.0.1:8099/docs`.

### 3. Frontend Setup
Open `frontend/index.html` in your web browser or serve it using any HTTP server:
```bash
cd frontend
python3 -m http.server 8000
```
Open `http://localhost:8000` in your browser.

---

## 🧪 Running Automated Tests

### Run Backend Tests (117 Tests)
```bash
cd backend
PYTHONPATH=. pytest
```

### Run Frontend E2E Tests (25 Playwright Tests)
```bash
cd frontend
pytest
```

---

## 🔒 Security Hardening

- **OAuth2 + JWT Authentication**: Role-based access control (`user` vs `admin`).
- **Encrypted Sensitive Data**: Bank account and routing numbers sanitized and masked.
- **Injection Defenses**: Prepared statements via SQLAlchemy, XSS stripping, CSV formula escaping.
- **Immutability**: Audit logs append-only via DB triggers/ORM restrictions.

---

## 📄 License
Internal Proprietary Enterprise System — AMIPI INC.
