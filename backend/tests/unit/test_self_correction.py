"""
Unit tests for self-correcting SQL and written summaries.

SQL runs for real against a small temporary database; the model calls are
patched at the names the pipeline looks them up under.
"""

import asyncio
import os
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from archer.ai.summary import is_grounded, result_text
from archer.pipeline import Turn, format_legacy, run_data_part


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE sales_data (customer_name TEXT, revenue REAL)")
    conn.executemany(
        "INSERT INTO sales_data VALUES (?, ?)",
        [("Acme Ltd", 1000.0), ("Beta Ltd", 2500.5), ("Gamma PLC", 750.25)],
    )
    conn.commit()
    conn.close()
    yield path
    os.unlink(path)


GOOD = "SELECT customer_name, revenue FROM sales_data ORDER BY revenue DESC"


def _run(db_path, first_sql, retry_sql=None, summary="Beta Ltd leads with £2,500.50.", summary_error=None):
    regenerate = MagicMock(return_value=(retry_sql or "", retry_sql or ""))
    summarise = MagicMock(return_value=summary, side_effect=summary_error)
    trace: dict = {}
    with (
        patch("archer.pipeline.create_llm", return_value=MagicMock()),
        patch("archer.pipeline.generate_sql", return_value=(first_sql, first_sql or "no sql")),
        patch("archer.pipeline.regenerate_sql", regenerate),
        patch("archer.pipeline.summarise", summarise),
        patch("archer.pipeline.database_path", return_value=db_path),
        patch("archer.db.query.database_path", return_value=db_path),
        patch("archer.pipeline.schema_columns", return_value=("customer_name", "revenue")),
    ):
        part = asyncio.run(run_data_part("Who are our biggest partners?", trace))
    return part, regenerate, summarise, trace


# ---------------------------------------------------------------------------
# Self-correction
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_failed_query_is_corrected(db_path) -> None:
    part, regenerate, _, trace = _run(db_path, "SELECT nope FROM sales_data", GOOD)

    assert part.status == "ok"
    assert part.corrected is True
    assert part.sql == GOOD
    assert trace["sql_attempts"] == ["SELECT nope FROM sales_data", GOOD]
    # The model is told what went wrong.
    reason = regenerate.call_args.args[-1]
    assert "no such column" in reason


@pytest.mark.unit
def test_missing_sql_is_retried(db_path) -> None:
    part, regenerate, _, _ = _run(db_path, "", GOOD)
    assert regenerate.call_count == 1
    assert part.status == "ok" and part.corrected


@pytest.mark.unit
def test_unexpected_empty_result_is_retried(db_path) -> None:
    part, regenerate, _, _ = _run(db_path, "SELECT customer_name FROM sales_data WHERE revenue < 0", GOOD)
    assert regenerate.call_count == 1
    assert part.status == "ok" and part.corrected


@pytest.mark.unit
def test_a_refused_query_is_never_retried(db_path) -> None:
    part, regenerate, _, _ = _run(db_path, "SELECT name FROM sqlite_master", GOOD)
    assert part.status == "blocked"
    regenerate.assert_not_called()


@pytest.mark.unit
def test_an_empty_existence_check_is_a_real_answer(db_path) -> None:
    sql = "SELECT DISTINCT customer_name FROM sales_data WHERE LOWER(customer_name) LIKE '%teapots%'"
    part, regenerate, _, _ = _run(db_path, sql, GOOD)
    assert part.status == "empty"
    regenerate.assert_not_called()


@pytest.mark.unit
def test_a_retry_that_also_finds_nothing_keeps_the_original(db_path) -> None:
    first = "SELECT customer_name FROM sales_data WHERE revenue < 0"
    part, regenerate, _, _ = _run(db_path, first, "SELECT customer_name FROM sales_data WHERE revenue < -1")
    assert regenerate.call_count == 1
    assert part.sql == first
    assert part.corrected is False


@pytest.mark.unit
def test_a_retry_that_fails_keeps_the_original(db_path) -> None:
    part, _, _, _ = _run(db_path, "SELECT nope FROM sales_data", "SELECT still_nope FROM sales_data")
    assert part.status == "sql_error"
    assert part.sql == "SELECT nope FROM sales_data"
    assert part.corrected is False


@pytest.mark.unit
def test_the_database_error_is_never_sent_to_the_browser(db_path) -> None:
    part, _, _, _ = _run(db_path, "SELECT nope FROM sales_data", "")
    assert part.error and "nope" in part.error
    assert "error" not in part.model_dump()


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_grounded_summary_is_shown(db_path) -> None:
    part, _, summarise, trace = _run(db_path, GOOD)
    assert part.summary == "Beta Ltd leads with £2,500.50."
    assert trace["summary"] == "used"
    assert format_legacy(Turn(kind="data", parts=[part])).startswith("Beta Ltd leads with £2,500.50.\n\n")


@pytest.mark.unit
def test_a_summary_with_an_invented_figure_is_dropped(db_path) -> None:
    part, _, _, trace = _run(db_path, GOOD, summary="Beta Ltd leads by 42% with £9,999.00.")
    assert part.summary is None
    assert trace["summary"] == "dropped"
    assert part.status == "ok" and len(part.rows) == 3


@pytest.mark.unit
def test_a_failed_summary_still_returns_the_table(db_path) -> None:
    part, _, summarise, trace = _run(db_path, GOOD, summary_error=RuntimeError("watsonx down"))
    summarise.assert_called_once()
    assert trace["summary"] == "failed"
    assert part.summary is None
    assert part.status == "ok" and len(part.rows) == 3


@pytest.mark.unit
def test_a_single_value_gets_no_summary_call(db_path) -> None:
    _, _, summarise, _ = _run(db_path, "SELECT SUM(revenue) FROM sales_data")
    summarise.assert_not_called()


@pytest.mark.unit
def test_grounding_allows_figures_from_the_rows_question_and_count() -> None:
    rows = [["Beta Ltd", "£2,500.50"], ["Acme Ltd", "£1,000.00"]]
    assert is_grounded("Beta Ltd leads with £2,500.50, ahead of Acme Ltd.", "q", rows, 2)
    assert is_grounded("The top 2 partners in 2024 are shown.", "Top partners in 2024?", rows, 2)
    assert not is_grounded("Beta Ltd earned £2.5 million.", "q", rows, 2)
    assert not is_grounded("Beta Ltd is 150% ahead.", "q", rows, 2)


@pytest.mark.unit
def test_result_text_says_when_rows_are_missing() -> None:
    rows = [[f"P{i}", "1"] for i in range(15)]
    text = result_text(["name", "n"], rows, 15, False)
    assert "Showing the first 10 of 15 rows" in text
    assert "P10" not in text


@pytest.mark.unit
def test_a_capped_row_count_is_not_a_fact() -> None:
    rows = [[f"P{i}", "1"] for i in range(100)]
    assert not is_grounded("There are 100 partners.", "q", rows, 100)
    assert "full count is unknown" in result_text(["name", "n"], rows, 100, False)


@pytest.mark.unit
def test_a_list_of_names_gets_no_summary(db_path) -> None:
    _, _, summarise, _ = _run(db_path, "SELECT customer_name FROM sales_data")
    summarise.assert_not_called()


@pytest.mark.unit
def test_deal_lines_get_no_summary(tmp_path) -> None:
    path = tmp_path / "lines.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE sales_data (document_number TEXT, revenue REAL)")
    conn.executemany("INSERT INTO sales_data VALUES (?, ?)", [("D1", 10.0), ("D1", 20.0)])
    conn.commit()
    conn.close()
    _, _, summarise, _ = _run(str(path), "SELECT document_number, revenue FROM sales_data")
    summarise.assert_not_called()
