"""
Unit tests for SQL extraction in archer.ai.sql_generator.

These exercise extract_sql() and generate_sql() without calling any real model:
the model is a MagicMock whose .invoke() replies with controlled text.

Extraction is a tidying step. It takes one statement out of a chat reply -
fenced or not, on one line or several - and stops at the first semicolon,
comment or backtick outside a quoted string. It is not the safety boundary:
generated SQL is executed only through archer.db.query.run_select, whose
engine-level restrictions are tested in test_query_guard.py.
"""

import pytest
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage

from archer.ai.sql_generator import extract_sql, generate_sql


def _mock_llm(sql_response: str) -> MagicMock:
    """Return a MagicMock chat model whose .invoke() replies with the given text."""
    llm = MagicMock()
    llm.invoke.return_value = AIMessage(content=sql_response)
    return llm


SCHEMA = "customer_name, revenue"


# ---------------------------------------------------------------------------
# generate_sql: the model is called once, and its reply is extracted
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_no_select_in_response_returns_empty() -> None:
    """A reply with no SELECT yields an empty SQL string."""
    sql, _ = generate_sql(_mock_llm("I cannot generate that query."), "some question", SCHEMA)
    assert sql == ""


@pytest.mark.unit
def test_clean_select_is_returned_unchanged() -> None:
    raw = "SELECT customer_name, revenue FROM sales_data LIMIT 10"
    sql, raw_reply = generate_sql(_mock_llm(raw), "show me customers", SCHEMA)
    assert sql == raw
    assert raw_reply == raw


@pytest.mark.unit
def test_empty_llm_response_returns_empty() -> None:
    sql, _ = generate_sql(_mock_llm(""), "anything", SCHEMA)
    assert sql == ""


@pytest.mark.unit
def test_model_is_called_once_with_chat_messages() -> None:
    llm = _mock_llm("SELECT 1")
    generate_sql(llm, "what is one?", SCHEMA)

    assert llm.invoke.call_count == 1
    messages = llm.invoke.call_args.args[0]
    assert all(role in ("system", "user", "assistant") for role, _ in messages)
    assert "what is one?" in messages[-1][1]


@pytest.mark.unit
def test_question_with_braces_renders() -> None:
    """
    Braces used to be escaped into the prompt and then rejected by the
    renderer as unfilled placeholders, so any question containing one failed.
    """
    llm = _mock_llm("SELECT 1")
    generate_sql(llm, "revenue for {weird} partner {{name}}", SCHEMA)
    assert "{weird} partner {{name}}" in llm.invoke.call_args.args[0][-1][1]


# ---------------------------------------------------------------------------
# extract_sql: where a statement starts
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_multi_line_sql_is_kept_whole() -> None:
    raw = "SELECT customer_name,\n       SUM(revenue)\nFROM sales_data\nGROUP BY customer_name"
    assert extract_sql(raw) == raw


@pytest.mark.unit
def test_fenced_sql_is_unwrapped() -> None:
    raw = "Here you go:\n```sql\nSELECT revenue\nFROM sales_data\n```\nHope that helps."
    assert extract_sql(raw) == "SELECT revenue\nFROM sales_data"


@pytest.mark.unit
def test_prose_before_the_query_is_skipped() -> None:
    assert extract_sql("The query is SELECT revenue FROM sales_data") == "SELECT revenue FROM sales_data"


@pytest.mark.unit
def test_with_statement_is_accepted() -> None:
    raw = "WITH t AS (SELECT revenue FROM sales_data) SELECT SUM(revenue) FROM t"
    assert extract_sql(raw) == raw


@pytest.mark.unit
def test_unterminated_fence_is_tolerated() -> None:
    assert extract_sql("```sql\nSELECT revenue FROM sales_data LIMIT 5") == (
        "SELECT revenue FROM sales_data LIMIT 5"
    )


@pytest.mark.unit
def test_trailing_fence_is_dropped() -> None:
    assert extract_sql("SELECT revenue FROM sales_data LIMIT 5```") == (
        "SELECT revenue FROM sales_data LIMIT 5"
    )


# ---------------------------------------------------------------------------
# extract_sql: where a statement ends
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_semicolon_ends_the_statement() -> None:
    sql = extract_sql("SELECT revenue FROM sales_data; DROP TABLE sales_data")
    assert sql == "SELECT revenue FROM sales_data"
    assert "DROP" not in sql


@pytest.mark.unit
def test_double_dash_comment_ends_the_statement() -> None:
    assert extract_sql("SELECT revenue FROM sales_data -- injected") == "SELECT revenue FROM sales_data"


@pytest.mark.unit
def test_block_comment_ends_the_statement() -> None:
    assert extract_sql("SELECT revenue FROM sales_data /* comment") == "SELECT revenue FROM sales_data"


@pytest.mark.unit
def test_terminators_inside_a_string_literal_are_kept() -> None:
    """
    The old extractor cut at every ';', '#' and '--', so a filter on a name
    containing one of them was truncated into a broken query.
    """
    raw = "SELECT revenue FROM sales_data WHERE customer_name = 'Smith #1; Ltd -- UK'"
    assert extract_sql(raw) == raw


@pytest.mark.unit
def test_escaped_quote_inside_a_literal_is_handled() -> None:
    raw = "SELECT revenue FROM sales_data WHERE customer_name = 'O''Brien; Sons'"
    assert extract_sql(raw + "; DROP TABLE x") == raw


@pytest.mark.unit
def test_text_without_a_statement_returns_empty() -> None:
    assert extract_sql("No query here, sorry.") == ""
