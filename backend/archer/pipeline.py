"""
Answering one message: the pipeline shared by the API and the evaluation suite.

run_turn() takes a question and returns a Turn - a structured record of what
Archer decided, what it ran and what came back - with no HTTP involved. The
API turns that into a response; the evaluation suite grades it directly, so
the two cannot drift apart.

Two renderings of a Turn leave this module:

  turn     the structured form the React app renders: parts, rows as display
           strings, the SQL, a status for every outcome
  answer   the Markdown string Archer has always returned, built by
           format_legacy(). Webhook callers of /ask depend on it, so for every
           outcome that existed before, it is unchanged.

Budget and authentication are the caller's job, not the pipeline's.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sqlite3
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from .ai.chat import generate_chat_response
from .ai.classifier import classify_query
from .ai.llm import create_llm
from .ai.sql_generator import generate_sql
from .db.database import database_path, schema_columns
from .db.query import QueryBlocked, run_select

TURN_VERSION = 1

# What a history item may carry back into a prompt. Kept small on purpose: it
# is resent with every question, and it is text the browser supplies.
MEMORY_MAX_ROWS = 10
MEMORY_MAX_COLUMNS = 8
MEMORY_MAX_CELL = 80
MEMORY_MAX_ANSWER = 300

TRUNCATION_NOTE = "Displaying the maximum of 100 rows to maintain performance."
SQL_ERROR_MESSAGE = (
    "I understood you need data, but I had trouble running that specific query "
    "against the database. Could you try rephrasing your question with slightly "
    "different terms?"
)
BLOCKED_MESSAGE = "I can only execute SELECT queries for security reasons."
UNAVAILABLE_MESSAGE = "Database temporarily unavailable. Please contact support."
MODEL_ERROR_MESSAGE = (
    "The language model did not respond. Please try again in a moment."
)

_SELECT_START = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)

PartType = Literal["data", "chat"]
DataStatus = Literal["ok", "empty", "no_sql", "blocked", "sql_error", "unavailable", "model_error"]
TurnKind = Literal["data", "chat", "error", "budget"]


class HistoryTurn(BaseModel):
    """One earlier exchange, as it is carried forward as context."""

    question: str = Field(max_length=1000)
    interpreted: Optional[str] = Field(default=None, max_length=1000)
    sql: Optional[str] = Field(default=None, max_length=4000)
    columns: list[str] = Field(default_factory=list, max_length=40)
    rows: list[list[Any]] = Field(default_factory=list, max_length=20)
    answer: Optional[str] = Field(default=None, max_length=2000)


class Part(BaseModel):
    """
    One answer within a turn. A data part carries the query and its result; a
    chat part carries text. `text` is always the sentence a person would read
    first, so a renderer never has to invent wording.
    """

    type: PartType
    question: str
    status: DataStatus = "ok"
    text: Optional[str] = None
    sql: Optional[str] = None
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    value: Optional[str] = None
    summary: Optional[str] = None
    corrected: bool = False


class Turn(BaseModel):
    version: int = TURN_VERSION
    kind: TurnKind
    interpreted_as: Optional[str] = None
    parts: list[Part]
    memory: Optional[HistoryTurn] = None


class ModelError(Exception):
    """A model call failed: the service was unreachable, refused or timed out."""


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _plain_number(value: float) -> str:
    return f"{int(value):,}" if value == int(value) else f"{value:,.2f}"


def format_cell(column: str, value: Any) -> str:
    """A table cell as displayed: pounds for revenue, whole numbers for quantity."""
    name = column.lower()
    if _is_number(value):
        if "revenue" in name:
            return f"£{value:,.2f}"
        if "quantity" in name:
            return f"{int(value):,}"
        return _plain_number(value)
    return str(value).replace("\n", ", ").replace("\r", "")


def format_scalar(column: str, value: Any) -> str:
    """A single-value answer as displayed."""
    if _is_number(value):
        return f"£{value:,.2f}" if "revenue" in column.lower() else _plain_number(value)
    return str(value)


# ---------------------------------------------------------------------------
# Running a turn
# ---------------------------------------------------------------------------


async def _call_model(function, *args):
    """
    Run a synchronous model call in a worker thread.

    The watsonx SDK is synchronous; calling it from an async handler would block
    the event loop for the whole round trip. Any failure is reported as a
    ModelError, so an outage becomes an answer rather than a 500.
    """
    try:
        return await asyncio.to_thread(function, *args)
    except Exception as exc:  # noqa: BLE001 - the SDK raises many unrelated types
        logging.error("Model call failed: %s: %s", type(exc).__name__, exc)
        raise ModelError(str(exc)) from exc


async def run_data_part(question: str) -> Part:
    """Generate SQL for a question, run it, and describe the result."""
    part = Part(type="data", question=question)

    db_path = database_path()
    if not os.path.exists(db_path):
        logging.error("Database file not found at %s - the image was built incorrectly", db_path)
        part.status, part.text = "unavailable", UNAVAILABLE_MESSAGE
        return part

    try:
        sql, raw_reply = await _call_model(
            generate_sql, create_llm("sql"), question, ", ".join(schema_columns())
        )
    except ModelError:
        part.status, part.text = "model_error", MODEL_ERROR_MESSAGE
        return part

    if not sql:
        part.status = "no_sql"
        part.text = f"I couldn't generate a valid SQL query. (AI said: {raw_reply})"
        return part

    part.sql = sql
    if not _SELECT_START.match(sql):
        logging.error("Non-SELECT query blocked: %s", sql)
        part.status, part.text = "blocked", BLOCKED_MESSAGE
        return part

    try:
        result = await asyncio.to_thread(run_select, sql)
    except QueryBlocked as exc:
        logging.error("Query refused by the guard: %s | %s", exc, sql)
        part.status, part.text = "blocked", BLOCKED_MESSAGE
        return part
    except (sqlite3.Error, ValueError, KeyError, AttributeError) as exc:
        logging.error("CRITICAL DB ERROR: %s | SQL ATTEMPTED: %s", exc, sql)
        part.status, part.text = "sql_error", SQL_ERROR_MESSAGE
        return part

    rows = result.rows
    part.columns = result.columns
    part.truncated = result.truncated
    part.row_count = len(rows)

    # SUM() over no matching rows returns one row holding NULL. That is an
    # empty result, not an answer of "None".
    if not rows or (len(rows) == 1 and len(rows[0]) == 1 and rows[0][0] is None):
        part.status = "empty"
        part.row_count = 0
        part.text = "I couldn't find any data matching that request."
        return part

    if len(rows) == 1 and len(rows[0]) == 1:
        part.value = format_scalar(result.columns[0], rows[0][0])
        part.rows = [[part.value]]
        part.text = "Based on the data, the answer is:"
    else:
        part.rows = [
            [format_cell(column, value) for column, value in zip(result.columns, row)]
            for row in rows
        ]
        part.text = "Here is the data you requested:"
    return part


async def run_chat_part(question: str) -> Part:
    try:
        reply = await _call_model(generate_chat_response, create_llm("chat"), question)
    except ModelError:
        return Part(type="chat", question=question, status="model_error", text=MODEL_ERROR_MESSAGE)
    return Part(type="chat", question=question, text=reply)


async def run_turn(question: str, history: Optional[list[HistoryTurn]] = None) -> Turn:
    """
    Answer one message.

    `history` is accepted now and used from the planner onwards; this version
    routes each question on its own, exactly as before.
    """
    try:
        route = await _call_model(classify_query, create_llm("classifier"), question)
    except ModelError:
        part = Part(type="chat", question=question, status="model_error", text=MODEL_ERROR_MESSAGE)
        return Turn(kind="error", parts=[part])

    part = await (run_data_part(question) if route == "1" else run_chat_part(question))
    kind: TurnKind = "error" if part.status in ("model_error", "unavailable") else part.type
    turn = Turn(kind=kind, parts=[part])
    turn.memory = build_history_item(question, turn)
    return turn


def budget_turn(question: str, message: str) -> Turn:
    """The turn returned when the daily question budget is spent."""
    return Turn(kind="budget", parts=[Part(type="chat", question=question, text=message)])


# ---------------------------------------------------------------------------
# History and the legacy answer
# ---------------------------------------------------------------------------


def _clip(text: Optional[str], limit: int) -> Optional[str]:
    if text is None:
        return None
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_history_item(question: str, turn: Turn) -> HistoryTurn:
    """
    What this exchange contributes as context to later questions.

    Built by the server, stored by the browser and sent back verbatim, so the
    limits on what history may hold are decided here, once.
    """
    part = turn.parts[0]
    columns = part.columns[:MEMORY_MAX_COLUMNS]
    rows = [
        [_clip(cell, MEMORY_MAX_CELL) for cell in row[:MEMORY_MAX_COLUMNS]]
        for row in part.rows[:MEMORY_MAX_ROWS]
    ]
    answer = part.text if part.type == "chat" else (
        f"{part.text} {part.value}" if part.value is not None else part.text
    )
    return HistoryTurn(
        question=_clip(question, 1000),
        interpreted=_clip(turn.interpreted_as, 1000),
        sql=_clip(part.sql, 4000),
        columns=columns,
        rows=rows,
        answer=_clip(answer, MEMORY_MAX_ANSWER),
    )


def _legacy_part(part: Part) -> str:
    if part.type == "chat" or part.status in ("no_sql", "blocked", "sql_error", "unavailable", "model_error"):
        return part.text or ""

    if part.status == "empty":
        return f"I couldn't find any data matching that request. \n\n*(Query attempted: {part.sql})*"

    if part.value is not None:
        return f"Based on the data, the answer is: **{part.value}** \n\n*(SQL used: {part.sql})*"

    table = f"| {' | '.join(part.columns)} |\n"
    table += f"|{'|'.join(['---'] * len(part.columns))}|\n"
    for row in part.rows:
        table += f"| {' | '.join(row)} |\n"
    note = f"\n\n*(Note: {TRUNCATION_NOTE})*" if part.truncated else ""
    return f"Here is the data you requested:\n\n{table}{note}\n*(SQL used: {part.sql})*"


def format_legacy(turn: Turn) -> str:
    """The Markdown answer string Archer has always returned."""
    return "\n\n".join(_legacy_part(part) for part in turn.parts)
