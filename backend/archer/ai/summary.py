"""
A sentence or two saying what a result table shows.

The model writes the summary; this module decides whether it may be shown.
A summary that states a figure the result does not contain is worse than no
summary - it reads as fact, beside a table that contradicts it - so every
number in it is checked against the rows the model was given. One that fails
is dropped, and the table is shown on its own.
"""

from __future__ import annotations

import re
from typing import Sequence

from .llm import complete
from .prompts import render_messages

# How much of a result the model sees. Enough to say who leads and by how
# much; the full table is on screen beneath the summary anyway.
SAMPLE_ROWS = 10
SAMPLE_CELL = 120
ROW_CAP = 100

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    """Every number in a piece of text, normalised: no commas, two decimals."""
    found = set()
    for token in _NUMBER.findall(text or ""):
        try:
            found.add(f"{float(token.replace(',', '')):.2f}")
        except ValueError:
            continue
    return found


def result_text(columns: Sequence[str], rows: Sequence[Sequence[str]], row_count: int, truncated: bool) -> str:
    """The sample of a result the model is shown, as plain text."""
    sample = rows[:SAMPLE_ROWS]
    lines = [f"Columns: {' | '.join(columns)}"]
    for row in sample:
        lines.append(" | ".join(str(cell)[:SAMPLE_CELL] for cell in row))
    if truncated or row_count >= ROW_CAP:
        # A result of exactly the cap may itself have been cut short by the
        # query's LIMIT, so the model is not told a total it cannot know.
        lines.append(f"(Showing the first {len(sample)} rows. The result was capped at {ROW_CAP}, "
                     "so the full count is unknown: do not state one.)")
    elif len(rows) > len(sample):
        lines.append(f"(Showing the first {len(sample)} of {row_count} rows.)")
    else:
        lines.append(f"({row_count} rows in total.)")
    return "\n".join(lines)


def is_grounded(summary: str, question: str, rows: Sequence[Sequence[str]], row_count: int) -> bool:
    """
    True when every number in the summary can be found in what the model saw.

    Allowed: any number in the sampled cells, any number in the question, the
    row count, and small whole numbers up to the sample size ("the top 3").
    """
    sample = rows[:SAMPLE_ROWS]
    allowed = _numbers(question)
    if row_count < ROW_CAP:
        # At the cap the true total is unknown, so the count is not a fact.
        allowed.add(f"{float(row_count):.2f}")
    allowed |= {f"{float(n):.2f}" for n in range(1, len(sample) + 1)}
    for row in sample:
        for cell in row:
            allowed |= _numbers(str(cell)[:SAMPLE_CELL])
    return _numbers(summary) <= allowed


def summarise(llm, question: str, columns: Sequence[str], rows: Sequence[Sequence[str]], row_count: int, truncated: bool) -> str:
    """Ask for a summary. The caller decides, with is_grounded(), whether to use it."""
    messages = render_messages(
        "summary",
        QUESTION=question,
        RESULT=result_text(columns, rows, row_count, truncated),
    )
    return complete(llm, messages)
