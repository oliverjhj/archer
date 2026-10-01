"""
Unit tests for the authenticated /api/ask proxy in archer.api.ask.

What this route exists to do
----------------------------
/ask is authenticated by the WEBHOOK_SECRET shared secret, which must never
reach browser code.  /api/ask is the browser-facing entry point: it is
authenticated by the archer_session session cookie instead, and calls the same
shared orchestration.  These tests exist to prove three things:

  1. the cookie is genuinely required, and a missing, malformed or expired one
     is rejected;
  2. a valid cookie gets an answer without the caller ever supplying, or
     needing to know, WEBHOOK_SECRET;
  3. /ask and /api/ask produce identical answers, because they share one code
     path rather than two that can drift apart.

Isolation strategy
------------------
Mirrors test_ask.py: a minimal FastAPI application containing only the ask
router is assembled here, so the real archer.app, its lifespan handler and
verify_database() are never touched.  Every external dependency is
patched at the name it is looked up under inside archer.api.ask.

No .env file, real sales.db, IBM Cloud, watsonx or network access is
required or permitted.
"""

import pytest

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import jwt as pyjwt

from fastapi import FastAPI
from starlette.testclient import TestClient
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

from archer.api import ask as ask_module
from archer.auth import jwt as jwt_module
from archer.core.limiter import limiter
from archer.ai.planner import Plan, PlannedPart

def _plan_as(kind):
    """A stand-in for the planner that keeps the question as typed."""
    def plan(_llm, question, _history=()):
        return Plan(kind=kind, parts=[PlannedPart(kind=kind, question=question)])
    return plan



# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_API_ASK_URL = "/api/ask"
_ASK_URL = "/ask"

# Must match the stub set in backend/tests/conftest.py
_VALID_API_KEY = "test-webhook-secret-stub-not-for-production"

_COOKIE_NAME = "archer_session"


# ---------------------------------------------------------------------------
# Module-level test app
# ---------------------------------------------------------------------------

def _build_test_app() -> FastAPI:
    """
    Minimal FastAPI application containing only the ask router.

    Deliberately does not register the archer.app 401 handler, so an
    unauthenticated request surfaces here as a plain 401 rather than the
    redirect-or-JSON behaviour that handler adds.  That handler is covered by
    the app-level tests instead.
    """
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(ask_module.router)
    return app


_test_app = _build_test_app()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client() -> TestClient:
    return TestClient(_test_app, raise_server_exceptions=False)


def _valid_token(username: str = "tester") -> str:
    """A correctly signed, unexpired token, produced by the real helper."""
    return jwt_module.create_jwt_token(username)


def _expired_token(username: str = "tester") -> str:
    """A correctly signed but expired token."""
    payload = {
        "sub": username,
        "exp": datetime.now(UTC) - timedelta(hours=1),
        "iat": datetime.now(UTC) - timedelta(hours=25),
    }
    return pyjwt.encode(payload, jwt_module.JWT_SECRET_KEY, algorithm=jwt_module.JWT_ALGORITHM)


def _post(client: TestClient, question: str, token: str | None = None):
    """POST to /api/ask, setting the session cookie only when one is given."""
    if token is not None:
        client.cookies.set(_COOKIE_NAME, token)
    else:
        client.cookies.clear()
    return client.post(_API_ASK_URL, json={"question": question})


def _chat_patches(answer: str):
    """Patch the chat path so no LLM, database or network is involved."""
    return (
        patch("archer.pipeline.create_llm", return_value=MagicMock()),
        patch("archer.pipeline.plan_message", side_effect=_plan_as("chat")),
        patch("archer.pipeline.generate_chat_response", return_value=answer),
    )


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_missing_cookie_returns_401() -> None:
    """No session cookie means no answer."""
    response = _post(_client(), "What was total revenue?")
    assert response.status_code == 401


@pytest.mark.unit
def test_malformed_cookie_returns_401() -> None:
    """A cookie that is not a JWT at all is rejected."""
    response = _post(_client(), "What was total revenue?", token="not-a-jwt")
    assert response.status_code == 401


@pytest.mark.unit
def test_expired_token_returns_401() -> None:
    """A correctly signed but expired token is rejected."""
    response = _post(_client(), "What was total revenue?", token=_expired_token())
    assert response.status_code == 401


@pytest.mark.unit
def test_token_signed_with_wrong_secret_returns_401() -> None:
    """A token signed with a different secret is rejected."""
    forged = pyjwt.encode(
        {
            "sub": "tester",
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "iat": datetime.now(UTC),
        },
        "a-different-secret-entirely",
        algorithm=jwt_module.JWT_ALGORITHM,
    )
    response = _post(_client(), "What was total revenue?", token=forged)
    assert response.status_code == 401


@pytest.mark.unit
def test_api_key_header_does_not_authenticate_api_ask() -> None:
    """
    The webhook secret must not be an alternative way in.

    /api/ask is cookie-authenticated only.  If the API key were also accepted
    here, a browser would have a reason to hold it, which is the exact thing
    this route exists to prevent.
    """
    client = _client()
    client.cookies.clear()
    response = client.post(
        _API_ASK_URL,
        json={"question": "What was total revenue?"},
        headers={"x-api-key": _VALID_API_KEY},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Authorised behaviour
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_valid_cookie_returns_answer_without_api_key() -> None:
    """A valid session cookie is sufficient; no API key is sent."""
    chat_answer = "I am Archer. Ask me about the sales data."
    p1, p2, p3 = _chat_patches(chat_answer)

    with p1, p2, p3:
        response = _post(_client(), "Hello", token=_valid_token())

    assert response.status_code == 200
    assert response.json()["answer"] == chat_answer


@pytest.mark.unit
def test_ask_and_api_ask_return_identical_answers() -> None:
    """
    Both routes share one orchestration function, so identical input must give
    identical output.  This is the regression guard against the two paths
    drifting apart.
    """
    chat_answer = "Both routes agree."
    question = "Tell me about the dataset"

    p1, p2, p3 = _chat_patches(chat_answer)
    with p1, p2, p3:
        client = _client()
        client.cookies.clear()
        webhook_response = client.post(
            _ASK_URL,
            json={"question": question},
            headers={"x-api-key": _VALID_API_KEY},
        )
        browser_response = _post(_client(), question, token=_valid_token())

    assert webhook_response.status_code == 200
    assert browser_response.status_code == 200
    assert webhook_response.json() == browser_response.json()


@pytest.mark.unit
def test_missing_question_returns_422() -> None:
    """Schema validation still applies behind the cookie check."""
    client = _client()
    client.cookies.set(_COOKIE_NAME, _valid_token())
    response = client.post(_API_ASK_URL, json={})
    assert response.status_code == 422


@pytest.mark.unit
def test_answer_question_is_the_shared_path() -> None:
    """
    Assert the structural property directly rather than only its symptoms: the
    route delegates to answer_question and does not carry its own copy of the
    orchestration.
    """
    with patch(
        "archer.api.ask.answer_question",
        return_value={"answer": "delegated"},
    ) as shared:
        response = _post(_client(), "anything", token=_valid_token())

    assert response.status_code == 200
    assert response.json()["answer"] == "delegated"
    shared.assert_awaited_once()


# ---------------------------------------------------------------------------
# History on the request
# ---------------------------------------------------------------------------


def _post_json(client: TestClient, body: dict, token: str):
    client.cookies.set(_COOKIE_NAME, token)
    return client.post(_API_ASK_URL, json=body)


@pytest.mark.unit
def test_history_is_accepted_and_both_routes_still_agree() -> None:
    history = [{"question": "Top customers?", "sql": "SELECT 1", "columns": ["a"], "rows": [["x"]], "answer": "ok"}]
    body = {"question": "and the second?", "history": history}

    p1, p2, p3 = _chat_patches("Context answer.")
    with p1, p2, p3:
        client = _client()
        client.cookies.clear()
        webhook = client.post(_ASK_URL, json=body, headers={"x-api-key": _VALID_API_KEY})
        browser = _post_json(_client(), body, _valid_token())

    assert browser.status_code == 200
    assert browser.json() == webhook.json()


@pytest.mark.unit
def test_too_much_history_is_rejected() -> None:
    body = {"question": "x", "history": [{"question": f"q{i}"} for i in range(7)]}
    assert _post_json(_client(), body, _valid_token()).status_code == 422


@pytest.mark.unit
def test_overlong_question_is_rejected() -> None:
    assert _post_json(_client(), {"question": "x" * 2001}, _valid_token()).status_code == 422
