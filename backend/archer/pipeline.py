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
from .ai.llm import create_llm
from .ai.planner import plan_message
from .ai.sql_generator import generate_sql, regenerate_sql
from .ai.summary import is_grounded, summarise
from .db.database import database_path, schema_columns
from .db.query import QueryBlocked, run_select

TURN_VERSION = 1

# Self-correction and summaries can be switched off, which is how the
# evaluation suite measures what each one adds. Both are on in production.
SQL_RETRY = os.environ.get("ARCHER_SQL_RETRY", "1").strip() != "0"
SUMMARIES = os.environ.get("ARCHER_SUMMARIES", "1").strip() != "0"

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
# Fixed, not generated: an off-topic request costs one model call (the
# planner) rather than two, the reply is the same every time, and there is no
# free text for a jailbreak to work on.
DECLINE_MESSAGE = (
    "I can only help with the sales data: questions about revenue, deals, "
    "partners, end users and products, or about an answer I have already "
    "given. Try asking one of those."
)

# How much client-supplied history is used. Requests may carry more (the
# request model's limits are generous, to reject only abuse); this trims it
# to what the prompts need.
HISTORY_TURNS = 3
HISTORY_MAX_CHARS = 6000
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_SELECT_START = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)

PartType = Literal["data", "chat", "decline"]
DataStatus = Literal["ok", "empty", "no_sql", "blocked", "sql_error", "unavailable", "model_error"]
TurnKind = Literal["data", "chat", "decline", "error", "budget"]


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
    # Why a query failed, for the retry and the logs. Never sent to the
    # browser: database errors are not something a visitor should read.
    error: Optional[str] = Field(default=None, exclude=True)
    # Whether the raw result held any numbers. A summary is only worth
    # writing for figures; a list of names speaks for itself.
    has_numbers: bool = Field(default=False, exclude=True)


class Turn(BaseModel):
    version: int = TURN_VERSION
    kind: TurnKind
    interpreted_as: Optional[str] = None
    parts: list[Part]
    memory: Optional[HistoryTurn] = None
    # What happened along the way - SQL attempts, whether a summary was used
    # or dropped. For the logs and the evaluation suite; not sent anywhere.
    trace: dict = Field(default_factory=dict, exclude=True)


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


_EXISTENCE_CHECK = re.compile(r"\bDISTINCT\b[\s\S]*\bLIKE\b", re.IGNORECASE)


def _retry_reason(part: Part) -> Optional[str]:
    """
    Why a first attempt deserves a second, completing "That query ...", or
    None when it does not.

    Never after a refusal by the query guard: that is a safety decision, not a
    mistake to be talked round. And not after an empty existence check, where
    "no such partner" is the correct answer.
    """
    if part.status == "no_sql":
        return "contained no SQL."
    if part.status == "sql_error":
        return f"failed with this error: {(part.error or 'unknown error')[:300]}"
    if part.status == "empty" and not _EXISTENCE_CHECK.search(part.sql or ""):
        return "ran, but found no matching rows."
    return None


async def run_data_part(question: str, trace: Optional[dict] = None) -> Part:
    """
    Generate SQL for a question, run it, and describe the result.

    A query that fails, or finds nothing where something was expected, gets
    one corrected attempt. The correction is kept only if it does better: a
    retry can turn an error into an answer, but never an answer into an error.
    """
    trace = trace if trace is not None else {}
    db_path = database_path()
    if not os.path.exists(db_path):
        logging.error("Database file not found at %s - the image was built incorrectly", db_path)
        return Part(type="data", question=question, status="unavailable", text=UNAVAILABLE_MESSAGE)

    schema_text = ", ".join(schema_columns())
    try:
        sql, raw_reply = await _call_model(generate_sql, create_llm("sql"), question, schema_text)
    except ModelError:
        return Part(type="data", question=question, status="model_error", text=MODEL_ERROR_MESSAGE)

    part = await _describe(question, sql, raw_reply)
    trace["sql_attempts"] = [part.sql or ""]
    trace["first_status"] = part.status

    reason = _retry_reason(part) if SQL_RETRY else None
    if reason:
        trace["retry_reason"] = reason
        try:
            retry_sql, retry_reply = await _call_model(
                regenerate_sql, create_llm("sql"), question, schema_text, part.sql or "", reason
            )
        except ModelError:
            retry_sql = ""
        if retry_sql:
            retry = await _describe(question, retry_sql, retry_reply)
            trace["sql_attempts"].append(retry_sql)
            better = retry.status == "ok" or (retry.status == "empty" and part.status != "empty")
            if better:
                retry.corrected = True
                logging.info("SQL corrected on retry (%s): %s", reason[:80], retry_sql)
                part = retry

    if SUMMARIES and _worth_summarising(part):
        await _add_summary(part, trace)
    return part


def _worth_summarising(part: Part) -> bool:
    """
    Summaries are written for figures compared across rows: rankings and
    breakdowns. Not for a single value (already a sentence), a list of names
    (it speaks for itself), or deal lines - rows with a document_number,
    where the model has been seen to call one line of a deal "the biggest
    deal" and the next line "the second biggest".
    """
    return (
        part.status == "ok"
        and part.value is None
        and part.row_count > 1
        and part.has_numbers
        and "document_number" not in part.columns
    )


async def _describe(question: str, sql: str, raw_reply: str) -> Part:
    """Turn a generated query, or the lack of one, into a Part."""
    if not sql:
        return Part(
            type="data",
            question=question,
            status="no_sql",
            text=f"I couldn't generate a valid SQL query. (AI said: {raw_reply})",
        )
    return await asyncio.to_thread(execute_query, question, sql)


async def _add_summary(part: Part, trace: dict) -> None:
    """Add a summary to a result table, if the model writes one that checks out."""
    try:
        summary = await _call_model(
            summarise, create_llm("summary"), part.question, part.columns, part.rows,
            part.row_count, part.truncated,
        )
    except ModelError:
        trace["summary"] = "failed"
        return
    if summary and is_grounded(summary, part.question, part.rows, part.row_count):
        part.summary = summary
        trace["summary"] = "used"
    else:
        logging.warning("Summary dropped: a figure in it is not in the result. %.200s", summary)
        trace["summary"] = "dropped"


def execute_query(question: str, sql: str) -> Part:
    """
    Run SQL through the guarded executor and describe the result as a Part.

    Separate from generation so the evaluation suite can build a scripted
    conversation history from known queries, with no model involved.
    """
    part = Part(type="data", question=question, sql=sql)
    if not _SELECT_START.match(sql):
        logging.error("Non-SELECT query blocked: %s", sql)
        part.status, part.text = "blocked", BLOCKED_MESSAGE
        return part

    try:
        result = run_select(sql)
    except QueryBlocked as exc:
        logging.error("Query refused by the guard: %s | %s", exc, sql)
        part.status, part.text = "blocked", BLOCKED_MESSAGE
        return part
    except (sqlite3.Error, ValueError, KeyError, AttributeError) as exc:
        logging.error("CRITICAL DB ERROR: %s | SQL ATTEMPTED: %s", exc, sql)
        part.status, part.text, part.error = "sql_error", SQL_ERROR_MESSAGE, str(exc)
        return part

    rows = result.rows
    part.columns = result.columns
    part.truncated = result.truncated
    part.row_count = len(rows)
    part.has_numbers = any(_is_number(value) for row in rows for value in row)

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


async def run_chat_part(question: str, history: list[HistoryTurn]) -> Part:
    try:
        reply = await _call_model(generate_chat_response, create_llm("chat"), question, history)
    except ModelError:
        return Part(type="chat", question=question, status="model_error", text=MODEL_ERROR_MESSAGE)
    return Part(type="chat", question=question, text=reply)


def _clean(text: Optional[str], limit: int) -> Optional[str]:
    if text is None:
        return None
    return _clip(_CONTROL_CHARS.sub(" ", str(text)), limit)


def normalise_history(history: Optional[list[HistoryTurn]]) -> list[HistoryTurn]:
    """
    Trim client-supplied history to what the prompts use.

    History comes from the browser, so it is treated as untrusted text: it is
    cut to the last few exchanges and to the same row, column and length
    limits the server applied when it built each item, with control
    characters removed. It is only ever shown to the model as context. The SQL
    in it is never executed: only freshly generated SQL runs, through
    run_select.
    """
    items = []
    for item in (history or [])[-HISTORY_TURNS:]:
        items.append(
            HistoryTurn(
                question=_clean(item.question, 1000) or "",
                interpreted=_clean(item.interpreted, 1000),
                sql=_clean(item.sql, 4000),
                columns=[_clean(c, MEMORY_MAX_CELL) or "" for c in item.columns[:MEMORY_MAX_COLUMNS]],
                rows=[
                    [_clean("" if cell is None else cell, MEMORY_MAX_CELL) for cell in row[:MEMORY_MAX_COLUMNS]]
                    for row in item.rows[:MEMORY_MAX_ROWS]
                ],
                answer=_clean(item.answer, MEMORY_MAX_ANSWER),
            )
        )

    # Fit the budget by dropping the oldest exchanges first, then rows from
    # the latest - never the latest exchange itself, which is the one a
    # follow-up most often refers to.
    def size() -> int:
        return sum(len(item.model_dump_json()) for item in items)

    while len(items) > 1 and size() > HISTORY_MAX_CHARS:
        items.pop(0)
    while items and items[-1].rows and size() > HISTORY_MAX_CHARS:
        items[-1].rows.pop()
    return items


def _same_question(a: str, b: str) -> bool:
    """True when two questions differ only in case, spacing or punctuation."""
    def squash(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return squash(a) == squash(b)


async def run_turn(question: str, history: Optional[list[HistoryTurn]] = None) -> Turn:
    """
    Answer one message, in the context of the earlier exchanges in `history`.

    The planner decides what the message needs and restates it so it stands
    on its own; the restated question is what the SQL generator or the chat
    prompt receives, and it is shown to the user as "Interpreted as" whenever
    it differs from what they typed.
    """
    context = normalise_history(history)

    try:
        plan = await _call_model(plan_message, create_llm("planner"), question, context)
    except ModelError:
        part = Part(type="chat", question=question, status="model_error", text=MODEL_ERROR_MESSAGE)
        return Turn(kind="error", parts=[part])

    if plan.kind == "off_topic":
        turn = Turn(kind="decline", parts=[Part(type="decline", question=question, text=DECLINE_MESSAGE)])
        turn.memory = build_history_item(question, turn)
        return turn

    planned = plan.parts[0]
    if not context:
        # With no earlier exchange there is nothing to resolve, so a restated
        # question could only be a paraphrase ("partners" for "customers").
        # The question goes on exactly as typed, which keeps a conversation's
        # first question behaving as it did before the planner existed.
        planned = planned.model_copy(update={"question": question})
    trace: dict = {}
    part = await (
        run_data_part(planned.question, trace)
        if planned.kind == "data"
        else run_chat_part(planned.question, context)
    )

    kind: TurnKind = "error" if part.status in ("model_error", "unavailable") else part.type
    interpreted = None if _same_question(planned.question, question) else planned.question
    turn = Turn(kind=kind, interpreted_as=interpreted, parts=[part], trace=trace)
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
    if part.type != "data":
        answer = part.text
    elif part.value is not None:
        answer = f"{part.text} {part.value}"
    else:
        answer = part.summary or part.text
    return HistoryTurn(
        question=_clip(question, 1000),
        interpreted=_clip(turn.interpreted_as, 1000),
        sql=_clip(part.sql, 4000),
        columns=columns,
        rows=rows,
        answer=_clip(answer, MEMORY_MAX_ANSWER),
    )


def _legacy_part(part: Part) -> str:
    if part.type != "data" or part.status in ("no_sql", "blocked", "sql_error", "unavailable", "model_error"):
        return part.text or ""

    if part.status == "empty":
        return f"I couldn't find any data matching that request. \n\n*(Query attempted: {part.sql})*"

    if part.value is not None:
        return f"Based on the data, the answer is: **{part.value}** \n\n*(SQL used: {part.sql})*"

    lead = f"{part.summary}\n\n" if part.summary else ""
    table = f"| {' | '.join(part.columns)} |\n"
    table += f"|{'|'.join(['---'] * len(part.columns))}|\n"
    for row in part.rows:
        table += f"| {' | '.join(row)} |\n"
    note = f"\n\n*(Note: {TRUNCATION_NOTE})*" if part.truncated else ""
    return f"{lead}Here is the data you requested:\n\n{table}{note}\n*(SQL used: {part.sql})*"


def format_legacy(turn: Turn) -> str:
    """The Markdown answer string Archer has always returned."""
    return "\n\n".join(_legacy_part(part) for part in turn.parts)
