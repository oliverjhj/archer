"""
Unit tests for GET /api/schema.

The route exists so a visitor can see what they are allowed to ask about. It
reads the column list from the database rather than from a constant, so these
tests point it at a small temporary database and assert it reports what is
actually there - a hardcoded list would pass a test and still be wrong.

Isolation follows the rest of the suite: a minimal FastAPI application holding
only this router, no real dataset, no network.
"""

import importlib.util
import os
import re
import sqlite3
import tempfile
from pathlib import Path

import pytest

from unittest.mock import patch

from fastapi import FastAPI
from starlette.testclient import TestClient
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

from archer.api import schema_routes
from archer.auth.jwt import create_jwt_token
from archer.core.limiter import limiter

_COOKIE_NAME = "archer_session"
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(schema_routes.router)
    return app


_test_app = _build_test_app()


def _make_temp_db() -> str:
    """A minimal sales_data table with two known rows."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE sales_data (customer_name TEXT, document_date TEXT, revenue REAL)"
    )
    conn.executemany(
        "INSERT INTO sales_data VALUES (?, ?, ?)",
        [("Acme Ltd", "2020-01-01", 10.0), ("Beta Ltd", "2026-03-17", 20.0)],
    )
    conn.commit()
    conn.close()
    return path


def _client(token: str | None = None) -> TestClient:
    client = TestClient(_test_app, raise_server_exceptions=False)
    client.follow_redirects = False
    if token is not None:
        client.cookies.set(_COOKIE_NAME, token)
    return client


@pytest.mark.unit
def test_schema_requires_authentication() -> None:
    """
    The schema describes the dataset behind the login wall, so it sits behind
    the same wall. It is not secret, but an unauthenticated endpoint is one
    more thing to reason about for no benefit.
    """
    assert _client().get("/api/schema").status_code == 401


@pytest.mark.unit
def test_schema_reports_what_is_actually_in_the_database() -> None:
    path = _make_temp_db()
    try:
        with patch("archer.api.schema_routes.database_path", return_value=path):
            response = _client(create_jwt_token("tester")).get("/api/schema")
    finally:
        os.unlink(path)

    assert response.status_code == 200
    body = response.json()
    assert body["table"] == "sales_data"
    assert body["row_count"] == 2
    assert body["date_from"] == "2020-01-01"
    assert body["date_to"] == "2026-03-17"
    assert [column["name"] for column in body["columns"]] == [
        "customer_name",
        "document_date",
        "revenue",
    ]


@pytest.mark.unit
def test_common_columns_are_flagged() -> None:
    """
    The reference distinguishes the columns a user will actually see in an
    answer from the full set, so the panel can lead with the useful ones.
    """
    path = _make_temp_db()
    try:
        with patch("archer.api.schema_routes.database_path", return_value=path):
            body = _client(create_jwt_token("tester")).get("/api/schema").json()
    finally:
        os.unlink(path)

    flags = {column["name"]: column["common"] for column in body["columns"]}
    assert flags["customer_name"] is True
    assert flags["revenue"] is True


@pytest.mark.unit
def test_columns_carry_their_descriptions() -> None:
    path = _make_temp_db()
    try:
        with patch("archer.api.schema_routes.database_path", return_value=path):
            body = _client(create_jwt_token("tester")).get("/api/schema").json()
    finally:
        os.unlink(path)

    descriptions = {column["name"]: column["description"] for column in body["columns"]}
    assert descriptions["revenue"] == schema_routes.COLUMN_DESCRIPTIONS["revenue"]


@pytest.mark.unit
def test_every_generated_column_has_a_description() -> None:
    """
    The guide describes every column. Built from the generator's own schema,
    so adding a column to the dataset without describing it fails here rather
    than showing a visitor a blank line.
    """
    spec = importlib.util.spec_from_file_location(
        "generate_dataset", _REPO_ROOT / "scripts" / "generate_dataset.py"
    )
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)

    conn = sqlite3.connect(":memory:")
    try:
        generator.create_schema(conn)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(sales_data)")}
    finally:
        conn.close()

    assert columns == set(schema_routes.COLUMN_DESCRIPTIONS)


@pytest.mark.unit
def test_default_columns_match_the_prompt() -> None:
    """
    The guide tells a visitor which columns an answer shows by default; the
    prompt is what actually decides it. The list is written in both places,
    so this holds them together.
    """
    prompt = (_REPO_ROOT / "prompts" / "sql_generator.md").read_text(encoding="utf-8")
    match = re.search(r"ALWAYS return EXACTLY these columns: ([a-z_, ]+)\.", prompt)
    assert match, "Default column rule not found in the SQL prompt"

    prompt_columns = {name.strip() for name in match.group(1).split(",")}
    assert prompt_columns == schema_routes.COMMON_COLUMNS


@pytest.mark.unit
def test_missing_database_degrades_rather_than_failing() -> None:
    """
    A schema panel is a convenience. If the database cannot be read, the
    endpoint returns an empty description rather than a 500 - the user should
    lose a reference table, not the page.
    """
    with patch("archer.api.schema_routes.database_path", return_value="/nonexistent/none.db"):
        response = _client(create_jwt_token("tester")).get("/api/schema")

    assert response.status_code == 200
    assert response.json()["columns"] == []
