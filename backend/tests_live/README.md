# Live verification suite

These tests run a REAL browser against a RUNNING deployment and are excluded from
the default `pytest` run, because:

* they need a live server (they skip when one is not reachable);
* `test_live_browser_e2e.py` targets the PRODUCTION Netlify/Render deployment, so it
  must never run unattended in CI.

They live outside `tests/` so they do not inherit that package's async
database fixtures.

Local run:

    # terminal 1
    export DATABASE_URL=postgresql+asyncpg://amipi:amipipass@127.0.0.1:5433/amipi_ach_uitest
    export SECRET_KEY=...          # any value locally
    alembic upgrade head
    uvicorn app.main:app --host 127.0.0.1 --port 8099

    # terminal 2
    pytest tests_live/test_live_ui_verification.py -v
