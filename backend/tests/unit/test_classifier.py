"""
Unit tests for classify_query() in archer.ai.classifier.

These tests exercise the routing logic inside classify_query() without calling
any real LLM, network service, IBM Cloud, or watsonx.  The LLM argument is
replaced with a MagicMock whose .invoke() method returns a controlled string so
that the regex extraction and fallback logic can be verified in isolation.

Behaviour under test (classifier.py):
  - raw LLM output is stripped, then re.search(r'[12]', ...) is applied;
  - the first digit matching [12] determines the route ("1" or "2");
  - if no [12] digit is found the function falls back to "2".
"""

import pytest
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage

from archer.ai.classifier import classify_query


def _mock_llm(response: str) -> MagicMock:
    """Return a MagicMock chat model whose .invoke() replies with the given text."""
    llm = MagicMock()
    llm.invoke.return_value = AIMessage(content=response)
    return llm


# ---------------------------------------------------------------------------
# Direct digit responses
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_returns_one_for_database_route() -> None:
    """LLM returning "1" causes the function to return "1"."""
    result = classify_query(_mock_llm("1"), "show me all revenue")
    assert result == "1"


@pytest.mark.unit
def test_returns_two_for_chat_route() -> None:
    """LLM returning "2" causes the function to return "2"."""
    result = classify_query(_mock_llm("2"), "hello there")
    assert result == "2"


# ---------------------------------------------------------------------------
# Digit embedded in prose (regex extracts first [12] found)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_digit_one_embedded_in_prose_returns_one() -> None:
    """A "1" embedded in surrounding text is still extracted as route "1"."""
    result = classify_query(_mock_llm("Classification: 1"), "revenue this year")
    assert result == "1"


@pytest.mark.unit
def test_digit_two_embedded_in_prose_returns_two() -> None:
    """A "2" embedded in surrounding text is still extracted as route "2"."""
    result = classify_query(_mock_llm("Classification: 2"), "who are you")
    assert result == "2"


# ---------------------------------------------------------------------------
# Fallback behaviour: no [12] digit in response -> "2"
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_unexpected_response_falls_back_to_two() -> None:
    """A response containing no digit 1 or 2 falls back to route "2"."""
    result = classify_query(_mock_llm("banana"), "some question")
    assert result == "2"


@pytest.mark.unit
def test_empty_response_falls_back_to_two() -> None:
    """An empty LLM response falls back to route "2"."""
    result = classify_query(_mock_llm(""), "some question")
    assert result == "2"


@pytest.mark.unit
def test_whitespace_only_response_falls_back_to_two() -> None:
    """A whitespace-only LLM response falls back to route "2"."""
    result = classify_query(_mock_llm("   "), "some question")
    assert result == "2"


# ---------------------------------------------------------------------------
# LLM invocation: called exactly once per classify_query() call
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_llm_invoke_is_called_exactly_once() -> None:
    """llm.invoke() is called exactly once per classify_query() call."""
    llm = _mock_llm("1")
    classify_query(llm, "any question")
    assert llm.invoke.call_count == 1
