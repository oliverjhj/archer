"""
Unit tests for the /ask route handler in archer.api.ask.

Isolation strategy
------------------
A minimal FastAPI application is assembled inside this module containing only
the ask router.  The real archer.app is never imported, so the lifespan event
handler and verify_database() are never triggered.

All external dependencies called inside ask_ai() are patched at the name they
are looked up under inside archer.api.ask:

  - archer.pipeline.create_llm          -- prevents WatsonxLLM instantiation
  - archer.pipeline.classify_query      -- controls route decision
  - archer.pipeline.generate_chat_response -- controls Route B output
  - archer.pipeline.generate_sql        -- controls Route A SQL output
  - archer.pipeline.os.path.exists      -- controls database-file presence check
  - archer.pipeline.os.path.abspath     -- redirects DB path to a temp file

The WEBHOOK_SECRET stub injected by conftest.py
("test-webhook-secret-stub-not-for-production") is used as the valid API key
header value throughout.

No .env file, real sales.db, IBM Cloud, watsonx, or network access is
required or permitted.
"""

import os
import sqlite3
import tempfile
import pytest

from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from starlette.testclient import TestClient
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

from archer.api import ask as ask_module
from archer.core.limiter import limiter


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Must match the stub set in backend/tests/conftest.py
_VALID_API_KEY = "test-webhook-secret-stub-not-for-production"

_ASK_URL = "/ask"


# ---------------------------------------------------------------------------
# Module-level test app
# ---------------------------------------------------------------------------

def _build_test_app() -> FastAPI:
    """
    Build and return a minimal FastAPI application containing only the ask
    router.  No lifespan, no static files, no archer.app side effects.
    """
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(ask_module.router)
    return app


_test_app = _build_test_app()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client() -> TestClient:
    """Return a TestClient for the minimal test app."""
    return TestClient(_test_app, raise_server_exceptions=False)


def _post(client: TestClient, question: str, api_key: str | None = _VALID_API_KEY) -> object:
    """
    POST to /ask with the given question and optional API key header.
    Omits the header entirely when api_key is None.
    """
    headers = {"x-api-key": api_key} if api_key is not None else {}
    return client.post(_ASK_URL, json={"question": question}, headers=headers)


def _make_temp_sales_db() -> str:
    """
    Create a temporary SQLite file with a minimal sales_data table and a small
    set of fixed, deterministic rows.  Returns the absolute path to the file.
    The caller is responsible for deleting the file after use.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE sales_data (
            customer_name       TEXT,
            document_date       TEXT,
            document_number     TEXT,
            item_group          TEXT,
            item_description    TEXT,
            revenue             REAL,
            end_user_company_name TEXT,
            quantity            REAL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO sales_data VALUES
            ('Acme Ltd', '2025-01-15', 'DOC001', 'IBM SOFT',
             'Software Licence', 1000.00, 'End User A', 5)
        """
    )
    conn.commit()
    conn.close()
    return path


# ---------------------------------------------------------------------------
# API key validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_missing_api_key_returns_401() -> None:
    """A request with no x-api-key header is rejected with HTTP 401."""
    client = _client()
    response = _post(client, "hello", api_key=None)
    assert response.status_code == 401


@pytest.mark.unit
def test_invalid_api_key_returns_401() -> None:
    """A request carrying a wrong x-api-key value is rejected with HTTP 401."""
    client = _client()
    response = _post(client, "hello", api_key="completely-wrong-key")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Route B: general chat path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_chat_route_returns_mocked_answer() -> None:
    """
    When the classifier returns route "2" the chat path is taken and the
    mocked generate_chat_response() return value appears in the response body.
    """
    mock_llm = MagicMock()
    chat_answer = "Hello, I am Archer."

    with (
        patch("archer.pipeline.create_llm", return_value=mock_llm),
        patch("archer.pipeline.classify_query", return_value="2"),
        patch("archer.pipeline.generate_chat_response", return_value=chat_answer),
    ):
        client = _client()
        response = _post(client, "Who are you?")

    assert response.status_code == 200
    assert response.json()["answer"] == chat_answer


@pytest.mark.unit
def test_chat_route_calls_generate_chat_response_once() -> None:
    """generate_chat_response() is called exactly once for a Route B request."""
    mock_llm = MagicMock()
    mock_generate_chat = MagicMock(return_value="Hi.")

    with (
        patch("archer.pipeline.create_llm", return_value=mock_llm),
        patch("archer.pipeline.classify_query", return_value="2"),
        patch("archer.pipeline.generate_chat_response", mock_generate_chat),
    ):
        client = _client()
        _post(client, "Hello")

    mock_generate_chat.assert_called_once()


# ---------------------------------------------------------------------------
# Route A: SQL path — guard conditions
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sql_route_database_file_missing_returns_unavailable_message() -> None:
    """
    When the database file does not exist the route returns the
    database-unavailable message without attempting a connection.
    """
    mock_llm = MagicMock()

    with (
        patch("archer.pipeline.create_llm", return_value=mock_llm),
        patch("archer.pipeline.classify_query", return_value="1"),
        patch("archer.pipeline.os.path.exists", return_value=False),
    ):
        client = _client()
        response = _post(client, "Show me revenue")

    assert response.status_code == 200
    assert response.json()["answer"] == "Database temporarily unavailable. Please contact support."


@pytest.mark.unit
def test_sql_route_empty_sql_returns_invalid_query_message() -> None:
    """
    When generate_sql() returns an empty SQL string the route returns the
    invalid-query message.
    """
    mock_llm = MagicMock()
    tmp_db = _make_temp_sales_db()

    try:
        with (
            patch("archer.pipeline.create_llm", return_value=mock_llm),
            patch("archer.pipeline.classify_query", return_value="1"),
            patch("archer.pipeline.os.path.exists", return_value=True),
            patch("archer.pipeline.os.path.abspath", return_value=tmp_db),
            patch("archer.pipeline.generate_sql", return_value=("", "I could not parse that")),
        ):
            client = _client()
            response = _post(client, "Something unparseable")
    finally:
        os.unlink(tmp_db)

    assert response.status_code == 200
    body = response.json()
    assert "I couldn't generate a valid SQL query" in body["answer"]
    assert "I could not parse that" in body["answer"]


@pytest.mark.unit
def test_sql_route_non_select_sql_is_blocked() -> None:
    """
    When generate_sql() returns a non-SELECT statement the route returns the
    security-rejection message and does not execute the query.
    """
    mock_llm = MagicMock()
    tmp_db = _make_temp_sales_db()

    try:
        with (
            patch("archer.pipeline.create_llm", return_value=mock_llm),
            patch("archer.pipeline.classify_query", return_value="1"),
            patch("archer.pipeline.os.path.exists", return_value=True),
            patch("archer.pipeline.os.path.abspath", return_value=tmp_db),
            patch(
                "archer.pipeline.generate_sql",
                return_value=("DROP TABLE sales_data", "DROP TABLE sales_data"),
            ),
        ):
            client = _client()
            response = _post(client, "Delete everything")
    finally:
        os.unlink(tmp_db)

    assert response.status_code == 200
    assert response.json()["answer"] == "I can only execute SELECT queries for security reasons."


# ---------------------------------------------------------------------------
# Route A: SQL path — happy path with temporary SQLite database
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sql_route_select_returns_answer_response() -> None:
    """
    When generate_sql() returns a valid SELECT and a temporary SQLite database
    exists, the route executes the query and returns an answer response.

    The SELECT targets the single row inserted into the temp database so the
    result is fully deterministic.
    """
    mock_llm = MagicMock()
    tmp_db = _make_temp_sales_db()

    # The query returns all columns for the one row in the temp database.
    select_sql = (
        "SELECT customer_name, document_date, document_number, item_group, "
        "item_description, revenue, end_user_company_name, quantity "
        "FROM sales_data"
    )

    try:
        with (
            patch("archer.pipeline.create_llm", return_value=mock_llm),
            patch("archer.pipeline.classify_query", return_value="1"),
            patch("archer.pipeline.os.path.exists", return_value=True),
            patch("archer.pipeline.os.path.abspath", return_value=tmp_db),
            patch(
                "archer.pipeline.generate_sql",
                return_value=(select_sql, select_sql),
            ),
        ):
            client = _client()
            response = _post(client, "Show me all sales")
    finally:
        os.unlink(tmp_db)

    assert response.status_code == 200
    body = response.json()
    # The response must contain an "answer" key with content drawn from the DB row.
    assert "answer" in body
    answer = body["answer"]
    assert "Acme Ltd" in answer
    assert "DOC001" in answer


# ---------------------------------------------------------------------------
# Route A: SQL path — SQL response formatting
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sql_zero_rows_returns_no_data_message() -> None:
    """
    When the executed SELECT returns no rows the route returns the
    no-data message and references the attempted query.
    """
    mock_llm = MagicMock()
    tmp_db = _make_temp_sales_db()

    # A WHERE clause that matches nothing guarantees an empty result set.
    select_sql = "SELECT customer_name FROM sales_data WHERE 1=0"

    try:
        with (
            patch("archer.pipeline.create_llm", return_value=mock_llm),
            patch("archer.pipeline.classify_query", return_value="1"),
            patch("archer.pipeline.os.path.exists", return_value=True),
            patch("archer.pipeline.os.path.abspath", return_value=tmp_db),
            patch("archer.pipeline.generate_sql", return_value=(select_sql, select_sql)),
        ):
            client = _client()
            response = _post(client, "Show me missing data")
    finally:
        os.unlink(tmp_db)

    assert response.status_code == 200
    answer = response.json()["answer"]
    assert "couldn't find any data" in answer
    assert select_sql in answer


@pytest.mark.unit
def test_sql_single_scalar_integer_formats_with_commas() -> None:
    """
    A single-cell result whose column name does not contain "revenue" and whose
    value is a whole number is formatted with comma-separated thousands and no
    decimal places, wrapped in the single-scalar answer phrase.
    """
    mock_llm = MagicMock()
    tmp_db = _make_temp_sales_db()

    # COUNT(*) returns an integer scalar; the column alias avoids any revenue
    # name match so the integer-comma branch is exercised.
    select_sql = "SELECT COUNT(*) AS total_count FROM sales_data"

    try:
        with (
            patch("archer.pipeline.create_llm", return_value=mock_llm),
            patch("archer.pipeline.classify_query", return_value="1"),
            patch("archer.pipeline.os.path.exists", return_value=True),
            patch("archer.pipeline.os.path.abspath", return_value=tmp_db),
            patch("archer.pipeline.generate_sql", return_value=(select_sql, select_sql)),
        ):
            client = _client()
            response = _post(client, "How many records?")
    finally:
        os.unlink(tmp_db)

    assert response.status_code == 200
    answer = response.json()["answer"]
    # Single-scalar branch prefix.
    assert "Based on the data, the answer is:" in answer
    # One row inserted; COUNT(*) = 1, formatted as "1" (no comma needed but
    # the branch must have fired — confirm the value is present).
    assert "**1**" in answer


@pytest.mark.unit
def test_sql_single_scalar_revenue_formats_with_pound_sign() -> None:
    """
    A single-cell result whose column name contains "revenue" is formatted with
    a pound sign and two decimal places in the single-scalar answer phrase.

    The temp database contains revenue = 1000.00 for the single row.
    """
    mock_llm = MagicMock()
    tmp_db = _make_temp_sales_db()

    # Alias uses "revenue" so the currency formatting branch fires.
    select_sql = "SELECT revenue AS total_revenue FROM sales_data"

    try:
        with (
            patch("archer.pipeline.create_llm", return_value=mock_llm),
            patch("archer.pipeline.classify_query", return_value="1"),
            patch("archer.pipeline.os.path.exists", return_value=True),
            patch("archer.pipeline.os.path.abspath", return_value=tmp_db),
            patch("archer.pipeline.generate_sql", return_value=(select_sql, select_sql)),
        ):
            client = _client()
            response = _post(client, "What is total revenue?")
    finally:
        os.unlink(tmp_db)

    assert response.status_code == 200
    answer = response.json()["answer"]
    assert "Based on the data, the answer is:" in answer
    # Revenue of 1000.00 formatted as £1,000.00.
    assert "£1,000.00" in answer


@pytest.mark.unit
def test_sql_single_row_multiple_columns_returns_markdown_table() -> None:
    """
    A single row with multiple columns falls into the table branch.
    The response must contain a Markdown-style header row with pipe characters,
    a separator row, and the data values from the temp database row.
    """
    mock_llm = MagicMock()
    tmp_db = _make_temp_sales_db()

    select_sql = (
        "SELECT customer_name, document_number, item_description "
        "FROM sales_data"
    )

    try:
        with (
            patch("archer.pipeline.create_llm", return_value=mock_llm),
            patch("archer.pipeline.classify_query", return_value="1"),
            patch("archer.pipeline.os.path.exists", return_value=True),
            patch("archer.pipeline.os.path.abspath", return_value=tmp_db),
            patch("archer.pipeline.generate_sql", return_value=(select_sql, select_sql)),
        ):
            client = _client()
            response = _post(client, "Show me customer details")
    finally:
        os.unlink(tmp_db)

    assert response.status_code == 200
    answer = response.json()["answer"]
    # Table-branch opening phrase.
    assert "Here is the data you requested" in answer
    # Column headers must appear in the Markdown table header row.
    assert "customer_name" in answer
    assert "document_number" in answer
    assert "item_description" in answer
    # Separator row marker.
    assert "---" in answer
    # Data values from the single inserted row.
    assert "Acme Ltd" in answer
    assert "DOC001" in answer
    assert "Software Licence" in answer


@pytest.mark.unit
def test_sql_multiple_rows_returns_all_rows_in_table() -> None:
    """
    When the SELECT returns multiple rows all row values appear in the
    Markdown table response.

    A second row is inserted into the temp database before the query is
    executed so the result is deterministic.
    """
    mock_llm = MagicMock()
    tmp_db = _make_temp_sales_db()

    # Insert a second deterministic row before issuing the SELECT.
    conn = sqlite3.connect(tmp_db)
    conn.execute(
        """
        INSERT INTO sales_data VALUES
            ('Beta Corp', '2025-02-20', 'DOC002', 'IBM HW',
             'Server Hardware', 2500.00, 'End User B', 3)
        """
    )
    conn.commit()
    conn.close()

    select_sql = "SELECT customer_name, document_number FROM sales_data"

    try:
        with (
            patch("archer.pipeline.create_llm", return_value=mock_llm),
            patch("archer.pipeline.classify_query", return_value="1"),
            patch("archer.pipeline.os.path.exists", return_value=True),
            patch("archer.pipeline.os.path.abspath", return_value=tmp_db),
            patch("archer.pipeline.generate_sql", return_value=(select_sql, select_sql)),
        ):
            client = _client()
            response = _post(client, "Show me all customers")
    finally:
        os.unlink(tmp_db)

    assert response.status_code == 200
    answer = response.json()["answer"]
    assert "Here is the data you requested" in answer
    # Both rows must be present.
    assert "Acme Ltd" in answer
    assert "DOC001" in answer
    assert "Beta Corp" in answer
    assert "DOC002" in answer


@pytest.mark.unit
def test_sql_revenue_column_in_table_formats_with_pound_sign() -> None:
    """
    In the table branch, cells in a column whose name contains "revenue" are
    formatted with a pound sign and two decimal places.

    The temp database revenue column holds 1000.00 for the existing row.
    """
    mock_llm = MagicMock()
    tmp_db = _make_temp_sales_db()

    select_sql = "SELECT customer_name, revenue FROM sales_data"

    try:
        with (
            patch("archer.pipeline.create_llm", return_value=mock_llm),
            patch("archer.pipeline.classify_query", return_value="1"),
            patch("archer.pipeline.os.path.exists", return_value=True),
            patch("archer.pipeline.os.path.abspath", return_value=tmp_db),
            patch("archer.pipeline.generate_sql", return_value=(select_sql, select_sql)),
        ):
            client = _client()
            response = _post(client, "Show me revenue by customer")
    finally:
        os.unlink(tmp_db)

    assert response.status_code == 200
    answer = response.json()["answer"]
    assert "Here is the data you requested" in answer
    # Revenue value 1000.00 must be rendered as £1,000.00.
    assert "£1,000.00" in answer
    assert "Acme Ltd" in answer


@pytest.mark.unit
def test_sql_quantity_column_in_table_formats_as_integer() -> None:
    """
    In the table branch, cells in a column whose name contains "quantity" are
    rendered as comma-separated whole integers (no decimal places).

    The temp database quantity column holds 5.0 for the existing row;
    the expected formatted value is "5".
    """
    mock_llm = MagicMock()
    tmp_db = _make_temp_sales_db()

    select_sql = "SELECT customer_name, quantity FROM sales_data"

    try:
        with (
            patch("archer.pipeline.create_llm", return_value=mock_llm),
            patch("archer.pipeline.classify_query", return_value="1"),
            patch("archer.pipeline.os.path.exists", return_value=True),
            patch("archer.pipeline.os.path.abspath", return_value=tmp_db),
            patch("archer.pipeline.generate_sql", return_value=(select_sql, select_sql)),
        ):
            client = _client()
            response = _post(client, "Show me quantities sold")
    finally:
        os.unlink(tmp_db)

    assert response.status_code == 200
    answer = response.json()["answer"]
    assert "Here is the data you requested" in answer
    # quantity 5.0 must be rendered as the integer "5", not "5.0" or "5.00".
    assert "| 5 |" in answer
    assert "Acme Ltd" in answer


# ---------------------------------------------------------------------------
# Route A: SQL path — SQL execution error
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sql_execution_error_returns_rephrasing_message() -> None:
    """
    When cursor.execute() raises sqlite3.OperationalError (a subclass of
    sqlite3.Error) because the generated SQL references a non-existent column,
    the route catches the exception and returns the polite rephrasing message.

    No mocking of the exception is required; SQLite raises it naturally when
    asked to select a column that does not exist in the schema.
    """
    mock_llm = MagicMock()
    tmp_db = _make_temp_sales_db()

    # This SQL is syntactically valid SELECT but references a column that does
    # not exist in the temp database, causing sqlite3.OperationalError.
    bad_sql = "SELECT nonexistent_column FROM sales_data"

    try:
        with (
            patch("archer.pipeline.create_llm", return_value=mock_llm),
            patch("archer.pipeline.classify_query", return_value="1"),
            patch("archer.pipeline.os.path.exists", return_value=True),
            patch("archer.pipeline.os.path.abspath", return_value=tmp_db),
            patch("archer.pipeline.generate_sql", return_value=(bad_sql, bad_sql)),
        ):
            client = _client()
            response = _post(client, "Show me something broken")
    finally:
        os.unlink(tmp_db)

    assert response.status_code == 200
    answer = response.json()["answer"]
    # The route must return the user-facing rephrasing message, not a 500.
    assert "I understood you need data" in answer
    assert "trouble running that specific query" in answer


# ---------------------------------------------------------------------------
# /ask edge cases: request body validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_missing_question_field_returns_422() -> None:
    """
    A POST to /ask whose body omits the required ``question`` field is
    rejected with HTTP 422 Unprocessable Entity by FastAPI's Pydantic
    validation layer.

    A valid API key header is supplied so that authentication does not mask
    the body-validation error.
    """
    client = _client()
    response = client.post(
        _ASK_URL,
        json={"not_question": "oops"},
        headers={"x-api-key": _VALID_API_KEY},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# /ask edge cases: list question
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_question_as_list_routes_to_chat() -> None:
    """
    When the ``question`` field is supplied as a JSON array the endpoint
    accepts the request, coerces the value, and returns a chat response.

    The Union[str, List[str]] schema in AskRequest permits this; the handler
    joins the list into one string before it reaches the classifier.
    A mocked classifier returning "2" directs the flow to Route B (chat).
    """
    mock_llm = MagicMock()
    chat_answer = "Hello from Archer."

    with (
        patch("archer.pipeline.create_llm", return_value=mock_llm),
        patch("archer.pipeline.classify_query", return_value="2"),
        patch("archer.pipeline.generate_chat_response", return_value=chat_answer),
    ):
        client = _client()
        response = client.post(
            _ASK_URL,
            json={"question": ["What is the revenue?"]},
            headers={"x-api-key": _VALID_API_KEY},
        )

    assert response.status_code == 200
    assert response.json()["answer"] == chat_answer


# ---------------------------------------------------------------------------
# /ask edge cases: classifier returns unexpected value
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_classifier_unexpected_value_falls_back_to_chat() -> None:
    """
    When classify_query() returns a value that is neither "1" nor "2" the
    handler falls through to the else branch and invokes the chat path.

    This test uses "3" as the unexpected classifier return value to confirm
    that the routing logic's default case is the chat route.
    """
    mock_llm = MagicMock()
    mock_chat = MagicMock(return_value="Fallback chat response.")

    with (
        patch("archer.pipeline.create_llm", return_value=mock_llm),
        patch("archer.pipeline.classify_query", return_value="3"),
        patch("archer.pipeline.generate_chat_response", mock_chat),
    ):
        client = _client()
        response = _post(client, "Unexpected route question")

    assert response.status_code == 200
    assert response.json()["answer"] == "Fallback chat response."
    mock_chat.assert_called_once()


# ---------------------------------------------------------------------------
# /ask edge cases: 101-row truncation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sql_101_rows_triggers_truncation_note() -> None:
    """
    When the executed SELECT returns 101 rows, fetchmany(101) retrieves all
    101, the handler detects len >= 100, slices to 100 rows, and appends the
    user-facing truncation note to the response.

    A temporary SQLite database is created with 101 deterministic rows.
    The SQL is patched to a plain SELECT * so that all rows are returned.
    """
    mock_llm = MagicMock()
    tmp_db = _make_temp_sales_db()  # Creates table with 1 row.

    # Insert 100 additional rows to reach 101 total.
    conn = sqlite3.connect(tmp_db)
    for i in range(2, 103):
        conn.execute(
            """
            INSERT INTO sales_data VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"Customer {i}",
                "2025-01-01",
                f"DOC{i:04d}",
                "IBM SOFT",
                "Software Licence",
                float(i * 100),
                f"End User {i}",
                float(i),
            ),
        )
    conn.commit()
    conn.close()

    select_sql = "SELECT customer_name, revenue FROM sales_data"

    try:
        with (
            patch("archer.pipeline.create_llm", return_value=mock_llm),
            patch("archer.pipeline.classify_query", return_value="1"),
            patch("archer.pipeline.os.path.exists", return_value=True),
            patch("archer.pipeline.os.path.abspath", return_value=tmp_db),
            patch("archer.pipeline.generate_sql", return_value=(select_sql, select_sql)),
        ):
            client = _client()
            response = _post(client, "Show me all customers")
    finally:
        os.unlink(tmp_db)

    assert response.status_code == 200
    answer = response.json()["answer"]
    # Truncation note must appear in the response.
    assert "100 rows" in answer
    assert "performance" in answer
    # The table itself must also be present.
    assert "Here is the data you requested" in answer
