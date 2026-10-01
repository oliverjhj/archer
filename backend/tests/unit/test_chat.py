"""
Unit tests for generate_chat_response() in archer.ai.chat.

These tests exercise the response-handling behaviour inside
generate_chat_response() without calling any real LLM, network service,
IBM Cloud, or watsonx.  The LLM argument is replaced with a MagicMock whose
.invoke() method returns a controlled string so that the post-invoke processing
can be verified in isolation.

Behaviour under test (chat.py):
  - the return value of llm.invoke() is stripped of leading/trailing whitespace;
  - the stripped value is returned directly to the caller;
  - internal whitespace (e.g. newlines) is preserved.
"""

import pytest
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage

from archer.ai.chat import generate_chat_response


def _mock_llm(response: str) -> MagicMock:
    """Return a MagicMock chat model whose .invoke() replies with the given text."""
    llm = MagicMock()
    llm.invoke.return_value = AIMessage(content=response)
    return llm


# ---------------------------------------------------------------------------
# Normal response handling
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_returns_llm_response() -> None:
    """A normal LLM response is returned unchanged."""
    result = generate_chat_response(_mock_llm("Hello from Archer."), "hi")
    assert result == "Hello from Archer."


@pytest.mark.unit
def test_strips_leading_and_trailing_whitespace() -> None:
    """Leading and trailing whitespace is stripped from the LLM response."""
    result = generate_chat_response(_mock_llm("  Hello from Archer.  "), "hi")
    assert result == "Hello from Archer."


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_empty_llm_response_returns_empty_string() -> None:
    """An empty LLM response produces an empty string."""
    result = generate_chat_response(_mock_llm(""), "hi")
    assert result == ""


@pytest.mark.unit
def test_multiline_response_preserves_internal_newlines() -> None:
    """Internal newlines in the LLM response are preserved after strip."""
    raw = "Line one.\nLine two."
    result = generate_chat_response(_mock_llm(raw), "tell me more")
    assert result == raw


# ---------------------------------------------------------------------------
# LLM invocation: called exactly once per generate_chat_response() call
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_llm_invoke_is_called_exactly_once() -> None:
    """llm.invoke() is called exactly once per generate_chat_response() call."""
    llm = _mock_llm("Hi.")
    generate_chat_response(llm, "hello")
    assert llm.invoke.call_count == 1
