import re
from datetime import datetime
from typing import Tuple

from ..db.database import dataset_date_range
from .llm import complete
from .prompts import render_messages

_FENCED = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_STATEMENT_START = re.compile(r"\b(SELECT|WITH)\b", re.IGNORECASE)


def extract_sql(text: str) -> str:
    """
    Pull one SQL statement out of a model reply.

    Chat models wrap SQL in fences, spread it over several lines and sometimes
    add a sentence either side, so this takes the first fenced block if there
    is one, starts at the first SELECT or WITH, and reads until the statement
    ends. It ends at the first semicolon, comment or backtick outside a quoted
    string: a ';' or '--' inside a literal such as 'Smith #1; Ltd' is part of
    the query, not the end of it.

    Returns "" when there is no SELECT or WITH statement to take. This is a
    tidying step, not the safety boundary: whatever it returns is executed
    only through archer.db.query.run_select, which the database engine itself
    restricts to reading sales_data.
    """
    fenced = _FENCED.search(text)
    candidate = fenced.group(1) if fenced else text

    start = _STATEMENT_START.search(candidate)
    if not start:
        return ""
    candidate = candidate[start.start():]

    quote = None
    end = len(candidate)
    index = 0
    while index < len(candidate):
        char = candidate[index]
        if quote:
            if char == quote:
                # A doubled quote is an escaped quote inside the literal.
                if index + 1 < len(candidate) and candidate[index + 1] == quote:
                    index += 2
                    continue
                quote = None
        elif char in ("'", '"'):
            quote = char
        elif char in (";", "`") or candidate.startswith(("--", "/*"), index):
            end = index
            break
        index += 1

    sql = candidate[:end].strip()
    return sql if _STATEMENT_START.match(sql) else ""


def _sql_messages(user_query: str, schema_text: str) -> list:
    return render_messages(
        "sql_generator",
        TODAY=datetime.today().strftime("%Y-%m-%d"),
        SCHEMA=schema_text,
        USER_QUERY=user_query,
    )


def regenerate_sql(
    llm, user_query: str, schema_text: str, failed_sql: str, problem: str
) -> Tuple[str, str]:
    """
    Ask once more after a query failed or found nothing.

    The model is shown its own failed query as its previous reply, then told
    what went wrong, so the correction is made in context rather than from
    scratch.

    Args:
        failed_sql: the query that failed ("" if there was none)
        problem: what went wrong, completing the sentence "That query ..."
    """
    date_from, date_to = dataset_date_range()
    messages = _sql_messages(user_query, schema_text)
    messages.append(("assistant", failed_sql or "(no query)"))
    messages += render_messages(
        "sql_retry",
        PROBLEM=problem,
        DATE_FROM=date_from or "the start of the data",
        DATE_TO=date_to or "the end of the data",
    )
    raw_reply = complete(llm, messages)
    return extract_sql(raw_reply), raw_reply


def generate_sql(llm, user_query: str, schema_text: str) -> Tuple[str, str]:
    """
    Generate SQL for a question.

    Args:
        llm: chat model client (see archer.ai.llm.create_llm)
        user_query: the question, as the user typed it
        schema_text: comma-separated list of column names

    Returns:
        (clean_sql, raw_reply): clean_sql is "" when the reply held no query.
    """
    raw_reply = complete(llm, _sql_messages(user_query, schema_text))
    return extract_sql(raw_reply), raw_reply
