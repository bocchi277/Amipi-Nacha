"""
Database URL preflight for the operational scripts.

`app.db.session` builds its engines at import time, so an unusable DATABASE_URL surfaces
as a SQLAlchemy stack trace from inside an import rather than as an actionable message.
Call `require_database_url()` BEFORE importing anything from `app`.

Never prints the password.
"""
from __future__ import annotations

import os
import re
import sys

PLACEHOLDER_HINTS = ("<", ">", "your-", "YOUR-", "paste", "PASTE", "example.com")


def _redact(url: str) -> str:
    """Replace the password with ***, keeping the rest of the shape visible."""
    return re.sub(r"(://[^:/@]+:)[^@]*(@)", r"\1***\2", url)


def describe(url: str) -> str:
    if not url:
        return "(empty)"
    shown = _redact(url)
    if len(shown) > 120:
        shown = shown[:117] + "..."
    return shown


def require_database_url() -> str:
    """
    Validate DATABASE_URL and return it, or exit with an explanation.

    Returns the raw value; scheme normalisation to asyncpg/psycopg2 is handled by
    app.config, which already converts postgres:// and postgresql:// and rewrites
    sslmode for asyncpg.
    """
    raw = os.getenv("DATABASE_URL", "")

    def fail(problem: str, fix: str) -> None:
        print("=" * 70)
        print(" DATABASE_URL IS NOT USABBLE".replace("USABBLE", "USABLE"))
        print("=" * 70)
        print(f" Problem : {problem}")
        print(f" Value   : {describe(raw)}")
        print(f" Length  : {len(raw)} characters")
        print()
        print(f" Fix     : {fix}")
        print()
        print(" Render dashboard -> your Postgres instance -> Connect ->")
        print(" 'External Database URL'. Copy it whole, then:")
        print()
        print('   export DATABASE_URL="<paste>"')
        print()
        print(" Quote it: connection strings often contain characters the shell would")
        print(" otherwise interpret. Do NOT include the angle brackets.")
        print("=" * 70)
        sys.exit(2)

    if not raw:
        fail("the variable is not set, or is empty",
             "export DATABASE_URL with the External Database URL from Render.")

    if any(h in raw for h in PLACEHOLDER_HINTS):
        fail("it still contains placeholder text rather than a real connection string",
             "Replace the whole value, including removing any < > brackets.")

    if "\n" in raw or "\r" in raw:
        fail("it contains a line break, so only part of it was captured",
             "Re-copy the URL as a single line and quote it.")

    if "://" not in raw:
        fail("there is no '://', so this is not a connection URL",
             "It must look like postgresql://USER:PASSWORD@HOST:5432/DBNAME")

    scheme, _, remainder = raw.partition("://")
    if not scheme or not remainder:
        fail("the scheme or the body of the URL is missing",
             "It must look like postgresql://USER:PASSWORD@HOST:5432/DBNAME")

    if not scheme.startswith(("postgres", "postgresql")):
        fail(f"the scheme is {scheme!r}, which is not PostgreSQL",
             "Use the PostgreSQL connection string from Render.")

    if "@" not in remainder:
        fail("there is no '@', so no host was given",
             "It must look like postgresql://USER:PASSWORD@HOST:5432/DBNAME")

    hostpart = remainder.rpartition("@")[2]
    if "/" not in hostpart:
        fail("no database name follows the host",
             "Append the database name: .../DBNAME")

    return raw


def report(url: str) -> None:
    scheme = url.partition("://")[0]
    host = url.rpartition("@")[2]
    print(f"  connection : {scheme}://***@{host.split('?')[0]}")
