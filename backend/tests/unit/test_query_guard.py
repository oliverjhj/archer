"""
Unit tests for archer.db.query.run_select - the only way generated SQL runs.

The guarantees here are enforced by SQLite, not by inspecting the query text,
so each test hands run_select a hostile query directly, as if the model had
produced it and every earlier check had missed it. A small temporary database
stands in for the real one.
"""

import os
import sqlite3
import tempfile

import pytest

from archer.db.query import QueryBlocked, QueryTimeout, run_select


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE sales_data (customer_name TEXT, revenue REAL)")
    conn.executemany(
        "INSERT INTO sales_data VALUES (?, ?)",
        [(f"Partner {i}", float(i)) for i in range(150)],
    )
    conn.commit()
    conn.close()
    yield path
    os.unlink(path)


# ---------------------------------------------------------------------------
# What is allowed
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_select_returns_columns_and_rows(db_path) -> None:
    result = run_select("SELECT customer_name, revenue FROM sales_data LIMIT 2", db_path=db_path)
    assert result.columns == ["customer_name", "revenue"]
    assert result.rows == [("Partner 0", 0.0), ("Partner 1", 1.0)]
    assert result.truncated is False


@pytest.mark.unit
def test_with_statement_is_allowed(db_path) -> None:
    result = run_select(
        "WITH t AS (SELECT revenue FROM sales_data) SELECT COUNT(*) FROM t", db_path=db_path
    )
    assert result.rows == [(150,)]


@pytest.mark.unit
def test_bounded_recursive_cte_is_allowed(db_path) -> None:
    result = run_select(
        "WITH RECURSIVE m(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM m WHERE n < 12) "
        "SELECT COUNT(*) FROM m",
        db_path=db_path,
    )
    assert result.rows == [(12,)]


@pytest.mark.unit
def test_row_cap_truncates_and_says_so(db_path) -> None:
    result = run_select("SELECT customer_name FROM sales_data", max_rows=100, db_path=db_path)
    assert len(result.rows) == 100
    assert result.truncated is True


@pytest.mark.unit
def test_exactly_max_rows_is_not_truncated(db_path) -> None:
    result = run_select("SELECT customer_name FROM sales_data LIMIT 100", max_rows=100, db_path=db_path)
    assert len(result.rows) == 100
    assert result.truncated is False


# ---------------------------------------------------------------------------
# What is refused
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE sales_data",
        "INSERT INTO sales_data VALUES ('x', 1)",
        "UPDATE sales_data SET revenue = 0",
        "DELETE FROM sales_data",
        "ATTACH DATABASE 'evil.db' AS evil",
        "PRAGMA table_info(sales_data)",
        "",
    ],
)
def test_statements_other_than_select_are_refused(db_path, sql) -> None:
    with pytest.raises(QueryBlocked):
        run_select(sql, db_path=db_path)


@pytest.mark.unit
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT name FROM sqlite_master",
        "SELECT sql FROM sqlite_schema",
        "SELECT load_extension('evil')",
    ],
)
def test_reads_beyond_sales_data_are_refused(db_path, sql) -> None:
    with pytest.raises(QueryBlocked):
        run_select(sql, db_path=db_path)


@pytest.fixture
def db_with_other_tables(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE secrets (value TEXT)")
    conn.execute("INSERT INTO secrets VALUES ('hidden')")
    conn.execute("CREATE VIEW secrets_view AS SELECT value FROM secrets")
    conn.commit()
    conn.close()
    return db_path


@pytest.mark.unit
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT value FROM secrets",
        "SELECT value FROM SECRETS",
        "SELECT value FROM secrets_view",
        "SELECT s.revenue FROM sales_data s JOIN secrets ON 1 = 1",
        "WITH t AS (SELECT value FROM secrets) SELECT * FROM t",
    ],
)
def test_other_tables_in_the_file_are_refused(db_with_other_tables, sql) -> None:
    with pytest.raises(QueryBlocked):
        run_select(sql, db_path=db_with_other_tables)


@pytest.mark.unit
def test_sales_data_and_ctes_still_work_beside_other_tables(db_with_other_tables) -> None:
    result = run_select(
        "WITH RECURSIVE m(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM m WHERE n < 3) "
        "SELECT COUNT(*) FROM sales_data, m",
        db_path=db_with_other_tables,
    )
    assert result.rows == [(450,)]


@pytest.mark.unit
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT revenue FROM sales_data; DROP TABLE sales_data",
        "SELECT revenue FROM sales_data\nATTACH DATABASE 'evil.db' AS evil",
        "SELECT revenue FROM sales_data\nPRAGMA journal_mode=WAL",
    ],
)
def test_a_second_statement_never_runs(db_path, sql) -> None:
    with pytest.raises(sqlite3.Error):
        run_select(sql, db_path=db_path)

    # And the table is untouched.
    assert run_select("SELECT COUNT(*) FROM sales_data", db_path=db_path).rows == [(150,)]


@pytest.mark.unit
def test_writes_fail_even_past_the_authorizer(db_path) -> None:
    """The connection is read-only regardless: a write is refused, not run."""
    with pytest.raises(sqlite3.Error):
        run_select(
            "WITH x AS (SELECT 1) INSERT INTO sales_data SELECT 'x', 1 FROM x", db_path=db_path
        )
    assert run_select("SELECT COUNT(*) FROM sales_data", db_path=db_path).rows == [(150,)]


@pytest.mark.unit
def test_runaway_query_is_interrupted(db_path) -> None:
    with pytest.raises(QueryTimeout):
        run_select(
            "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT COUNT(*) FROM r",
            timeout_seconds=0.5,
            db_path=db_path,
        )


@pytest.mark.unit
def test_ordinary_errors_are_sqlite_errors(db_path) -> None:
    with pytest.raises(sqlite3.OperationalError):
        run_select("SELECT no_such_column FROM sales_data", db_path=db_path)
