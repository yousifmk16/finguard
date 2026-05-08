# MLQ-04 — Explainability Quality Examples

> Generated 2026-05-08T13:26:18.018020+00:00.
> Run via `python -m ml.src.evaluation.explainability_examples`.
> Machine-readable: [`explainability_examples.json`](explainability_examples.json).
> Threshold 0.3000 (source: `threshold_calibration.json` (MLQ-01)). Validation set matches MLQ-01 / MLQ-02 / MLQ-03 (seed = 42).

## What this gallery proves

Each case below is a real row from the validation set, scored
through the EXP-01..03 pipeline and round-tripped through the
EXP-04 Pydantic schema. A run is only published when *every*
payload validates — that round-trip is the contract gate.

Quality axes the gallery exercises:

1. **Numeric / narrative agreement** — the one-line summary must
   match the signed residual, z-score, and CI-breach flags.
2. **Multi-rule narrative** — when ≥ 2 rules fire, the rule
   explanation must enumerate them coherently.
3. **Graceful degradation** — `if_score` is intentionally NaN
   here; the component breakdown must surface that as `active=false`
   without polluting the final score.
4. **Honest non-detection** — when `is_anomaly = 0`, the summary
   must NOT claim an anomaly even if the score is non-trivial.

## Cases

### `high_confidence_spike`

_Strongest TP. Verifies the headline summary, component contributions, and severity all agree at the top of the score range._

| Field | Value |
| --- | --- |
| Row index | `2746` |
| Label | `anomaly` |
| Anomaly type | `spike` |
| Account / Service / Region | `acct-prod-1` / `Cloud Storage` / `us-central1` |
| Timestamp | `2026-04-25T10:00:00+00:00` |
| Cost (actual) | `1,696.87` |
| Forecast mean ± std | `337.07` ± `171.30` |
| Anomaly score | **`0.9368`** (threshold `0.3000`) |
| Verdict | `FLAGGED` (severity `high`) |

**Forecast vs actual (EXP-01)**

> Actual total_cost (1696.87) is 403.4% above the forecast (337.07), a deviation of 7.9 standard deviations, breaching the 95% confidence interval.

**Triggered rules (EXP-02)**

> 3 rules triggered: threshold_breach — Value 1696.87 exceeds budget limit 1000.00 by 69.7%.; sudden_jump — Sudden jump of 318.7% detected (threshold 50.0%, window mean 405.27).; sustained_increase — All 3 consecutive periods grew by ≥5.0% — sustained upward trend detected.

| Rule | Fired | Score | Reason |
| --- | --- | --- | --- |
| `threshold_breach` | ✓ | `0.6969` | Value 1696.87 exceeds budget limit 1000.00 by 69.7%. |
| `sudden_jump` | ✓ | `1.0000` | Sudden jump of 318.7% detected (threshold 50.0%, window mean 405.27). |
| `sustained_increase` | ✓ | `1.0000` | All 3 consecutive periods grew by ≥5.0% — sustained upward trend detected. |

**Component breakdown (EXP-03)**

| Component | Active | Raw score | Configured weight | Effective weight | Contribution |
| --- | --- | --- | --- | --- | --- |
| `ts_signal` (Time-Series Signal) | ✓ | `1.0000` | `0.3500` | `0.5833` | `0.5833` |
| `if_score` (Isolation Forest) | · | — | `0.4000` | `0.0000` | `0.0000` |
| `rule_score` (Rule Engine) | ✓ | `0.8484` | `0.2500` | `0.4167` | `0.3535` |

**EXP-04 payload (validated)**

```json
{
  "anomaly_score": 0.936847,
  "anomaly_threshold": 0.3,
  "is_anomaly": true,
  "severity": "high",
  "components": [
    {
      "name": "ts_signal",
      "label": "Time-Series Signal",
      "raw_score": 1.0,
      "configured_weight": 0.35,
      "effective_weight": 0.583333,
      "weighted_contribution": 0.583333,
      "active": true
    },
    {
      "name": "if_score",
      "label": "Isolation Forest",
      "raw_score": null,
      "configured_weight": 0.4,
      "effective_weight": 0.0,
      "weighted_contribution": 0.0,
      "active": false
    },
    {
      "name": "rule_score",
      "label": "Rule Engine",
      "raw_score": 0.848433,
      "configured_weight": 0.25,
      "effective_weight": 0.416667,
      "weighted_contribution": 0.353514,
      "active": true
    }
  ],
  "forecast_explanation": {
    "actual": 1696.865925,
    "forecast_mean": 337.066996,
    "forecast_std": 171.303696,
    "residual": 1359.798929,
    "pct_deviation": 403.421,
    "z_score": 7.9379,
    "direction": "above",
    "ci_breaches": {
      "95": true
    },
    "summary": "Actual total_cost (1696.87) is 403.4% above the forecast (337.07), a deviation of 7.9 standard deviations, breaching the 95% confidence interval."
  },
  "rule_explanation": {
    "threshold_breach": {
      "rule": "threshold_breach",
      "fired": true,
      "score": 0.696866,
      "reason": "Value 1696.87 exceeds budget limit 1000.00 by 69.7%."
    },
    "sudden_jump": {
      "rule": "sudden_jump",
      "fired": true,
      "score": 1.0,
      "reason": "Sudden jump of 318.7% detected (threshold 50.0%, window mean 405.27)."
    },
    "sustained_increase": {
      "rule": "sustained_increase",
      "fired": true,
      "score": 1.0,
      "reason": "All 3 consecutive periods grew by \u22655.0% \u2014 sustained upward trend detected."
    },
    "triggered_rules": [
      "threshold_breach",
      "sudden_jump",
      "sustained_increase"
    ],
    "summary": "3 rules triggered: threshold_breach \u2014 Value 1696.87 exceeds budget limit 1000.00 by 69.7%.; sudden_jump \u2014 Sudden jump of 318.7% detected (threshold 50.0%, window mean 405.27).; sustained_increase \u2014 All 3 consecutive periods grew by \u22655.0% \u2014 sustained upward trend detected."
  }
}
```

### `sustained_budget_breach`

_Budget_breach row with at least one rule fired — exercises the multi-rule narrative path in EXP-02 and the rule-driven score contribution in EXP-03._

| Field | Value |
| --- | --- |
| Row index | `1524` |
| Label | `anomaly` |
| Anomaly type | `budget_breach` |
| Account / Service / Region | `acct-prod-2` / `BigQuery` / `us-east1` |
| Timestamp | `2026-03-05T12:00:00+00:00` |
| Cost (actual) | `911.63` |
| Forecast mean ± std | `266.95` ± `141.41` |
| Anomaly score | **`0.7124`** (threshold `0.3000`) |
| Verdict | `FLAGGED` (severity `medium`) |

**Forecast vs actual (EXP-01)**

> Actual total_cost (911.63) is 241.5% above the forecast (266.95), a deviation of 4.6 standard deviations, breaching the 95% confidence interval.

**Triggered rules (EXP-02)**

> 1 rule triggered: sudden_jump — Sudden jump of 221.8% detected (threshold 50.0%, window mean 283.32).

| Rule | Fired | Score | Reason |
| --- | --- | --- | --- |
| `threshold_breach` | · | `0.0000` | Value 911.63 within budget limit 1000.00. |
| `sudden_jump` | ✓ | `1.0000` | Sudden jump of 221.8% detected (threshold 50.0%, window mean 283.32). |
| `sustained_increase` | · | `0.6667` | Only 2/3 periods met the 5.0% growth threshold. |

**Component breakdown (EXP-03)**

| Component | Active | Raw score | Configured weight | Effective weight | Contribution |
| --- | --- | --- | --- | --- | --- |
| `ts_signal` (Time-Series Signal) | ✓ | `0.9118` | `0.3500` | `0.5833` | `0.5319` |
| `if_score` (Isolation Forest) | · | — | `0.4000` | `0.0000` | `0.0000` |
| `rule_score` (Rule Engine) | ✓ | `0.4333` | `0.2500` | `0.4167` | `0.1806` |

**EXP-04 payload (validated)**

```json
{
  "anomaly_score": 0.712444,
  "anomaly_threshold": 0.3,
  "is_anomaly": true,
  "severity": "medium",
  "components": [
    {
      "name": "ts_signal",
      "label": "Time-Series Signal",
      "raw_score": 0.91181,
      "configured_weight": 0.35,
      "effective_weight": 0.583333,
      "weighted_contribution": 0.531889,
      "active": true
    },
    {
      "name": "if_score",
      "label": "Isolation Forest",
      "raw_score": null,
      "configured_weight": 0.4,
      "effective_weight": 0.0,
      "weighted_contribution": 0.0,
      "active": false
    },
    {
      "name": "rule_score",
      "label": "Rule Engine",
      "raw_score": 0.433333,
      "configured_weight": 0.25,
      "effective_weight": 0.416667,
      "weighted_contribution": 0.180556,
      "active": true
    }
  ],
  "forecast_explanation": {
    "actual": 911.627209,
    "forecast_mean": 266.947745,
    "forecast_std": 141.406595,
    "residual": 644.679464,
    "pct_deviation": 241.5002,
    "z_score": 4.559,
    "direction": "above",
    "ci_breaches": {
      "95": true
    },
    "summary": "Actual total_cost (911.63) is 241.5% above the forecast (266.95), a deviation of 4.6 standard deviations, breaching the 95% confidence interval."
  },
  "rule_explanation": {
    "threshold_breach": {
      "rule": "threshold_breach",
      "fired": false,
      "score": 0.0,
      "reason": "Value 911.63 within budget limit 1000.00."
    },
    "sudden_jump": {
      "rule": "sudden_jump",
      "fired": true,
      "score": 1.0,
      "reason": "Sudden jump of 221.8% detected (threshold 50.0%, window mean 283.32)."
    },
    "sustained_increase": {
      "rule": "sustained_increase",
      "fired": false,
      "score": 0.666667,
      "reason": "Only 2/3 periods met the 5.0% growth threshold."
    },
    "triggered_rules": [
      "sudden_jump"
    ],
    "summary": "1 rule triggered: sudden_jump \u2014 Sudden jump of 221.8% detected (threshold 50.0%, window mean 283.32)."
  }
}
```

### `borderline_normal`

_Highest-scoring true negative. Verifies the explanation does not overclaim when ``is_anomaly = 0`` but the score is non-trivial._

| Field | Value |
| --- | --- |
| Row index | `88` |
| Label | `normal` |
| Anomaly type | `normal` |
| Account / Service / Region | `acct-dev-1` / `Compute Engine` / `us-east1` |
| Timestamp | `2026-01-04T16:00:00+00:00` |
| Cost (actual) | `45.67` |
| Forecast mean ± std | `135.72` ± `67.94` |
| Anomaly score | **`0.2102`** (threshold `0.3000`) |
| Verdict | `NOT flagged` (severity `none`) |

**Forecast vs actual (EXP-01)**

> Actual total_cost (45.67) is 66.4% below the forecast (135.72), a deviation of 1.3 standard deviations.

**Triggered rules (EXP-02)**

> No rules triggered.

**Component breakdown (EXP-03)**

| Component | Active | Raw score | Configured weight | Effective weight | Contribution |
| --- | --- | --- | --- | --- | --- |
| `ts_signal` (Time-Series Signal) | ✓ | `0.2651` | `0.3500` | `0.5833` | `0.1546` |
| `if_score` (Isolation Forest) | · | — | `0.4000` | `0.0000` | `0.0000` |
| `rule_score` (Rule Engine) | ✓ | `0.1333` | `0.2500` | `0.4167` | `0.0556` |

**EXP-04 payload (validated)**

```json
{
  "anomaly_score": 0.210188,
  "anomaly_threshold": 0.3,
  "is_anomaly": false,
  "severity": "none",
  "components": [
    {
      "name": "ts_signal",
      "label": "Time-Series Signal",
      "raw_score": 0.265084,
      "configured_weight": 0.35,
      "effective_weight": 0.583333,
      "weighted_contribution": 0.154632,
      "active": true
    },
    {
      "name": "if_score",
      "label": "Isolation Forest",
      "raw_score": null,
      "configured_weight": 0.4,
      "effective_weight": 0.0,
      "weighted_contribution": 0.0,
      "active": false
    },
    {
      "name": "rule_score",
      "label": "Rule Engine",
      "raw_score": 0.133333,
      "configured_weight": 0.25,
      "effective_weight": 0.416667,
      "weighted_contribution": 0.055556,
      "active": true
    }
  ],
  "forecast_explanation": {
    "actual": 45.666437,
    "forecast_mean": 135.719531,
    "forecast_std": 67.943133,
    "residual": -90.053095,
    "pct_deviation": -66.3523,
    "z_score": -1.3254,
    "direction": "below",
    "ci_breaches": {
      "95": false
    },
    "summary": "Actual total_cost (45.67) is 66.4% below the forecast (135.72), a deviation of 1.3 standard deviations."
  },
  "rule_explanation": {
    "threshold_breach": {
      "rule": "threshold_breach",
      "fired": false,
      "score": 0.0,
      "reason": "Value 45.67 within budget limit 1000.00."
    },
    "sudden_jump": {
      "rule": "sudden_jump",
      "fired": false,
      "score": 0.0,
      "reason": "Jump of -42.9% is below threshold 50.0%."
    },
    "sustained_increase": {
      "rule": "sustained_increase",
      "fired": false,
      "score": 0.666667,
      "reason": "Only 2/3 periods met the 5.0% growth threshold."
    },
    "triggered_rules": [],
    "summary": "No rules triggered."
  }
}
```

### `calm_normal`

_Lowest-scoring normal. Verifies the quiet path ('forecast holds; no rules fired') still produces a coherent payload._

| Field | Value |
| --- | --- |
| Row index | `1750` |
| Label | `normal` |
| Anomaly type | `normal` |
| Account / Service / Region | `acct-dev-1` / `Compute Engine` / `us-east1` |
| Timestamp | `2026-03-14T22:00:00+00:00` |
| Cost (actual) | `135.51` |
| Forecast mean ± std | `135.72` ± `67.94` |
| Anomaly score | **`0.0004`** (threshold `0.3000`) |
| Verdict | `NOT flagged` (severity `none`) |

**Forecast vs actual (EXP-01)**

> Actual total_cost (135.51) is 0.2% below the forecast (135.72), a deviation of 0.0 standard deviations.

**Triggered rules (EXP-02)**

> No rules triggered.

**Component breakdown (EXP-03)**

| Component | Active | Raw score | Configured weight | Effective weight | Contribution |
| --- | --- | --- | --- | --- | --- |
| `ts_signal` (Time-Series Signal) | ✓ | `0.0006` | `0.3500` | `0.5833` | `0.0004` |
| `if_score` (Isolation Forest) | · | — | `0.4000` | `0.0000` | `0.0000` |
| `rule_score` (Rule Engine) | ✓ | `0.0000` | `0.2500` | `0.4167` | `0.0000` |

**EXP-04 payload (validated)**

```json
{
  "anomaly_score": 0.000367,
  "anomaly_threshold": 0.3,
  "is_anomaly": false,
  "severity": "none",
  "components": [
    {
      "name": "ts_signal",
      "label": "Time-Series Signal",
      "raw_score": 0.000629,
      "configured_weight": 0.35,
      "effective_weight": 0.583333,
      "weighted_contribution": 0.000367,
      "active": true
    },
    {
      "name": "if_score",
      "label": "Isolation Forest",
      "raw_score": null,
      "configured_weight": 0.4,
      "effective_weight": 0.0,
      "weighted_contribution": 0.0,
      "active": false
    },
    {
      "name": "rule_score",
      "label": "Rule Engine",
      "raw_score": 0.0,
      "configured_weight": 0.25,
      "effective_weight": 0.416667,
      "weighted_contribution": 0.0,
      "active": true
    }
  ],
  "forecast_explanation": {
    "actual": 135.505993,
    "forecast_mean": 135.719531,
    "forecast_std": 67.943133,
    "residual": -0.213538,
    "pct_deviation": -0.1573,
    "z_score": -0.0031,
    "direction": "below",
    "ci_breaches": {
      "95": false
    },
    "summary": "Actual total_cost (135.51) is 0.2% below the forecast (135.72), a deviation of 0.0 standard deviations."
  },
  "rule_explanation": {
    "threshold_breach": {
      "rule": "threshold_breach",
      "fired": false,
      "score": 0.0,
      "reason": "Value 135.51 within budget limit 1000.00."
    },
    "sudden_jump": {
      "rule": "sudden_jump",
      "fired": false,
      "score": 0.0,
      "reason": "Jump of -11.9% is below threshold 50.0%."
    },
    "sustained_increase": {
      "rule": "sustained_increase",
      "fired": false,
      "score": 0.0,
      "reason": "Only 0/3 periods met the 5.0% growth threshold."
    },
    "triggered_rules": [],
    "summary": "No rules triggered."
  }
}
```

### `missed_anomaly`

_True anomaly with the lowest score — verifies the explanation remains honest about ``is_anomaly = 0`` even when the label says the row should have been caught._

| Field | Value |
| --- | --- |
| Row index | `1523` |
| Label | `anomaly` |
| Anomaly type | `budget_breach` |
| Account / Service / Region | `acct-prod-1` / `BigQuery` / `us-central1` |
| Timestamp | `2026-03-05T11:00:00+00:00` |
| Cost (actual) | `338.31` |
| Forecast mean ± std | `337.07` ± `171.30` |
| Anomaly score | **`0.0008`** (threshold `0.3000`) |
| Verdict | `NOT flagged` (severity `none`) |

**Forecast vs actual (EXP-01)**

> Actual total_cost (338.31) is 0.4% above the forecast (337.07), a deviation of 0.0 standard deviations.

**Triggered rules (EXP-02)**

> No rules triggered.

**Component breakdown (EXP-03)**

| Component | Active | Raw score | Configured weight | Effective weight | Contribution |
| --- | --- | --- | --- | --- | --- |
| `ts_signal` (Time-Series Signal) | ✓ | `0.0015` | `0.3500` | `0.5833` | `0.0008` |
| `if_score` (Isolation Forest) | · | — | `0.4000` | `0.0000` | `0.0000` |
| `rule_score` (Rule Engine) | ✓ | `0.0000` | `0.2500` | `0.4167` | `0.0000` |

**EXP-04 payload (validated)**

```json
{
  "anomaly_score": 0.000847,
  "anomaly_threshold": 0.3,
  "is_anomaly": false,
  "severity": "none",
  "components": [
    {
      "name": "ts_signal",
      "label": "Time-Series Signal",
      "raw_score": 0.001452,
      "configured_weight": 0.35,
      "effective_weight": 0.583333,
      "weighted_contribution": 0.000847,
      "active": true
    },
    {
      "name": "if_score",
      "label": "Isolation Forest",
      "raw_score": null,
      "configured_weight": 0.4,
      "effective_weight": 0.0,
      "weighted_contribution": 0.0,
      "active": false
    },
    {
      "name": "rule_score",
      "label": "Rule Engine",
      "raw_score": 0.0,
      "configured_weight": 0.25,
      "effective_weight": 0.416667,
      "weighted_contribution": 0.0,
      "active": true
    }
  ],
  "forecast_explanation": {
    "actual": 338.310871,
    "forecast_mean": 337.066996,
    "forecast_std": 171.303696,
    "residual": 1.243875,
    "pct_deviation": 0.369,
    "z_score": 0.0073,
    "direction": "above",
    "ci_breaches": {
      "95": false
    },
    "summary": "Actual total_cost (338.31) is 0.4% above the forecast (337.07), a deviation of 0.0 standard deviations."
  },
  "rule_explanation": {
    "threshold_breach": {
      "rule": "threshold_breach",
      "fired": false,
      "score": 0.0,
      "reason": "Value 338.31 within budget limit 1000.00."
    },
    "sudden_jump": {
      "rule": "sudden_jump",
      "fired": false,
      "score": 0.0,
      "reason": "Jump of -5.8% is below threshold 50.0%."
    },
    "sustained_increase": {
      "rule": "sustained_increase",
      "fired": false,
      "score": 0.0,
      "reason": "Only 0/3 periods met the 5.0% growth threshold."
    },
    "triggered_rules": [],
    "summary": "No rules triggered."
  }
}
```

## Caveats

- TS-01 / ML-01 trained models are not yet in the registry. The forecast layer here is the same per-account μ/σ recipe MLQ-01 used; replace with a real `TimeSeriesBaselineModel` once one is trained, and re-run.
- `if_score` is intentionally NaN to demonstrate the graceful-degradation path. Once ML-01 is loaded, the breakdown for the same rows will gain an active IF component.
- Re-run after every EXP-01..04 change so this gallery and the API contract stay in sync — the Pydantic round-trip is the gate.
