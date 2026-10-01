import re
import logging

from .llm import complete
from .prompts import render_messages


def classify_query(llm, user_query: str) -> str:
    """
    Classify a question as a database query (1) or general chat (2).

    Args:
        llm: chat model client (see archer.ai.llm.create_llm)
        user_query: the question, as the user typed it

    Returns:
        str: "1" for database query, "2" for general chat
    """
    raw_classification = complete(llm, render_messages("classifier", USER_QUERY=user_query))
    logging.info(f"AI Classification Output: {raw_classification}")

    match = re.search(r'[12]', raw_classification)
    route_decision = match.group(0) if match else "2"
    logging.info(f"Route Decision: {route_decision} ({'DATA QUERY' if route_decision == '1' else 'GENERAL CHAT'})")

    return route_decision
