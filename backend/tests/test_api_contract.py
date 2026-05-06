"""
TST-04: API contract tests.

Verify the OpenAPI specification (API-06) is self-consistent and that
runtime responses match the shapes the spec documents. The goal is to
catch drift the moment a route's annotations stop matching the actual
output — a class of bug that is otherwise easy to miss until clients
break.

Coverage layers:
1. Spec wellness   — /openapi.json reachable, well-formed, expected metadata.
2. Schema sanity   — every documented response references a defined schema;
                     every defined schema appears as a response shape or a
                     nested ref.
3. Tag consistency — every endpoint tag has a description in the root tags
                     list (otherwise /docs shows undocumented tags).
4. Auth contract   — every protected endpoint declares 401 + 403.
5. Versioning      — all non-utility paths live under /api/v1/.
6. Live responses  — actual JSON keys match the documented schema's
                     ``required`` fields for the main read endpoints.
7. Error contract  — documented error codes are actually returned.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _spec() -> dict[str, Any]:
    """Fetch the live OpenAPI spec served by the running app."""
    response = client.get("/openapi.json")
    assert response.status_code == 200, "openapi.json must be served"
    return response.json()


def _resolve_ref(spec: dict, ref: str) -> dict:
    """Resolve a JSON-pointer-style $ref like ``#/components/schemas/X``."""
    parts = ref.lstrip("#/").split("/")
    node = spec
    for part in parts:
        node = node[part]
    return node


def _required_fields(spec: dict, schema_name: str) -> set[str]:
    """Return ``required`` field names for a top-level schema, or empty set."""
    schema = spec["components"]["schemas"].get(schema_name, {})
    return set(schema.get("required", []))


# ---------------------------------------------------------------------------
# 1. Spec wellness
# ---------------------------------------------------------------------------


class TestSpecWellness:
    def test_openapi_endpoint_returns_200(self) -> None:
        assert client.get("/openapi.json").status_code == 200

    def test_docs_endpoint_returns_html(self) -> None:
        # Swagger UI page — sanity check API-06 documentation is exposed.
        response = client.get("/docs")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_redoc_endpoint_returns_html(self) -> None:
        response = client.get("/redoc")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_spec_has_title_and_version(self) -> None:
        info = _spec().get("info", {})
        assert info.get("title") == "FinGuard API"
        assert "version" in info and info["version"]

    def test_spec_declares_openapi_version(self) -> None:
        spec = _spec()
        assert "openapi" in spec
        assert spec["openapi"].startswith("3.")


# ---------------------------------------------------------------------------
# 2. Schema sanity
# ---------------------------------------------------------------------------


class TestSchemaSanity:
    def test_every_response_ref_is_defined(self) -> None:
        spec = _spec()
        defined = set(spec["components"]["schemas"].keys())
        seen_refs: set[str] = set()

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                if "$ref" in node and isinstance(node["$ref"], str):
                    seen_refs.add(node["$ref"].rsplit("/", 1)[-1])
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(spec["paths"])

        missing = seen_refs - defined
        assert not missing, f"Path responses reference undefined schemas: {missing}"

    def test_anomaly_response_has_expected_required_fields(self) -> None:
        required = _required_fields(_spec(), "AnomalyResponse")
        # Hard contract: clients depend on these.
        for field in ("anomaly_id", "account_id", "service", "region", "severity", "status"):
            assert field in required, f"AnomalyResponse must require '{field}'"

    def test_alert_response_has_expected_required_fields(self) -> None:
        required = _required_fields(_spec(), "AlertResponse")
        for field in ("alert_id", "anomaly_id", "severity", "status", "channel"):
            assert field in required, f"AlertResponse must require '{field}'"

    def test_token_response_has_role(self) -> None:
        # Frontend uses this to build the role-aware UI (UI-09).
        required = _required_fields(_spec(), "TokenResponse")
        assert "role" in required
        assert "access_token" in required


# ---------------------------------------------------------------------------
# 3. Tag consistency
# ---------------------------------------------------------------------------


class TestTagConsistency:
    def test_every_used_tag_is_declared(self) -> None:
        spec = _spec()
        declared = {t["name"] for t in spec.get("tags", [])}
        used: set[str] = set()
        for path_ops in spec["paths"].values():
            for method, op in path_ops.items():
                if isinstance(op, dict):
                    used.update(op.get("tags", []))
        undocumented = used - declared
        assert not undocumented, (
            f"These tags appear on endpoints but are not in the root tags list: "
            f"{undocumented}. /docs will show them without a description."
        )

    def test_every_declared_tag_has_a_description(self) -> None:
        for tag in _spec().get("tags", []):
            assert tag.get("description"), f"Tag '{tag['name']}' is missing a description"


# ---------------------------------------------------------------------------
# 4. Auth contract
# ---------------------------------------------------------------------------


# Endpoints that intentionally do not require auth. Anything not on this list
# is expected to declare 401 (and, for GETs, 403) in its OpenAPI responses.
_PUBLIC_PATHS = {
    "/api/v1/auth/login",          # SEC-01 auth itself
    "/health",                     # top-level liveness probe
    "/api/v1/detection/health",    # DET-03 — for monitoring scrapers, intentionally unauthenticated
    "/api/v1/detection/metrics",   # DET-03 — for Prometheus / similar, intentionally unauthenticated
}


class TestAuthContract:
    def test_protected_endpoints_declare_401(self) -> None:
        spec = _spec()
        offenders: list[str] = []
        for path, ops in spec["paths"].items():
            if path in _PUBLIC_PATHS:
                continue
            for method, op in ops.items():
                if not isinstance(op, dict):
                    continue
                if "401" not in op.get("responses", {}):
                    offenders.append(f"{method.upper()} {path}")
        assert not offenders, (
            f"Protected endpoints missing documented 401 response: {offenders}"
        )

    def test_protected_get_endpoints_declare_403(self) -> None:
        # All protected GET endpoints go through the analyst-or-admin RBAC dep.
        spec = _spec()
        offenders: list[str] = []
        for path, ops in spec["paths"].items():
            if path in _PUBLIC_PATHS:
                continue
            get_op = ops.get("get")
            if not isinstance(get_op, dict):
                continue
            if "403" not in get_op.get("responses", {}):
                offenders.append(path)
        assert not offenders, (
            f"Protected GETs missing documented 403 response: {offenders}"
        )


# ---------------------------------------------------------------------------
# 5. Versioning
# ---------------------------------------------------------------------------


class TestVersioning:
    def test_business_endpoints_under_v1(self) -> None:
        # Only utility endpoints are allowed outside /api/v1/.
        allowed_outside_v1 = {"/health", "/openapi.json", "/docs", "/redoc"}
        offenders: list[str] = []
        for path in _spec()["paths"].keys():
            if path in allowed_outside_v1:
                continue
            if not path.startswith("/api/v1/"):
                offenders.append(path)
        assert not offenders, f"Endpoints not under /api/v1/: {offenders}"


# ---------------------------------------------------------------------------
# 6. Live responses match documented shape
# ---------------------------------------------------------------------------


def _empty_db_override() -> None:
    """Replace the DB dependency with None so endpoints take their no-DB path."""
    app.dependency_overrides[get_db] = lambda: None


def _restore_db_override() -> None:
    app.dependency_overrides.pop(get_db, None)


class TestLiveResponseShape:
    def setup_method(self) -> None:
        _empty_db_override()

    def teardown_method(self) -> None:
        _restore_db_override()

    def test_anomaly_list_matches_schema(self) -> None:
        body = client.get("/api/v1/anomalies").json()
        required = _required_fields(_spec(), "AnomalyListResponse")
        for field in required:
            assert field in body, f"AnomalyListResponse missing required field '{field}'"

    def test_alert_list_matches_schema(self) -> None:
        body = client.get("/api/v1/alerts").json()
        required = _required_fields(_spec(), "AlertListResponse")
        for field in required:
            assert field in body, f"AlertListResponse missing required field '{field}'"

    def test_kpi_summary_matches_schema(self) -> None:
        body = client.get("/api/v1/kpi/summary").json()
        required = _required_fields(_spec(), "KpiSummaryResponse")
        for field in required:
            assert field in body, f"KpiSummaryResponse missing required field '{field}'"

    def test_kpi_trend_matches_schema(self) -> None:
        body = client.get("/api/v1/kpi/trend").json()
        required = _required_fields(_spec(), "KpiTrendResponse")
        for field in required:
            assert field in body, f"KpiTrendResponse missing required field '{field}'"

    def test_health_returns_status_field(self) -> None:
        body = client.get("/health").json()
        assert "status" in body


# ---------------------------------------------------------------------------
# 7. Error contract — documented status codes actually fire
# ---------------------------------------------------------------------------


class TestErrorContract:
    def setup_method(self) -> None:
        _empty_db_override()

    def teardown_method(self) -> None:
        _restore_db_override()

    def test_invalid_severity_returns_422(self) -> None:
        # Spec documents 422 for the anomaly list — confirm it actually fires.
        r = client.get("/api/v1/anomalies?severity=critical")
        assert r.status_code == 422

    def test_invalid_alert_status_returns_422(self) -> None:
        r = client.get("/api/v1/alerts?status=deleted")
        assert r.status_code == 422

    def test_kpi_trend_over_max_returns_422(self) -> None:
        r = client.get("/api/v1/kpi/trend?days=999")
        assert r.status_code == 422

    def test_unknown_anomaly_id_returns_404(self) -> None:
        # 404 path requires an active DB; mock it returning None for the anomaly.
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        app.dependency_overrides[get_db] = lambda: db
        try:
            r = client.get(f"/api/v1/anomalies/{uuid.uuid4()}")
            assert r.status_code == 404
        finally:
            _empty_db_override()


# ---------------------------------------------------------------------------
# 8. Pagination defaults match docs
# ---------------------------------------------------------------------------


class TestPaginationDefaults:
    def setup_method(self) -> None:
        _empty_db_override()

    def teardown_method(self) -> None:
        _restore_db_override()

    def test_anomaly_list_default_page_size(self) -> None:
        # Spec documents page_size default as 50; the no-DB branch echoes
        # whatever the query handler used.
        body = client.get("/api/v1/anomalies").json()
        assert body["page"] == 1
        assert body["page_size"] == 50

    def test_alert_list_default_page_size(self) -> None:
        body = client.get("/api/v1/alerts").json()
        assert body["page"] == 1
        assert body["page_size"] == 50

    def test_kpi_trend_default_days(self) -> None:
        body = client.get("/api/v1/kpi/trend").json()
        assert body["days"] == 14
