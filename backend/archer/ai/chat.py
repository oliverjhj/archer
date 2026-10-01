from ..db.database import dataset_date_range
from .llm import complete
from .prompts import render_messages


def generate_chat_response(llm, user_query: str) -> str:
    """
    Generate a conversational reply in the Archer persona.

    Args:
        llm: chat model client (see archer.ai.llm.create_llm)
        user_query: the question, as the user typed it

    Returns:
        str: the reply
    """
    date_from, date_to = dataset_date_range()
    messages = render_messages(
        "chat",
        USER_QUERY=user_query,
        DATE_FROM=date_from or "the start of the dataset",
        DATE_TO=date_to or "the most recent record",
    )
    return complete(llm, messages)
