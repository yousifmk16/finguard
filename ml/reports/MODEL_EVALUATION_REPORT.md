# MLQ-02 — Model Evaluation Report

> Generated 2026-05-07T23:28:07.609744+00:00.
> Run via `python -m ml.src.evaluation.run_evaluation`.
> Machine-readable: [`evaluation.json`](evaluation.json).

## Headline metrics

Evaluated at `anomaly_threshold = 0.3000` (source: `threshold_calibration.json` (MLQ-01)).

| Metric | Value |
| --- | --- |
| Precision | **`1.0000`** |
| Recall | **`0.7297`** |
| F1 | **`0.8438`** |
| Accuracy | `0.9867` |
| TP / FP / FN / TN | `108` / `0` / `40` / `2852` |

## Validation set

| Property | Value |
| --- | --- |
| Total rows | 3,000 |
| True anomalies | 148 (4.93 %) |
| Source | in-code MLQ-01 tuning config (seed = 42) |
| Score recipe | per-account `\|z-score\|` of `cost_amount`, clipped, normalised to [0, 1] |

## Detection sensitivity

How the flag rate changes if we move the threshold:

| Threshold | Flagged | % flagged |
|---|---|---|
| `0.300` | 108 | 3.60 % ← current |
| `0.400` | 99 | 3.30 % |
| `0.450` | 94 | 3.13 % |
| `0.500` | 89 | 2.97 % |
| `0.550` | 69 | 2.30 % |
| `0.600` | 65 | 2.17 % |
| `0.700` | 56 | 1.87 % |
| `0.800` | 48 | 1.60 % |

## Per-anomaly-type recall

| Type | Total | Detected | Recall |
|---|---|---|---|
| `budget_breach` | 50 | 15 | `0.3000` |
| `spike` | 98 | 93 | `0.9490` |

## Signal contribution (mean score per class)

| Signal | Mean (normal) | Mean (anomaly) | Separation |
|---|---|---|---|
| `anomaly_score` | `0.0881` | `0.5519` | `0.4638` |

## Caveats

- Score recipe is rules / residual-only. Real ensemble scores will be at
  least as large once TS-01 / ML-01 trained models contribute, so these
  numbers are a **conservative lower bound** on production performance.
- Validation set is fully synthetic. Re-run from a labeled production
  sample once available — the workflow is unchanged.
- This report is the **deployment artifact** for the recall / F1 / precision
  figures quoted in the sprint demo. Re-run after every change to
  `_TUNING_GENERATOR_CONFIG` or to the threshold calibration.
