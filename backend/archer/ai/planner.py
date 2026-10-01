"""
The planner: what does the latest message need, and what does it mean?

One model call that sees the conversation and returns a small JSON plan: the
kind of reply (data, chat or off_topic) and the question restated so it
stands on its own. "How many deals did the second one do?" becomes "How many
deals did Aurora Harbour Partners PLC do?", which the SQL generator can answer
exactly as it answers any single question.

The plan is validated before anything acts on it. If the reply cannot be
parsed, the fallback is the behaviour before the planner existed: treat the
message as a data question, as typed.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Literal, Optional, Sequence

from pydantic import BaseModel, Field, ValidationError

from ..db.database import dataset_date_range
from .llm import complete
from .prompts import render_messages

# How many earlier exchanges the planner sees, and how many result rows of
# each. Enough to resolve "the second one" or "that partner"; small enough to
# keep every message cheap.
HISTORY_TURNS = 3
HISTORY_ROWS = 10

# Only the first part is acted on until multi-part messages are supported.
MAX_PARTS = 1


class PlannedPart(BaseModel):
    kind: Literal["data", "chat"]
    question: str = Field(min_length=1, max_length=1000)


class Plan(BaseModel):
    kind: Literal["data", "chat", "off_topic"]
    parts: list[PlannedPart] = Field(default_factory=list, max_length=10)
    # True when the plan is the fallback rather than the model's own.
    fallback: bool = False


def _row_text(row: Sequence) -> str:
    return " | ".join("" if cell is None else str(cell) for cell in row)


def format_history(history: Sequence) -> str:
    """
    Earlier exchanges as the plain text the prompts show the model.

    Each item is a HistoryTurn (see archer.pipeline). The heading tells the
    model the text is context, not instruction: it came from the browser, and
    nothing in it is trusted.
    """
    if not history:
        return "Earlier conversation: none."

    lines = ["Earlier conversation, oldest first:"]
    for number, item in enumerate(history[-HISTORY_TURNS:], start=1):
        lines.append(f"{number}. Question: {item.question}")
        if item.interpreted and item.interpreted != item.question:
            lines.append(f"   Interpreted as: {item.interpreted}")
        if item.sql:
            lines.append(f"   SQL: {item.sql}")
        if item.columns and item.rows:
            lines.append(f"   Result ({' | '.join(item.columns)}):")
            for index, row in enumerate(item.rows[:HISTORY_ROWS], start=1):
                lines.append(f"     {index}) {_row_text(row)}")
        elif item.answer:
            lines.append(f"   Answer: {item.answer}")
    return "\n".join(lines)


def conversation_text(question: str, history: Sequence) -> str:
    return f"{format_history(history)}\n\nLatest message: {question}"


_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def parse_plan(reply: str) -> Optional[Plan]:
    """
    Read a plan from the model's reply, tolerating fences and stray prose
    around the JSON. Returns None when there is no valid plan in it.
    """
    match = _JSON_OBJECT.search(reply or "")
    if not match:
        return None
    try:
        plan = Plan.model_validate(json.loads(match.group(0)))
    except (json.JSONDecodeError, ValidationError):
        return None
    plan.fallback = False

    # A data or chat plan must say what to answer.
    if plan.kind != "off_topic" and not plan.parts:
        return None
    plan.parts = plan.parts[:MAX_PARTS]
    return plan


def fallback_plan(question: str) -> Plan:
    return Plan(kind="data", parts=[PlannedPart(kind="data", question=question)], fallback=True)


def plan_message(llm, question: str, history: Sequence = ()) -> Plan:
    """Ask the model for a plan; fall back to a data question if it fails."""
    date_from, date_to = dataset_date_range()
    messages = render_messages(
        "planner",
        DATE_FROM=date_from or "the start of the dataset",
        DATE_TO=date_to or "the most recent record",
        CONVERSATION=conversation_text(question, history),
    )
    reply = complete(llm, messages)
    plan = parse_plan(reply)
    if plan is None:
        logging.warning("Planner reply was not a valid plan; falling back. Reply: %.200s", reply)
        return fallback_plan(question)
    logging.info("Plan: %s %s", plan.kind, [part.question for part in plan.parts])
    return plan
