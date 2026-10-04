"""
Unit tests for SecurityHeadersMiddleware in archer.core.security_headers.

Isolation strategy
------------------
A minimal FastAPI application is assembled with SecurityHeadersMiddleware
added and a single dummy GET /health route.  The real archer.app is never
imported.

Headers asserted by these tests are taken directly from the current
implementation in backend/archer/core/security_headers.py.  Any change to
the middleware's header values should be reflected here.

No .env file, real sales.db, IBM Cloud, COS, watsonx, or network access is
required or permitted.
"""

import pytest

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient

from archer.core.security_headers import SecurityHeadersMiddleware


# ---------------------------------------------------------------------------
# Minimal test application
# ---------------------------------------------------------------------------

def _build_test_app() -> FastAPI:
    """
    Build a minimal FastAPI application with SecurityHeadersMiddleware and a
    single /health endpoint.  No lifespan, no archer.app side effects.
    """
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"ok": True})

    @app.get("/static/style.css")
    async def stylesheet() -> JSONResponse:
        return JSONResponse({"ok": True})

    return app


_test_app = _build_test_app()
_client = TestClient(_test_app)


@pytest.mark.unit
def test_static_files_are_revalidated_on_every_visit() -> None:
    """The login stylesheet keeps its URL across deploys, so it is never
    reused from cache without checking for a newer version."""
    assert _client.get("/static/style.css").headers["Cache-Control"] == "no-cache"
    assert "Cache-Control" not in _client.get("/health").headers


# ---------------------------------------------------------------------------
# Header presence
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_security_headers_are_present() -> None:
    """
    All seven security headers added by SecurityHeadersMiddleware are present
    on a normal JSON response.
    """
    response = _client.get("/health")
    assert response.status_code == 200

    expected_header_names = [
        "x-content-type-options",
        "x-frame-options",
        "x-xss-protection",
        "strict-transport-security",
        "content-security-policy",
        "referrer-policy",
        "permissions-policy",
    ]
    for header in expected_header_names:
        assert header in response.headers, f"Missing security header: {header}"


# ---------------------------------------------------------------------------
# Header values
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_security_headers_have_expected_values() -> None:
    """
    Critical security headers carry the exact values defined in
    SecurityHeadersMiddleware.dispatch().
    """
    response = _client.get("/health")

    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["permissions-policy"] == "geolocation=(), microphone=(), camera=()"
