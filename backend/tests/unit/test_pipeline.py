"""
Unit tests for archer.pipeline: the structured Turn and the legacy answer.

Model calls are patched at the names the pipeline looks them up under; the SQL
runs for real against a small temporary database through run_select.
"""

import asyncio
import os
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from archer import pipeline
from archer.ai.planner import Plan, PlannedPart
from archer.pipeline import (
    MEMORY_MAX_ANSWER,
    MEMORY_MAX_CELL,
    MEMORY_MAX_ROWS,
    MODEL_ERROR_MESSAGE,
    Part,
    Turn,
    build_history_item,
    format_legacy,
    run_turn,
)


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE sales_data (customer_name TEXT, revenue REAL, quantity REAL)")
    conn.executemany(
        "INSERT INTO sales_data VALUES (?, ?, ?)",
        [("Acme Ltd", 1000.0, 5.0), ("Beta\nLtd", 2500.5, 2.0)],
    )
    conn.commit()
    conn.close()
    yield path
    os.unlink(path)


def _run(question, db_path, *, route="1", sql=None, chat="Hello."):
    kind = "data" if route == "1" else "chat"
    plan = Plan(kind=kind, parts=[PlannedPart(kind=kind, question=question)])
    with (
        patch("archer.pipeline.create_llm", return_value=MagicMock()),
        patch("archer.pipeline.plan_message", return_value=plan),
        patch("archer.pipeline.generate_sql", return_value=(sql or "", sql or "no sql")),
        patch("archer.pipeline.generate_chat_response", return_value=chat),
        patch("archer.pipeline.database_path", return_value=db_path),
        patch("archer.db.query.database_path", return_value=db_path),
        patch("archer.pipeline.schema_columns", return_value=("customer_name", "revenue", "quantity")),
    ):
        return asyncio.run(run_turn(question))


# ---------------------------------------------------------------------------
# Data parts
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_scalar_answer(db_path) -> None:
    turn = _run("total?", db_path, sql="SELECT SUM(revenue) FROM sales_data")
    part = turn.parts[0]

    assert turn.kind == "data"
    assert (part.type, part.status, part.value) == ("data", "ok", "£3,500.50")
    assert format_legacy(turn) == (
        "Based on the data, the answer is: **£3,500.50** \n\n"
        "*(SQL used: SELECT SUM(revenue) FROM sales_data)*"
    )


@pytest.mark.unit
def test_table_answer_formats_cells(db_path) -> None:
    turn = _run("all", db_path, sql="SELECT customer_name, revenue, quantity FROM sales_data")
    part = turn.parts[0]

    assert part.columns == ["customer_name", "revenue", "quantity"]
    assert part.rows == [["Acme Ltd", "£1,000.00", "5"], ["Beta, Ltd", "£2,500.50", "2"]]
    assert part.row_count == 2
    assert format_legacy(turn).startswith("Here is the data you requested:\n\n| customer_name | revenue | quantity |\n")


@pytest.mark.unit
def test_empty_result(db_path) -> None:
    turn = _run("x", db_path, sql="SELECT customer_name FROM sales_data WHERE revenue < 0")
    assert turn.parts[0].status == "empty"
    assert format_legacy(turn).startswith("I couldn't find any data matching that request.")


@pytest.mark.unit
def test_sum_over_no_rows_is_empty_not_none(db_path) -> None:
    """SUM() over nothing returns NULL; that used to be shown as 'the answer is: None'."""
    turn = _run("x", db_path, sql="SELECT SUM(revenue) FROM sales_data WHERE revenue < 0")
    assert turn.parts[0].status == "empty"
    assert "None" not in format_legacy(turn)


@pytest.mark.unit
def test_query_refused_by_the_guard_is_blocked(db_path) -> None:
    turn = _run("x", db_path, sql="SELECT name FROM sqlite_master")
    assert turn.parts[0].status == "blocked"
    assert format_legacy(turn) == "I can only execute SELECT queries for security reasons."


@pytest.mark.unit
def test_sql_error_gives_the_polite_message(db_path) -> None:
    turn = _run("x", db_path, sql="SELECT nope FROM sales_data")
    assert turn.parts[0].status == "sql_error"
    assert format_legacy(turn).startswith("I understood you need data")


@pytest.mark.unit
def test_no_sql(db_path) -> None:
    turn = _run("x", db_path, sql="")
    assert turn.parts[0].status == "no_sql"


# ---------------------------------------------------------------------------
# Chat parts and failures
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_chat_answer(db_path) -> None:
    turn = _run("hi", db_path, route="2", chat="Hello there.")
    assert turn.kind == "chat"
    assert turn.parts[0].text == "Hello there."
    assert format_legacy(turn) == "Hello there."


@pytest.mark.unit
def test_model_outage_is_an_answer_not_a_500(db_path) -> None:
    with (
        patch("archer.pipeline.create_llm", return_value=MagicMock()),
        patch("archer.pipeline.plan_message", side_effect=RuntimeError("watsonx down")),
    ):
        turn = asyncio.run(run_turn("anything"))
    assert turn.kind == "error"
    assert turn.parts[0].status == "model_error"
    assert format_legacy(turn) == MODEL_ERROR_MESSAGE


# ---------------------------------------------------------------------------
# History items
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_memory_is_built_and_capped() -> None:
    long_cell = "x" * 500
    part = Part(
        type="data",
        question="q",
        text="Here is the data you requested:",
        sql="SELECT 1",
        columns=[f"c{i}" for i in range(12)],
        rows=[[long_cell] * 12 for _ in range(50)],
    )
    memory = build_history_item("q", Turn(kind="data", parts=[part]))

    assert len(memory.rows) == MEMORY_MAX_ROWS
    assert len(memory.columns) == 8
    assert all(len(row) == 8 for row in memory.rows)
    assert all(len(cell) <= MEMORY_MAX_CELL for row in memory.rows for cell in row)
    assert memory.sql == "SELECT 1"


@pytest.mark.unit
def test_chat_memory_answer_is_capped() -> None:
    part = Part(type="chat", question="q", text="y" * 5000)
    memory = build_history_item("q", Turn(kind="chat", parts=[part]))
    assert len(memory.answer) <= MEMORY_MAX_ANSWER


@pytest.mark.unit
def test_turn_carries_its_memory(db_path) -> None:
    turn = _run("total?", db_path, sql="SELECT SUM(revenue) FROM sales_data")
    assert turn.memory.question == "total?"
    assert turn.memory.sql == "SELECT SUM(revenue) FROM sales_data"
    assert "£3,500.50" in turn.memory.answer


@pytest.mark.unit
def test_budget_turn() -> None:
    turn = pipeline.budget_turn("q", "Limit reached.")
    assert turn.kind == "budget"
    assert format_legacy(turn) == "Limit reached."
