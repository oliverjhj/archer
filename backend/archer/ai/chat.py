from functools import lru_cache
from typing import Sequence

from ..db.catalogue import COLUMN_DESCRIPTIONS, KNOWN_VALUES
from ..db.database import dataset_date_range
from .llm import complete
from .planner import conversation_text
from .prompts import render_messages

# Terms people use that map onto the data. Kept beside the column glossary so
# an explanation uses the same words as the guide in the React app.
_VOCABULARY = {
    "partner / customer": "the company that placed the order (customer_name)",
    "end user": "the organisation the partner sold on to (end_user_company_name)",
    "deal": "one invoice or credit, identified by document_number; it can have several lines",
    "line": "one row of the table: one product within a deal",
    "IBM SOFT / IBM SERV / IBM CCHW": "the item groups: software, services and converged hardware",
    "credit": "a refund or reversal; credit lines carry negative revenue and quantity",
}


@lru_cache(maxsize=1)
def glossary() -> str:
    """The dataset described in plain text: terms, columns and fixed values."""
    lines = ["Terms:"]
    lines += [f"- {term}: {meaning}" for term, meaning in _VOCABULARY.items()]
    lines.append("Columns of sales_data:")
    lines += [f"- {column}: {description}" for column, description in COLUMN_DESCRIPTIONS.items()]
    lines.append("Columns with a fixed set of values:")
    lines += [f"- {column}: {', '.join(values)}" for column, values in KNOWN_VALUES.items()]
    return "\n".join(lines)


def generate_chat_response(llm, user_query: str, history: Sequence = ()) -> str:
    """
    Reply to data-related conversation in the Archer persona.

    Args:
        llm: chat model client (see archer.ai.llm.create_llm)
        user_query: the message, as the planner restated it
        history: earlier exchanges (HistoryTurn items), for explanations

    Returns:
        str: the reply
    """
    date_from, date_to = dataset_date_range()
    messages = render_messages(
        "chat",
        DATE_FROM=date_from or "the start of the dataset",
        DATE_TO=date_to or "the most recent record",
        GLOSSARY=glossary(),
        CONVERSATION=conversation_text(user_query, history),
    )
    return complete(llm, messages)
