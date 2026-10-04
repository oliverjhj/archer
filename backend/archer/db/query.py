"""
The one way generated SQL is executed.

Model output is untrusted, so the guarantees here do not depend on the model,
the prompt or any text inspection of the query. They are enforced by SQLite
itself, on a connection that:

  - is opened read-only, so no write can succeed even if every other check
    were removed;
  - has an authorizer that permits reading the one queryable table and
    nothing else: no other table or view, no SQLite internal tables such as
    sqlite_master, no PRAGMA, no ATTACH and no load_extension;
  - runs one statement only, which Python's sqlite3 enforces by refusing a
    string that contains a second;
  - has a deadline, so a runaway query (a cross join, a recursive CTE with no
    end) is interrupted rather than holding a worker;
  - returns at most max_rows rows, plus a flag saying whether there were more.

The application and the evaluation suite both execute through run_select, so
what the suite measures is what the demo runs.
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass

from .database import TABLE_NAME, database_path

DEFAULT_MAX_ROWS = 100
DEFAULT_TIMEOUT_SECONDS = 5.0

# Checked every this many SQLite virtual machine instructions. Small enough to
# stop a runaway query promptly, large enough to cost nothing on a normal one.
_PROGRESS_INTERVAL = 10_000

_ALLOWED_START = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)
_DENIED_FUNCTIONS = {"load_extension"}


class QueryBlocked(sqlite3.DatabaseError):
    """The query tried to do something other than read the queryable table."""


class QueryTimeout(sqlite3.OperationalError):
    """The query ran past its deadline and was interrupted."""


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    truncated: bool


def _make_authorizer(other_tables: frozenset[str]):
    """
    Build the authorizer for one connection.

    Reads are refused by name: SQLite's own sqlite_* tables, and every other
    table or view in the file. An allow-list of TABLE_NAME alone would also
    refuse common table expressions, which SQLite reports as reads under names
    the model chooses.
    """

    def _authorizer(action, arg1, arg2, _db_name, _source):
        if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE):
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            name = (arg1 or "").lower()
            if name.startswith("sqlite_") or name in other_tables:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION:
            return sqlite3.SQLITE_DENY if (arg2 or "").lower() in _DENIED_FUNCTIONS else sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    return _authorizer


def _other_tables(conn: sqlite3.Connection) -> frozenset[str]:
    """Every table and view in the file except the queryable one, lower-cased."""
    names = conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")
    return frozenset(row[0].lower() for row in names) - {TABLE_NAME.lower()}


def run_select(
    sql: str,
    *,
    max_rows: int = DEFAULT_MAX_ROWS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    db_path: str | None = None,
) -> QueryResult:
    """
    Execute one read-only SELECT (or WITH ... SELECT) against the queryable table.

    Raises QueryBlocked when the query is refused, QueryTimeout when it runs
    past the deadline, and sqlite3.Error for anything else SQLite rejects,
    such as a misspelt column. All three are sqlite3.Error subclasses, so a
    caller that only needs to know the query failed can catch that alone.
    """
    if not _ALLOWED_START.match(sql or ""):
        raise QueryBlocked("Only SELECT queries can be run.")

    conn = sqlite3.connect(f"file:{db_path or database_path()}?mode=ro", uri=True)
    try:
        # Listed before the authorizer is installed, which refuses sqlite_master.
        conn.set_authorizer(_make_authorizer(_other_tables(conn)))

        deadline = time.monotonic() + timeout_seconds
        timed_out = False

        def _check_deadline() -> int:
            nonlocal timed_out
            if time.monotonic() > deadline:
                timed_out = True
                return 1  # non-zero interrupts the query
            return 0

        conn.set_progress_handler(_check_deadline, _PROGRESS_INTERVAL)

        try:
            cursor = conn.execute(sql)
            rows = cursor.fetchmany(max_rows + 1)
        except sqlite3.DatabaseError as exc:
            if timed_out:
                raise QueryTimeout(f"The query took longer than {timeout_seconds:g}s.") from exc
            message = str(exc).lower()
            if "not authorized" in message or "prohibited" in message:
                raise QueryBlocked(f"The query was refused: it may only read {TABLE_NAME}.") from exc
            raise

        columns = [description[0] for description in cursor.description or []]
        return QueryResult(columns=columns, rows=rows[:max_rows], truncated=len(rows) > max_rows)
    finally:
        conn.close()
