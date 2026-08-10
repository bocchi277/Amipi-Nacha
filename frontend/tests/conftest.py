"""
Playwright Test Configuration for AMIPI Frontend Tests.

Starts the FastAPI backend server on a test port before running browser tests,
and tears it down after.
"""
import asyncio
import os
import subprocess
import time

import pytest


@pytest.fixture(scope="session")
def backend_server():
    """
    Launch the FastAPI backend on port 8099 for browser testing.
    The backend serves the frontend static files at root.
    """
    env = os.environ.copy()
    env["DATABASE_URL"] = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://amipi:amipipass@localhost:5432/amipi_ach"
    )

    proc = subprocess.Popen(
        [
            "python3", "-m", "uvicorn",
            "app.main:app",
            "--host", "127.0.0.1",
            "--port", "8099",
            "--log-level", "warning",
        ],
        cwd=os.path.join(os.path.dirname(__file__), "..", "..", "backend"),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for server to be ready
    import urllib.request
    for _ in range(30):
        try:
            urllib.request.urlopen("http://127.0.0.1:8099/health", timeout=1)
            break
        except Exception:
            time.sleep(0.5)
    else:
        proc.kill()
        raise RuntimeError("Backend server failed to start on port 8099")

    yield "http://127.0.0.1:8099"

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="session")
def base_url(backend_server):
    """Provide the base URL for Playwright tests."""
    return backend_server
