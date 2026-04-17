"""
EXP-04: Explanation formatting for API.

Defines Pydantic v2 response models that represent the anomaly explanation
payload produced by EXP-03 (ScoreBreakdown) in a form suitable for FastAPI
``response_model`` declarations and OpenAPI documentation.

Relationship to the EXP-* stack
--------------------------------
    EXP-01  ForecastExplanation        – forecast vs actual (ML layer)
    EXP-02  RuleExplanation            – per-rule details   (ML layer)
    EXP-03  ScoreBreakdown / to_dict() – full payload       (ML layer)
    EXP-04  AnomalyExplanationResponse – API schema         (this file)

Two entry points
----------------
``format_explanation(breakdown)``
    Accepts a ``ScoreBreakdown`` instance (EXP-03) and returns a validated
    ``AnomalyExplanationResponse``.  Use this when the breakdown is available
    as a Python object in the same process.

``format_explanation_dict(d)``
    Accepts the plain ``dict`` produced by ``ScoreBreakdown.to_dict()``.
    Use this when the breakdown is serialised (e.g. from a message queue or
    cache) before it reaches the API layer.

Usage (FastAPI endpoint)
------------------------
from app.schemas.explanation import AnomalyExplanationResponse, format_explanation

@router.get("/anomalies/{id}/explanation", response_model=AnomalyExplanationResponse)
def get_explanation(id: str) -> AnomalyExplanationResponse:
    breakdown = build_breakdown_for(id)          # returns ScoreBreakdown
    return format_explanation(breakdown)
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class ComponentBreakdownResponse(BaseModel):
    """
    Score contribution of a single ensemble component.

    Fields mirror ``ComponentBreakdown.to_dict()`` from EXP-03.
    """

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(
        description="Column name in the scored DataFrame "
        "(ts_signal | if_score | rule_score).",
    )
    label: str = Field(
        description="Human-readable component label.",
    )
    raw_score: float | None = Field(
        None,
        description="Raw component score [0, 1]; null when the component was "
        "unavailable (model not loaded or disabled).",
    )
    configured_weight: float = Field(
        description="Nominal ensemble weight from ScoringConfig.",
    )
    effective_weight: float = Field(
        description="Actual weight after NaN-renormalisation of missing "
        "components.  Always in [0, 1]; sums to 1.0 across active components.",
    )
    weighted_contribution: float = Field(
        description="effective_weight × raw_score; 0.0 when component is "
        "inactive.",
    )
    active: bool = Field(
        description="True when raw_score is a finite value (component "
        "contributed to the ensemble score).",
    )


class ForecastExplanationResponse(BaseModel):
    """
    Forecast-vs-actual deviation explanation (EXP-01).
    """

    model_config = ConfigDict(populate_by_name=True)

    actual: float = Field(description="Observed cost value.")
    forecast_mean: float | None = Field(
        None,
        description="Predicted mean from the time-series baseline model.",
    )
    forecast_std: float | None = Field(
        None,
        description="Predicted standard deviation.",
    )
    residual: float | None = Field(
        None,
        description="Signed difference: actual − forecast_mean.",
    )
    pct_deviation: float | None = Field(
        None,
        description="Signed percentage deviation from the forecast mean.  "
        "Null when forecast_mean is zero.",
    )
    z_score: float | None = Field(
        None,
        description="Signed z-score: residual / forecast_std.",
    )
    direction: str = Field(
        description='"above" | "below" | "within".',
    )
    ci_breaches: dict[str, bool] = Field(
        default_factory=dict,
        description="Maps each CI level (e.g. '95') to whether the actual "
        "value fell outside that confidence interval.",
    )
    summary: str = Field(
        description="Human-readable one-sentence deviation description.",
    )

    @field_validator("direction")
    @classmethod
    def direction_valid(cls, v: str) -> str:
        allowed = {"above", "below", "within", "unknown"}
        if v not in allowed:
            raise ValueError(f"direction must be one of {allowed}, got {v!r}")
        return v


class RuleResultResponse(BaseModel):
    """
    Result of a single deterministic rule evaluation (EXP-02).
    """

    model_config = ConfigDict(populate_by_name=True)

    rule: str = Field(
        description="Rule identifier "
        "(threshold_breach | sudden_jump | sustained_increase).",
    )
    fired: bool = Field(description="True when the rule triggered.")
    score: float = Field(
        ge=0.0,
        le=1.0,
        description="Rule confidence in [0, 1]; 0.0 when not fired.",
    )
    reason: str = Field(description="Human-readable rule reason.")


class RuleExplanationResponse(BaseModel):
    """
    Per-rule explanation details (EXP-02).
    """

    model_config = ConfigDict(populate_by_name=True)

    threshold_breach: RuleResultResponse = Field(
        description="Result of RUL-01 (absolute budget threshold).",
    )
    sudden_jump: RuleResultResponse = Field(
        description="Result of RUL-02 (single-period percentage spike).",
    )
    sustained_increase: RuleResultResponse = Field(
        description="Result of RUL-03 (consecutive-period upward trend).",
    )
    triggered_rules: list[str] = Field(
        default_factory=list,
        description="Names of rules that fired.  Empty list when none fired.",
    )
    summary: str = Field(
        description="Human-readable sentence: which rules fired and why.",
    )


# ---------------------------------------------------------------------------
# Top-level response model
# ---------------------------------------------------------------------------


class AnomalyExplanationResponse(BaseModel):
    """
    EXP-04: Full anomaly explanation response.

    Returned by the anomaly detail / explanation endpoints.  Combines:
    - Per-component score breakdown (EXP-03)
    - Forecast-vs-actual deviation (EXP-01, optional)
    - Triggered-rule details (EXP-02, optional)
    """

    model_config = ConfigDict(populate_by_name=True)

    anomaly_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Final weighted ensemble score in [0, 1].",
    )
    anomaly_threshold: float = Field(
        ge=0.0,
        le=1.0,
        description="Score threshold above which is_anomaly is True.",
    )
    is_anomaly: bool = Field(
        description="True when anomaly_score ≥ anomaly_threshold.",
    )
    severity: str | None = Field(
        None,
        description='"none" | "low" | "medium" | "high"; null when severity '
        "mapping was not applied.",
    )
    components: list[ComponentBreakdownResponse] = Field(
        description="Score breakdown per ensemble component, ordered "
        "ts_signal → if_score → rule_score.",
    )
    forecast_explanation: ForecastExplanationResponse | None = Field(
        None,
        description="Forecast-vs-actual deviation details (EXP-01). "
        "Null when the time-series baseline was not available.",
    )
    rule_explanation: RuleExplanationResponse | None = Field(
        None,
        description="Per-rule fired/score/reason details (EXP-02). "
        "Null when rule explanation was not computed.",
    )

    @field_validator("severity")
    @classmethod
    def severity_valid(cls, v: str | None) -> str | None:
        if v is None:
            return v
        allowed = {"none", "low", "medium", "high"}
        if v not in allowed:
            raise ValueError(f"severity must be one of {allowed}, got {v!r}")
        return v


# ---------------------------------------------------------------------------
# Formatter functions
# ---------------------------------------------------------------------------


def format_explanation(breakdown: object) -> AnomalyExplanationResponse:
    """
    Convert a ``ScoreBreakdown`` (EXP-03) to an ``AnomalyExplanationResponse``.

    Parameters
    ----------
    breakdown :
        A ``ScoreBreakdown`` instance produced by ``ScoreBreakdownBuilder``.

    Returns
    -------
    AnomalyExplanationResponse validated by Pydantic.

    Raises
    ------
    pydantic.ValidationError
        If the breakdown payload fails schema validation.
    """
    payload: dict[str, Any] = breakdown.to_dict()  # type: ignore[attr-defined]
    return format_explanation_dict(payload)


def format_explanation_dict(d: dict[str, Any]) -> AnomalyExplanationResponse:
    """
    Build an ``AnomalyExplanationResponse`` from the plain dict produced by
    ``ScoreBreakdown.to_dict()``.

    Use this overload when the breakdown has been serialised (e.g. loaded from
    a message queue payload or cache) before reaching the API layer.

    Parameters
    ----------
    d :
        A dict matching the structure returned by ``ScoreBreakdown.to_dict()``.

    Returns
    -------
    AnomalyExplanationResponse validated by Pydantic.
    """
    return AnomalyExplanationResponse.model_validate(d)
