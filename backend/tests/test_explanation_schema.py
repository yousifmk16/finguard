"""
EXP-04: Unit tests for the explanation API schema and formatter.

Covers:
  ComponentBreakdownResponse  – valid construction, null raw_score
  ForecastExplanationResponse – valid construction, direction validator
  RuleResultResponse          – score bounds, fired flag
  RuleExplanationResponse     – nested models, triggered_rules list
  AnomalyExplanationResponse  – severity validator, optional sub-models
  format_explanation_dict()   – round-trips a minimal and a full payload
  format_explanation()        – accepts a ScoreBreakdown-like object
  Validation errors           – bad direction, bad severity, score out of range
  JSON serialisation          – model_dump(mode="json") produces clean output
  OpenAPI compatibility       – model_json_schema() contains expected fields
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from app.schemas.explanation import (
    AnomalyExplanationResponse,
    ComponentBreakdownResponse,
    ForecastExplanationResponse,
    RuleExplanationResponse,
    RuleResultResponse,
    format_explanation,
    format_explanation_dict,
)
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Canonical test payloads
# ---------------------------------------------------------------------------

def _component(
    name: str = "ts_signal",
    label: str = "Time-Series Signal",
    raw_score: float | None = 0.6,
    configured_weight: float = 0.35,
    effective_weight: float = 0.35,
    weighted_contribution: float = 0.21,
    active: bool = True,
) -> dict[str, Any]:
    return {
        "name": name,
        "label": label,
        "raw_score": raw_score,
        "configured_weight": configured_weight,
        "effective_weight": effective_weight,
        "weighted_contribution": weighted_contribution,
        "active": active,
    }


def _rule_result(
    rule: str = "threshold_breach",
    fired: bool = False,
    score: float = 0.0,
    reason: str = "Within budget.",
) -> dict[str, Any]:
    return {"rule": rule, "fired": fired, "score": score, "reason": reason}


def _rule_explanation() -> dict[str, Any]:
    return {
        "threshold_breach": _rule_result("threshold_breach", False, 0.0, "Within budget."),
        "sudden_jump": _rule_result("sudden_jump", True, 0.8, "Sudden jump of 100.0% detected."),
        "sustained_increase": _rule_result("sustained_increase", False, 0.0, "Only 1/3 periods."),
        "triggered_rules": ["sudden_jump"],
        "summary": "1 rule triggered: sudden_jump — Sudden jump of 100.0% detected.",
    }


def _forecast_explanation(direction: str = "above") -> dict[str, Any]:
    return {
        "actual": 150.0,
        "forecast_mean": 100.0,
        "forecast_std": 10.0,
        "residual": 50.0,
        "pct_deviation": 50.0,
        "z_score": 5.0,
        "direction": direction,
        "ci_breaches": {"95": True},
        "summary": "Actual total_cost (150.00) is 50.0% above the forecast (100.00).",
    }


def _minimal_payload() -> dict[str, Any]:
    return {
        "anomaly_score": 0.62,
        "anomaly_threshold": 0.55,
        "is_anomaly": True,
        "severity": "medium",
        "components": [
            _component("ts_signal", "Time-Series Signal", 0.6, 0.35, 0.35, 0.21, True),
            _component("if_score", "Isolation Forest", 0.7, 0.40, 0.40, 0.28, True),
            _component("rule_score", "Rule Engine", 0.5, 0.25, 0.25, 0.125, True),
        ],
    }


def _full_payload() -> dict[str, Any]:
    p = _minimal_payload()
    p["forecast_explanation"] = _forecast_explanation()
    p["rule_explanation"] = _rule_explanation()
    return p


# ---------------------------------------------------------------------------
# ComponentBreakdownResponse
# ---------------------------------------------------------------------------


class TestComponentBreakdownResponse:
    def test_valid_construction(self):
        c = ComponentBreakdownResponse(**_component())
        assert c.name == "ts_signal"
        assert c.active is True

    def test_null_raw_score_accepted(self):
        c = ComponentBreakdownResponse(**_component(raw_score=None, active=False))
        assert c.raw_score is None
        assert c.active is False

    def test_all_fields_present_in_dict(self):
        d = ComponentBreakdownResponse(**_component()).model_dump()
        for key in ["name", "label", "raw_score", "configured_weight",
                    "effective_weight", "weighted_contribution", "active"]:
            assert key in d


# ---------------------------------------------------------------------------
# ForecastExplanationResponse
# ---------------------------------------------------------------------------


class TestForecastExplanationResponse:
    def test_valid_above(self):
        f = ForecastExplanationResponse(**_forecast_explanation("above"))
        assert f.direction == "above"
        assert f.pct_deviation == 50.0

    def test_valid_below(self):
        f = ForecastExplanationResponse(**_forecast_explanation("below"))
        assert f.direction == "below"

    def test_valid_within(self):
        f = ForecastExplanationResponse(**_forecast_explanation("within"))
        assert f.direction == "within"

    def test_invalid_direction_raises(self):
        data = _forecast_explanation("sideways")
        with pytest.raises(ValidationError) as exc:
            ForecastExplanationResponse(**data)
        assert "direction" in str(exc.value)

    def test_nullable_fields_accept_none(self):
        data = _forecast_explanation()
        data.update({"forecast_mean": None, "forecast_std": None,
                     "residual": None, "pct_deviation": None, "z_score": None})
        f = ForecastExplanationResponse(**data)
        assert f.forecast_mean is None
        assert f.z_score is None

    def test_ci_breaches_dict(self):
        f = ForecastExplanationResponse(**_forecast_explanation())
        assert f.ci_breaches == {"95": True}

    def test_ci_breaches_defaults_empty(self):
        data = _forecast_explanation()
        del data["ci_breaches"]
        f = ForecastExplanationResponse(**data)
        assert f.ci_breaches == {}


# ---------------------------------------------------------------------------
# RuleResultResponse
# ---------------------------------------------------------------------------


class TestRuleResultResponse:
    def test_valid_fired(self):
        r = RuleResultResponse(**_rule_result("sudden_jump", True, 0.8, "reason"))
        assert r.fired is True
        assert r.score == 0.8

    def test_valid_not_fired(self):
        r = RuleResultResponse(**_rule_result(fired=False, score=0.0))
        assert r.fired is False

    def test_score_zero_valid(self):
        RuleResultResponse(**_rule_result(score=0.0))

    def test_score_one_valid(self):
        RuleResultResponse(**_rule_result(score=1.0))

    def test_score_above_one_raises(self):
        with pytest.raises(ValidationError):
            RuleResultResponse(**_rule_result(score=1.1))

    def test_score_below_zero_raises(self):
        with pytest.raises(ValidationError):
            RuleResultResponse(**_rule_result(score=-0.1))


# ---------------------------------------------------------------------------
# RuleExplanationResponse
# ---------------------------------------------------------------------------


class TestRuleExplanationResponse:
    def test_valid_construction(self):
        r = RuleExplanationResponse(**_rule_explanation())
        assert r.sudden_jump.fired is True
        assert "sudden_jump" in r.triggered_rules

    def test_triggered_rules_empty_when_none_fired(self):
        data = _rule_explanation()
        data["sudden_jump"] = _rule_result("sudden_jump", False, 0.0, "No jump.")
        data["triggered_rules"] = []
        data["summary"] = "No rules triggered."
        r = RuleExplanationResponse(**data)
        assert r.triggered_rules == []

    def test_all_three_rules_present(self):
        r = RuleExplanationResponse(**_rule_explanation())
        assert r.threshold_breach.rule == "threshold_breach"
        assert r.sudden_jump.rule == "sudden_jump"
        assert r.sustained_increase.rule == "sustained_increase"


# ---------------------------------------------------------------------------
# AnomalyExplanationResponse
# ---------------------------------------------------------------------------


class TestAnomalyExplanationResponse:
    def test_minimal_payload(self):
        r = AnomalyExplanationResponse(**_minimal_payload())
        assert r.is_anomaly is True
        assert len(r.components) == 3
        assert r.forecast_explanation is None
        assert r.rule_explanation is None

    def test_full_payload(self):
        r = AnomalyExplanationResponse(**_full_payload())
        assert r.forecast_explanation is not None
        assert r.rule_explanation is not None

    def test_severity_none_accepted(self):
        p = _minimal_payload()
        p["severity"] = None
        r = AnomalyExplanationResponse(**p)
        assert r.severity is None

    def test_severity_valid_values(self):
        for sev in ("none", "low", "medium", "high"):
            p = _minimal_payload()
            p["severity"] = sev
            AnomalyExplanationResponse(**p)

    def test_severity_invalid_raises(self):
        p = _minimal_payload()
        p["severity"] = "critical"
        with pytest.raises(ValidationError) as exc:
            AnomalyExplanationResponse(**p)
        assert "severity" in str(exc.value)

    def test_anomaly_score_bounds(self):
        # Exactly 0 and 1 are valid
        p = _minimal_payload()
        p["anomaly_score"] = 0.0
        AnomalyExplanationResponse(**p)
        p["anomaly_score"] = 1.0
        AnomalyExplanationResponse(**p)

    def test_anomaly_score_above_one_raises(self):
        p = _minimal_payload()
        p["anomaly_score"] = 1.001
        with pytest.raises(ValidationError):
            AnomalyExplanationResponse(**p)

    def test_components_list_preserved(self):
        r = AnomalyExplanationResponse(**_full_payload())
        names = [c.name for c in r.components]
        assert names == ["ts_signal", "if_score", "rule_score"]

    def test_inactive_component_null_raw_score(self):
        p = _minimal_payload()
        p["components"][0]["raw_score"] = None
        p["components"][0]["active"] = False
        r = AnomalyExplanationResponse(**p)
        assert r.components[0].raw_score is None
        assert r.components[0].active is False


# ---------------------------------------------------------------------------
# format_explanation_dict()
# ---------------------------------------------------------------------------


class TestFormatExplanationDict:
    def test_minimal_round_trip(self):
        r = format_explanation_dict(_minimal_payload())
        assert isinstance(r, AnomalyExplanationResponse)
        assert r.anomaly_score == 0.62

    def test_full_round_trip(self):
        r = format_explanation_dict(_full_payload())
        assert r.forecast_explanation is not None
        assert r.rule_explanation is not None
        assert r.rule_explanation.sudden_jump.fired is True

    def test_returns_anomaly_explanation_response(self):
        r = format_explanation_dict(_minimal_payload())
        assert isinstance(r, AnomalyExplanationResponse)

    def test_invalid_dict_raises_validation_error(self):
        with pytest.raises(ValidationError):
            format_explanation_dict({"anomaly_score": 2.0})  # score > 1


# ---------------------------------------------------------------------------
# format_explanation() with ScoreBreakdown-like object
# ---------------------------------------------------------------------------


class TestFormatExplanation:
    def _make_mock_breakdown(self, payload: dict[str, Any]) -> MagicMock:
        mock = MagicMock()
        mock.to_dict.return_value = payload
        return mock

    def test_calls_to_dict(self):
        mock_bd = self._make_mock_breakdown(_minimal_payload())
        format_explanation(mock_bd)
        mock_bd.to_dict.assert_called_once()

    def test_returns_anomaly_explanation_response(self):
        mock_bd = self._make_mock_breakdown(_minimal_payload())
        r = format_explanation(mock_bd)
        assert isinstance(r, AnomalyExplanationResponse)

    def test_full_payload_from_mock(self):
        mock_bd = self._make_mock_breakdown(_full_payload())
        r = format_explanation(mock_bd)
        assert r.forecast_explanation is not None
        assert r.rule_explanation is not None


# ---------------------------------------------------------------------------
# JSON serialisation
# ---------------------------------------------------------------------------


class TestJsonSerialisation:
    def test_model_dump_json_no_nan(self):
        # Null raw_score should appear as null in JSON, not NaN
        p = _minimal_payload()
        p["components"][0]["raw_score"] = None
        r = AnomalyExplanationResponse(**p)
        j = r.model_dump(mode="json")
        assert j["components"][0]["raw_score"] is None

    def test_json_round_trip_minimal(self):
        r = format_explanation_dict(_minimal_payload())
        j_str = r.model_dump_json()
        parsed = json.loads(j_str)
        assert parsed["anomaly_score"] == 0.62
        assert parsed["is_anomaly"] is True

    def test_json_round_trip_full(self):
        r = format_explanation_dict(_full_payload())
        j_str = r.model_dump_json()
        parsed = json.loads(j_str)
        assert "forecast_explanation" in parsed
        assert "rule_explanation" in parsed
        assert parsed["rule_explanation"]["sudden_jump"]["fired"] is True

    def test_model_dump_excludes_none_optionals(self):
        # When no sub-explanations, forecast_explanation and rule_explanation
        # are None — they should still appear in the dump (not excluded by default)
        r = format_explanation_dict(_minimal_payload())
        d = r.model_dump()
        assert "forecast_explanation" in d
        assert d["forecast_explanation"] is None

    def test_no_unexpected_keys_in_component(self):
        r = format_explanation_dict(_minimal_payload())
        comp_keys = set(r.model_dump()["components"][0].keys())
        expected = {
            "name", "label", "raw_score", "configured_weight",
            "effective_weight", "weighted_contribution", "active",
        }
        assert comp_keys == expected


# ---------------------------------------------------------------------------
# OpenAPI schema compatibility
# ---------------------------------------------------------------------------


class TestOpenAPISchema:
    def test_schema_has_properties(self):
        schema = AnomalyExplanationResponse.model_json_schema()
        props = schema.get("properties", {})
        for field in ["anomaly_score", "is_anomaly", "severity", "components"]:
            assert field in props, f"Missing field in schema: {field}"

    def test_component_schema_has_description(self):
        schema = AnomalyExplanationResponse.model_json_schema()
        # components should have a description set on it
        components_schema = schema["properties"]["components"]
        assert "description" in components_schema

    def test_schema_is_json_serialisable(self):
        schema = AnomalyExplanationResponse.model_json_schema()
        json.dumps(schema)
