"""Tests for INT-01: CORS middleware on the FastAPI app."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


class TestCors:
    def test_preflight_from_dev_origin_succeeds(self) -> None:
        # Vite dev server runs on http://localhost:3000 — this must work
        # out of the box without any env var being set.
        r = client.options(
            "/api/v1/anomalies",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"

    def test_preflight_allows_authorization_header(self) -> None:
        r = client.options(
            "/api/v1/anomalies",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        allowed = r.headers.get("access-control-allow-headers", "").lower()
        assert "authorization" in allowed

    def test_preflight_allows_patch_for_status_updates(self) -> None:
        # API-03 uses PATCH; the UI must be able to preflight it.
        r = client.options(
            "/api/v1/anomalies/abc/status",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "PATCH",
                "Access-Control-Request-Headers": "Authorization,Content-Type",
            },
        )
        allowed_methods = r.headers.get("access-control-allow-methods", "").upper()
        assert "PATCH" in allowed_methods

    def test_response_includes_allow_origin_for_simple_get(self) -> None:
        r = client.get(
            "/health",
            headers={"Origin": "http://localhost:3000"},
        )
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"

    def test_disallowed_origin_does_not_get_allow_header(self) -> None:
        r = client.get(
            "/health",
            headers={"Origin": "https://evil.example.com"},
        )
        # The endpoint still answers (browsers, not Starlette, enforce CORS),
        # but Starlette must not echo back an allow header for this origin.
        assert r.headers.get("access-control-allow-origin") != "https://evil.example.com"
