"""
Unit tests for the /login GET and POST routes in archer.api.auth_routes.

Isolation strategy
------------------
A minimal FastAPI application is assembled containing only the auth router.
The real archer.app is never imported, so the lifespan event handler and
verify_database() are never triggered.

The login.html template is read from backend/templates/login.html via
BASE_DIR (backend/archer/core/paths.py), which resolves correctly when pytest
is run from the backend/ directory, as configured in pyproject.toml.

WEB_USERNAME and WEB_PASSWORD are injected per-test via a file-local fixture
that uses monkeypatch.setenv.  They are intentionally absent from the global
conftest.py so that other tests cannot accidentally rely on them.

CSRF_SECRET_KEY is stubbed by backend/tests/conftest.py via
os.environ.setdefault() before any module is imported, so generate_csrf_token()
produces tokens that validate_csrf_token() accepts.

No .env file, real sales.db, IBM Cloud, watsonx, or network access is
required or permitted.
"""

import pathlib

import pytest

from fastapi import FastAPI
from starlette.testclient import TestClient
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

from archer.api import auth_routes as auth_routes_module
from archer.auth.csrf import generate_csrf_token
from archer.core.limiter import limiter


# ---------------------------------------------------------------------------
# Minimal test application
# ---------------------------------------------------------------------------

def _build_test_app() -> FastAPI:
    """
    Build a minimal FastAPI application containing only the auth router.
    No lifespan, no static files, no archer.app side effects.
    """
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(auth_routes_module.router)
    return app


_test_app = _build_test_app()


# ---------------------------------------------------------------------------
# File-local fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def web_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Set WEB_USERNAME and WEB_PASSWORD environment variables for the duration
    of a single test.  These values are intentionally local to this file and
    must not be placed in the global conftest.py.
    """
    monkeypatch.setenv("WEB_USERNAME", "testuser")
    monkeypatch.setenv("WEB_PASSWORD", "testpass")


# ---------------------------------------------------------------------------
# GET /login
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_get_login_returns_200() -> None:
    """GET /login responds with HTTP 200."""
    client = TestClient(_test_app, raise_server_exceptions=False)
    response = client.get("/login")
    assert response.status_code == 200


@pytest.mark.unit
def test_get_login_carries_the_page_link_through_sign_in() -> None:
    """The login page adds the URL fragment to the form action, so a link to
    /#/how-it-was-built still lands there after signing in."""
    # Read from disk rather than requested: /login is rate limited, and an
    # extra request here would push later tests over the limit.
    template = pathlib.Path(__file__).parents[2] / "templates" / "login.html"
    html = template.read_text(encoding="utf-8")
    assert "form.setAttribute('action', '/login' + window.location.hash)" in html
    assert '<form action="/login" method="POST">' in html


@pytest.mark.unit
def test_get_login_sets_csrf_cookie() -> None:
    """GET /login sets a csrf_token cookie on the response."""
    client = TestClient(_test_app, raise_server_exceptions=False)
    response = client.get("/login")
    assert "csrf_token" in response.cookies


# ---------------------------------------------------------------------------
# POST /login — valid credentials
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_post_login_valid_credentials_redirects_and_sets_jwt(
    web_credentials: None,
) -> None:
    """
    POST /login with valid credentials and a valid CSRF token issues a 303
    redirect and sets the archer_session cookie.
    """
    # follow_redirects=False so the 303 response (and its Set-Cookie header)
    # is visible before any redirect is followed.
    client = TestClient(_test_app, raise_server_exceptions=False, follow_redirects=False)
    csrf = generate_csrf_token()
    response = client.post(
        "/login",
        data={"username": "testuser", "password": "testpass", "csrf_token": csrf},
    )
    assert response.status_code == 303
    assert "archer_session" in response.cookies


# ---------------------------------------------------------------------------
# POST /login — invalid credentials
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_post_login_invalid_password_does_not_set_jwt(
    web_credentials: None,
) -> None:
    """
    POST /login with an incorrect password does not set the archer_session cookie.
    The route re-renders the login page (HTTP 200) rather than redirecting.
    """
    client = TestClient(_test_app, raise_server_exceptions=False, follow_redirects=False)
    csrf = generate_csrf_token()
    response = client.post(
        "/login",
        data={"username": "testuser", "password": "wrongpassword", "csrf_token": csrf},
    )
    assert response.status_code == 200
    assert "archer_session" not in response.cookies

    # The error is announced, styled only by the stylesheet, and shown above
    # the fields rather than below the button.
    html = response.text
    assert '<div class="login-error" role="alert">' in html
    assert "login-error\" style=" not in html
    assert html.index("login-error") < html.index('id="username"')


# ---------------------------------------------------------------------------
# POST /login — CSRF rejection
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_post_login_tampered_csrf_is_rejected() -> None:
    """
    POST /login with a tampered CSRF token (corrupted signature segment) is
    rejected with HTTP 403 and does not set the archer_session cookie.
    """
    client = TestClient(_test_app, raise_server_exceptions=False, follow_redirects=False)
    csrf = generate_csrf_token()
    # URLSafeTimedSerializer tokens are dot-separated: payload.timestamp.signature.
    # Replacing the last segment with a known-invalid string guarantees BadSignature.
    parts = csrf.split(".")
    parts[-1] = "invalidsignatureXXXXXXXXXXXX"
    tampered = ".".join(parts)
    response = client.post(
        "/login",
        data={"username": "testuser", "password": "testpass", "csrf_token": tampered},
    )
    assert response.status_code == 403
    assert "archer_session" not in response.cookies


@pytest.mark.unit
def test_post_login_missing_csrf_returns_error() -> None:
    """
    POST /login without a csrf_token form field is rejected by FastAPI's
    form-field validation with HTTP 422 Unprocessable Entity and does not
    set the archer_session cookie.
    """
    client = TestClient(_test_app, raise_server_exceptions=False, follow_redirects=False)
    response = client.post(
        "/login",
        data={"username": "testuser", "password": "testpass"},
    )
    assert response.status_code == 422
    assert "archer_session" not in response.cookies
