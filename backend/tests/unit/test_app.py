"""
Unit tests for full application assembly in archer.app.

Isolation strategy
------------------
archer.app calls load_dotenv() and configure_logging() at module level, and
mounts a StaticFiles directory.  To prevent any real .env file from being read
during tests, dotenv.load_dotenv is patched to a no-op before the module is
imported.

The module is imported once inside a session-scoped fixture.  All tests that
need the app object receive it via that fixture.

Route-registration tests use a TestClient context manager rather than
inspecting app.routes directly.  Direct inspection of app.routes is brittle
across environments because route objects may not be flattened onto the app
in a consistent order on all platforms.  HTTP smoke tests are more robust:
each test confirms that a specific endpoint is reachable and returns the
expected status code for a safe, unauthenticated or invalid request.

Tests that exercise the lifespan event handler also use TestClient, with
verify_database patched via patch.object() on the already-imported
module, so no real IBM COS credentials, network access, .env file, or
sales.db are ever required.

No .env file, real sales.db, IBM Cloud, COS, watsonx, or network access is
required or permitted.
"""

import pytest

from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from starlette.testclient import TestClient
from archer.ai.planner import Plan, PlannedPart

def _plan_as(kind):
    """A stand-in for the planner that keeps the question as typed."""
    def plan(_llm, question, _history=()):
        return Plan(kind=kind, parts=[PlannedPart(kind=kind, question=question)])
    return plan



# ---------------------------------------------------------------------------
# Module import helper
# ---------------------------------------------------------------------------

def _import_app_module():
    """
    Import archer.app with dotenv.load_dotenv patched to a no-op.

    Called once per session from the fixture below.  The patch is applied
    before the import so that even if the module was not previously cached,
    load_dotenv() never reads a real .env file.
    """
    with patch("dotenv.load_dotenv", return_value=None):
        import archer.app as _app_module  # noqa: PLC0415
    return _app_module


# ---------------------------------------------------------------------------
# Session fixture: imported app module
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def app_module():
    """
    Return the archer.app module, imported exactly once per test session
    with load_dotenv patched to a no-op.
    """
    return _import_app_module()


# ---------------------------------------------------------------------------
# 1. app is a FastAPI instance
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_app_is_fastapi_instance(app_module) -> None:
    """
    The archer.app module exposes an ``app`` attribute that is a FastAPI
    instance.  This confirms the module can be imported and assembled
    without real cloud credentials.
    """
    assert isinstance(app_module.app, FastAPI)


# ---------------------------------------------------------------------------
# 2. /ask route is reachable after mocked startup
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_ask_route_reachable_after_mocked_startup(app_module) -> None:
    """
    POST /ask without an API key is rejected by the authentication guard,
    which raises HTTP 401.  The full app's exception handler converts the
    401 into a 303 redirect to /login.  With follow_redirects=False the
    redirect is visible directly, confirming the /ask route is registered
    and that the authentication guard and exception handler are both active.
    """
    mock_dl = MagicMock(return_value=True)

    with patch.object(app_module, "verify_database", mock_dl):
        with TestClient(app_module.app, follow_redirects=False) as client:
            response = client.post("/ask", json={"question": "hello"})

    assert response.status_code == 303, (
        f"POST /ask returned unexpected status {response.status_code}"
    )


# ---------------------------------------------------------------------------
# 3. Auth router is mounted: GET /login returns 200
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_auth_router_mounted_after_mocked_startup(app_module) -> None:
    """
    GET /login returns HTTP 200, confirming the auth router is mounted on the
    full assembled application.

    GET /login is rate-limited at 5 per minute on a shared in-process slowapi
    MemoryStorage singleton.  To prevent this request from consuming one of the
    5 slots relied upon by test_auth_routes.py when both files are collected in
    the same pytest session, the storage counter is reset to zero immediately
    after the response is received, before the TestClient context exits.

    No assertion is made on the exact HTML content.
    """
    mock_dl = MagicMock(return_value=True)

    with patch.object(app_module, "verify_database", mock_dl):
        with TestClient(app_module.app) as client:
            response = client.get("/login")
            # Reset the counter inside the TestClient context so the hit
            # recorded by this request is cleared before the session ends.
            app_module.app.state.limiter._storage.reset()

    assert response.status_code == 200, (
        f"GET /login returned unexpected status {response.status_code}"
    )


# ---------------------------------------------------------------------------
# 4. POST /login route is reachable after mocked startup
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_login_post_route_reachable_after_mocked_startup(app_module) -> None:
    """
    POST /login with no form data returns a client-error status code (422
    from FastAPI's form-field validation), confirming the route is registered
    and reached by the full assembled application.

    No real WEB_USERNAME or WEB_PASSWORD is set; the test only verifies that
    the route exists and that a request reaches it.
    """
    mock_dl = MagicMock(return_value=True)

    with patch.object(app_module, "verify_database", mock_dl):
        with TestClient(app_module.app) as client:
            response = client.post("/login", data={})

    assert response.status_code == 422, (
        f"POST /login returned unexpected status {response.status_code}"
    )


# ---------------------------------------------------------------------------
# 5. /landing route is protected after mocked startup
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_app_shell_protected_after_mocked_startup(app_module) -> None:
    """
    GET / without a valid JWT cookie causes the JWT guard to raise HTTP 401,
    which the application converts into a 303 redirect to /login. With
    follow_redirects=False the redirect is visible directly, confirming the
    route is registered and that authentication is enforced by the fully
    assembled application.

    This targets / rather than the retired /landing: / is now the page that
    serves the React application, so it is the one that must stay protected.
    """
    mock_dl = MagicMock(return_value=True)

    with patch.object(app_module, "verify_database", mock_dl):
        with TestClient(app_module.app, follow_redirects=False) as client:
            response = client.get("/")

    assert response.status_code == 303, (
        f"GET / returned unexpected status {response.status_code}"
    )


# ---------------------------------------------------------------------------
# 6. SecurityHeadersMiddleware is present in user_middleware
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_security_headers_middleware_is_registered(app_module) -> None:
    """
    SecurityHeadersMiddleware appears in app.user_middleware.

    app.user_middleware is the list of middleware added via
    app.add_middleware() before the ASGI stack is built.  It is the stable,
    public attribute to inspect at assembly time.
    """
    from archer.core.security_headers import SecurityHeadersMiddleware  # noqa: PLC0415

    middleware_classes = [m.cls for m in app_module.app.user_middleware]
    assert SecurityHeadersMiddleware in middleware_classes, (
        "SecurityHeadersMiddleware not found in app.user_middleware"
    )


# ---------------------------------------------------------------------------
# 7. Lifespan calls mocked verify_database exactly once
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_lifespan_calls_verify_database_once(app_module) -> None:
    """
    When the application starts via a TestClient context manager,
    verify_database() is called exactly once during the lifespan
    startup phase.

    The COS function is patched on the archer.app module so no real IBM COS
    credentials or network access are used.
    """
    mock_dl = MagicMock(return_value=True)

    with patch.object(app_module, "verify_database", mock_dl):
        with TestClient(app_module.app):
            pass  # Lifespan runs on entry; we only need startup to complete.

    mock_dl.assert_called_once()


# ---------------------------------------------------------------------------
# 8. Lifespan raises RuntimeError when verify_database returns False
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_lifespan_raises_on_failed_cos_download(app_module) -> None:
    """
    When verify_database() returns False, the lifespan handler
    raises RuntimeError, preventing the application from accepting requests.

    This reflects current behaviour in archer.app: the startup code raises
    RuntimeError("Failed to download database from IBM Cloud Object Storage")
    when the download reports failure.
    """
    mock_dl = MagicMock(return_value=False)

    with patch.object(app_module, "verify_database", mock_dl):
        with pytest.raises(RuntimeError):
            with TestClient(app_module.app, raise_server_exceptions=True):
                pass  # pragma: no cover


# ---------------------------------------------------------------------------
# 9. Full app can serve a safe route after startup with COS mocked
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_full_app_serves_favicon_after_mocked_startup(app_module) -> None:
    """
    After a successful mocked lifespan startup, the full assembled application
    serves GET /favicon.ico with HTTP 200.

    /favicon.ico is used rather than /login because it carries no rate-limit
    decorator, so this test cannot exhaust the shared slowapi counter and
    cause interference with test_auth_routes.py when both files are collected
    in the same pytest session.

    This confirms that routers, static files, and exception handlers are wired
    correctly under a complete TestClient session, without real COS, watsonx,
    .env, or sales.db.
    """
    mock_dl = MagicMock(return_value=True)

    with patch.object(app_module, "verify_database", mock_dl):
        with TestClient(app_module.app) as client:
            response = client.get("/favicon.ico")

    assert response.status_code == 200, (
        f"GET /favicon.ico returned unexpected status {response.status_code}"
    )


@pytest.mark.unit
def test_api_ask_returns_json_401_not_a_redirect(app_module) -> None:
    """
    An unauthenticated POST to /api/ask must return a JSON 401.

    Page routes turn a 401 into a redirect to /login, which is right for a
    browser navigating to /landing but wrong for a fetch() call: the caller
    would receive an HTML login page where it expected data. This test pins
    the distinction, because it is the kind of behaviour that is easy to lose
    in a later refactor of the exception handler.
    """
    mock_dl = MagicMock(return_value=True)

    with patch.object(app_module, "verify_database", mock_dl):
        with TestClient(app_module.app, follow_redirects=False) as client:
            response = client.post("/api/ask", json={"question": "hello"})

    assert response.status_code == 401, (
        f"POST /api/ask returned {response.status_code}, expected a JSON 401"
    )
    assert response.headers["content-type"].startswith("application/json"), (
        "POST /api/ask must answer with JSON, never an HTML login page"
    )
    assert "detail" in response.json()


@pytest.mark.unit
def test_page_route_401_still_redirects(app_module) -> None:
    """
    The JSON-401 rule is scoped to /api/ paths only. Browser page routes keep
    the redirect-to-login behaviour they had before the proxy was added.
    """
    mock_dl = MagicMock(return_value=True)

    with patch.object(app_module, "verify_database", mock_dl):
        with TestClient(app_module.app, follow_redirects=False) as client:
            response = client.get("/")

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


@pytest.mark.unit
def test_api_ask_answers_with_valid_cookie_on_full_app(app_module) -> None:
    """
    End-to-end through the real assembled application rather than the minimal
    test app used in test_api_ask.py.

    This is the composition check: routers, middleware, the security headers,
    the rate limiter and the 401 handler are all in place, and a request
    carrying a valid session cookie still reaches the shared orchestration and
    comes back with an answer.

    A token is minted directly rather than by posting to /login, because
    /login carries a 5/minute rate limit shared across the whole test session
    and exhausting it here would make unrelated files fail.
    """
    from archer.auth.jwt import create_jwt_token

    mock_dl = MagicMock(return_value=True)
    expected = "Composition check answer."

    with patch.object(app_module, "verify_database", mock_dl), \
        patch("archer.pipeline.create_llm", return_value=MagicMock()), \
        patch("archer.pipeline.plan_message", side_effect=_plan_as("chat")), \
        patch("archer.pipeline.generate_chat_response", return_value=expected):
        with TestClient(app_module.app, follow_redirects=False) as client:
            client.cookies.set("archer_session", create_jwt_token("tester"))
            response = client.post("/api/ask", json={"question": "hello"})

    assert response.status_code == 200, (
        f"POST /api/ask on the full app returned {response.status_code}"
    )
    assert response.json()["answer"] == expected
