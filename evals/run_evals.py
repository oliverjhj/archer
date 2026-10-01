#!/usr/bin/env python3
"""
Evaluate the Archer text-to-SQL pipeline against a fixed set of cases.

Why this exists
---------------
The v2.6.0 changelog claimed "96-97% accuracy maintained" after a model
migration. Nothing substantiated it. This measures the claim instead of
repeating it, and the number it produces is the one that gets published -
whichever way it comes out.

How grading works
-----------------
SQL is graded by **execution**, not by string comparison. Both the reference
query and the generated query run against the same database and their result
sets are compared. A query that reaches the right answer by different means is
correct, which is what anyone actually means by accuracy; string matching would
fail perfectly good SQL.

Two levels are reported, because the difference between them is informative:

  exact match      the result sets are identical
  value match      every value in the reference result appears in the
                   generated result

A query that returns the right numbers alongside extra columns fails the first
and passes the second. That is a real distinction: it is not wrong, but it is
not what was asked for either.

Routing is graded separately. Sending a greeting to the SQL generator wastes a
call and produces nonsense, so the classifier is measured on its own.

The suite runs the application's own code, not a copy of it: each case goes
through archer.pipeline.run_turn, the function the API calls, so models,
prompts and the guarded SQL executor are exactly what the demo uses. Token usage
and the version of each prompt are recorded with every run, so a change in
accuracy or cost can be traced to the change that caused it.

Usage
-----
    python evals/run_evals.py
    python evals/run_evals.py --model meta-llama/llama-3-3-70b-instruct
    python evals/run_evals.py --cases evals/cases.yaml --output results.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import statistics
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

import yaml  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from langchain_core.callbacks import get_usage_metadata_callback  # noqa: E402

from archer.ai.llm import DEFAULT_MODEL_ID  # noqa: E402
from archer.ai.prompts import prompt_meta  # noqa: E402
from archer.db import database  # noqa: E402
from archer.db.query import run_select  # noqa: E402
from archer.pipeline import run_turn  # noqa: E402

PROMPTS = ("classifier", "sql_generator", "chat")


def run_generated(sql: str, database: str) -> tuple[list[tuple] | None, str | None]:
    """Execute generated SQL exactly as the application does. Returns (rows, error)."""
    try:
        return run_select(sql, max_rows=200, db_path=database).rows, None
    except sqlite3.Error as exc:
        return None, f"{type(exc).__name__}: {exc}"


def run_reference(conn: sqlite3.Connection, sql: str) -> tuple[list[tuple] | None, str | None]:
    """Execute a reference query, which is trusted, on a plain read-only connection."""
    try:
        return conn.execute(sql).fetchmany(200), None
    except sqlite3.Error as exc:
        return None, f"{type(exc).__name__}: {exc}"


def normalise_cell(value: Any) -> Any:
    """
    Make values comparable across queries that compute the same thing.

    Floats are rounded because SUM() over the same rows in a different order
    can differ in the last bits, and that is not a difference anyone cares
    about. Strings are stripped and case-folded.
    """
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, str):
        return value.strip().casefold()
    return value


def normalise_rows(rows: list[tuple], ordered: bool) -> list[tuple]:
    normalised = [tuple(normalise_cell(cell) for cell in row) for row in rows]
    return normalised if ordered else sorted(normalised, key=repr)


def value_multiset(rows: list[tuple]) -> set:
    """Every scalar value in a result, ignoring shape."""
    return {normalise_cell(cell) for row in rows for cell in row}


def grade_case(case: dict, conn: sqlite3.Connection, database: str) -> dict:
    """Run one case through the application's pipeline and grade the turn."""
    result: dict[str, Any] = {
        "id": case["id"],
        "category": case.get("category", "uncategorised"),
        "question": case["question"],
        "expected_route": case["route"],
    }

    started = time.monotonic()
    turn = asyncio.run(run_turn(case["question"]))
    result["seconds"] = round(time.monotonic() - started, 2)

    part = turn.parts[0]
    if part.status == "model_error":
        result.update(route="error", route_correct=False, error="model call failed")
        return result

    route = part.type
    result["route"] = route
    result["route_correct"] = route == case["route"]

    # Conversational cases are graded on routing alone: there is no SQL, and
    # the point is that they never reach the SQL generator.
    if case["route"] == "chat":
        return result

    if route != "data":
        # Misrouted. No SQL was generated, so it cannot be correct.
        result.update(sql_valid=False, exact_match=False, value_match=False)
        return result

    generated_sql = part.sql or ""
    result["generated_sql"] = generated_sql
    result["status"] = part.status

    if not generated_sql:
        result.update(sql_valid=False, exact_match=False, value_match=False, error="no SQL produced")
        return result

    # The pipeline has already run this query; it runs again here for the raw
    # values, because the turn holds display strings (£ signs, commas) that
    # cannot be compared with the reference result.
    actual_rows, actual_error = run_generated(generated_sql, database)
    if actual_error is not None:
        result.update(sql_valid=False, exact_match=False, value_match=False, error=actual_error)
        return result

    result["sql_valid"] = True

    expected_rows, expected_error = run_reference(conn, case["expected_sql"])
    if expected_error is not None:
        # The reference query is wrong, not the model. Say so loudly rather
        # than silently scoring the model against a broken baseline.
        result.update(exact_match=False, value_match=False, error=f"REFERENCE SQL FAILED: {expected_error}")
        return result

    ordered = bool(case.get("ordered", False))
    result["exact_match"] = normalise_rows(actual_rows, ordered) == normalise_rows(expected_rows, ordered)
    result["value_match"] = value_multiset(expected_rows).issubset(value_multiset(actual_rows))
    return result


def summarise(results: list[dict]) -> dict:
    """Aggregate the per-case records into the numbers that get published."""
    data_cases = [r for r in results if r["expected_route"] == "data"]
    chat_cases = [r for r in results if r["expected_route"] == "chat"]

    def pct(numerator: int, denominator: int) -> float:
        return round(100.0 * numerator / denominator, 1) if denominator else 0.0

    routed = sum(1 for r in results if r.get("route_correct"))
    valid = sum(1 for r in data_cases if r.get("sql_valid"))
    exact = sum(1 for r in data_cases if r.get("exact_match"))
    value = sum(1 for r in data_cases if r.get("value_match"))

    by_category: dict[str, dict] = {}
    for record in data_cases:
        bucket = by_category.setdefault(record["category"], {"total": 0, "exact": 0})
        bucket["total"] += 1
        bucket["exact"] += 1 if record.get("exact_match") else 0
    for name, bucket in by_category.items():
        bucket["accuracy"] = pct(bucket["exact"], bucket["total"])

    latencies = [r["seconds"] for r in results if "seconds" in r]
    input_tokens = [r["input_tokens"] for r in results if "input_tokens" in r]

    return {
        "cases_total": len(results),
        "cases_data": len(data_cases),
        "cases_chat": len(chat_cases),
        "routing_accuracy": pct(routed, len(results)),
        "sql_valid_rate": pct(valid, len(data_cases)),
        "execution_accuracy": pct(exact, len(data_cases)),
        "value_accuracy": pct(value, len(data_cases)),
        "median_seconds": round(statistics.median(latencies), 2) if latencies else 0.0,
        "total_input_tokens": sum(input_tokens),
        "total_output_tokens": sum(r.get("output_tokens", 0) for r in results),
        "median_input_tokens_data": (
            statistics.median([r["input_tokens"] for r in data_cases if "input_tokens" in r])
            if data_cases
            else 0
        ),
        "by_category": by_category,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the Archer text-to-SQL pipeline.")
    parser.add_argument("--model", default=DEFAULT_MODEL_ID, help="watsonx model id to evaluate.")
    parser.add_argument("--cases", default=str(Path(__file__).parent / "cases.yaml"))
    parser.add_argument("--database", default=str(REPO_ROOT / "sales.db"))
    parser.add_argument("--output", default=None, help="Write the full JSON record here.")
    parser.add_argument("--only", default=None, help="Run a single case by id.")
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    if not os.environ.get("IBM_API_KEY") or not os.environ.get("PROJECT_ID"):
        print("IBM_API_KEY and PROJECT_ID must be set (see .env.example).", file=sys.stderr)
        return 2

    cases = yaml.safe_load(Path(args.cases).read_text(encoding="utf-8"))
    if args.only:
        cases = [c for c in cases if c["id"] == args.only]

    conn = sqlite3.connect(f"file:{args.database}?mode=ro", uri=True)

    # The pipeline resolves its model and database the way the application
    # does, from the environment and the configured path, so the suite points
    # those at what it was asked to measure.
    os.environ["WATSONX_MODEL_ID"] = args.model
    database.DB_FILENAME = args.database
    prompt_versions = {name: prompt_meta(name).get("version", "?") for name in PROMPTS}

    print(f"model: {args.model}")
    print(f"prompts: {prompt_versions}")
    print(f"cases: {len(cases)}\n")

    results = []
    for index, case in enumerate(cases, start=1):
        with get_usage_metadata_callback() as usage:
            record = grade_case(case, conn, args.database)
        record["input_tokens"] = sum(u.get("input_tokens", 0) for u in usage.usage_metadata.values())
        record["output_tokens"] = sum(u.get("output_tokens", 0) for u in usage.usage_metadata.values())
        results.append(record)

        if case["route"] == "chat":
            mark = "PASS" if record.get("route_correct") else "FAIL"
            detail = f"routed {record.get('route')}"
        else:
            mark = "PASS" if record.get("exact_match") else "FAIL"
            if record.get("exact_match"):
                detail = "exact"
            elif record.get("value_match"):
                detail = "values correct, shape differs"
            elif record.get("error"):
                detail = record["error"][:60]
            else:
                detail = "wrong result"
        print(f"[{index:>2}/{len(cases)}] {mark}  {case['id']:<32} {detail}")

    conn.close()

    summary = summarise(results)
    print("\n" + "=" * 62)
    print(f"Routing accuracy    {summary['routing_accuracy']}%  ({summary['cases_total']} cases)")
    print(f"Valid SQL rate      {summary['sql_valid_rate']}%  ({summary['cases_data']} data cases)")
    print(f"Execution accuracy  {summary['execution_accuracy']}%")
    print(f"Value accuracy      {summary['value_accuracy']}%")
    print(f"Median latency      {summary['median_seconds']}s")
    print(f"Tokens              {summary['total_input_tokens']:,} in, {summary['total_output_tokens']:,} out")
    print("=" * 62)
    for name, bucket in sorted(summary["by_category"].items()):
        print(f"  {name:<14} {bucket['accuracy']:>5}%  ({bucket['exact']}/{bucket['total']})")

    if args.output:
        Path(args.output).write_text(
            json.dumps(
                {"model": args.model, "prompts": prompt_versions, "summary": summary, "results": results},
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nWrote {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
