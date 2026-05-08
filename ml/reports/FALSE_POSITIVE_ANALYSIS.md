# MLQ-03 — False-Positive Analysis

> Generated 2026-05-08T13:09:20.690960+00:00.
> Run via `python -m ml.src.evaluation.false_positive_analysis`.
> Machine-readable: [`false_positive_analysis.json`](false_positive_analysis.json).
> Headline metrics live in [`MODEL_EVALUATION_REPORT.md`](MODEL_EVALUATION_REPORT.md) (MLQ-02).

## Headline counts

Evaluated at `anomaly_threshold = 0.3000` (source: `threshold_calibration.json` (MLQ-01)).

| Metric | Value |
| --- | --- |
| Precision | **`1.0000`** |
| Recall | `0.7297` |
| False positive rate | **`0.0000`** |
| TP / FP / FN / TN | `108` / **`0`** / `40` / `2852` |
| Normals (n) / Anomalies (n) | `2,852` / `148` |

_No false positives at the current threshold. The borderline section below shows how much margin the threshold has._

## Realised false positives at current threshold

_(none — precision is 1.0 at this threshold)_

## Borderline normals (closest to flipping into FPs)

These are the **highest-scoring true negatives**. They are the rows that
would convert into false positives first if the threshold drifted down.
The gap between their scores and the current threshold is the precision
margin.

| # | score | cost | account | service | region | type | timestamp |
|---|---|---|---|---|---|---|---|
| 1 | `0.2651` | `45.67` | `acct-dev-1` | `Compute Engine` | `us-east1` | `normal` | `2026-01-04T16:00:00+00:00` |
| 2 | `0.2443` | `52.74` | `acct-dev-1` | `BigQuery` | `us-central1` | `normal` | `2026-01-07T15:00:00+00:00` |
| 3 | `0.2352` | `538.51` | `acct-prod-1` | `Compute Engine` | `us-central1` | `normal` | `2026-05-02T06:00:00+00:00` |
| 4 | `0.2337` | `537.20` | `acct-prod-1` | `BigQuery` | `europe-west1` | `normal` | `2026-05-01T05:00:00+00:00` |
| 5 | `0.2305` | `57.40` | `acct-dev-1` | `BigQuery` | `us-central1` | `normal` | `2026-01-20T15:00:00+00:00` |
| 6 | `0.2301` | `139.99` | `acct-prod-1` | `Cloud Storage` | `europe-west1` | `normal` | `2026-01-06T17:00:00+00:00` |
| 7 | `0.2296` | `57.73` | `acct-dev-1` | `Compute Engine` | `us-central1` | `normal` | `2026-01-20T19:00:00+00:00` |
| 8 | `0.2275` | `142.18` | `acct-prod-1` | `Compute Engine` | `us-east1` | `normal` | `2026-01-13T17:00:00+00:00` |
| 9 | `0.2264` | `58.81` | `acct-dev-1` | `BigQuery` | `us-central1` | `normal` | `2026-01-04T22:00:00+00:00` |
| 10 | `0.2264` | `143.19` | `acct-prod-1` | `Cloud Storage` | `us-east1` | `normal` | `2026-01-06T22:00:00+00:00` |

## False-positive curve under threshold sweep

How FP count and precision evolve as the threshold moves. Use this to
quote the *precision margin*: the lowest threshold at which precision is
still acceptable.

| Threshold | Flagged | FP | TP | Precision | FP rate (vs normals) |
|---|---|---|---|---|---|
| `0.050` | 2,090 | 1963 | 127 | `0.0608` | `0.6883` |
| `0.100` | 1,269 | 1156 | 113 | `0.0890` | `0.4053` |
| `0.150` | 591 | 478 | 113 | `0.1912` | `0.1676` |
| `0.200` | 198 | 85 | 113 | `0.5707` | `0.0298` |
| `0.250` | 112 | 1 | 111 | `0.9911` | `0.0004` |
| `0.300` | 108 | 0 | 108 | `1.0000` | `0.0000` ← current |
| `0.350` | 104 | 0 | 104 | `1.0000` | `0.0000` |
| `0.400` | 99 | 0 | 99 | `1.0000` | `0.0000` |
| `0.450` | 94 | 0 | 94 | `1.0000` | `0.0000` |
| `0.500` | 89 | 0 | 89 | `1.0000` | `0.0000` |
| `0.550` | 69 | 0 | 69 | `1.0000` | `0.0000` |
| `0.600` | 65 | 0 | 65 | `1.0000` | `0.0000` |
| `0.700` | 56 | 0 | 56 | `1.0000` | `0.0000` |
| `0.800` | 48 | 0 | 48 | `1.0000` | `0.0000` |

## False-positive risk by slice

For each dimension, ranked by mean `anomaly_score` *over normals only*.
Slices with high mean / p95 normal scores are where a future FP is most
likely to appear if anything shifts upstream.

### `account_id`

| value | n (normal) | FP @ current | mean score | p95 score | max score |
|---|---|---|---|---|---|
| `acct-dev-1` | 944 | 0 | `0.0909` | `0.1966` | `0.2651` |
| `acct-prod-1` | 953 | 0 | `0.0878` | `0.1875` | `0.2352` |
| `acct-prod-2` | 955 | 0 | `0.0855` | `0.1830` | `0.2247` |

### `service`

| value | n (normal) | FP @ current | mean score | p95 score | max score |
|---|---|---|---|---|---|
| `BigQuery` | 934 | 0 | `0.0893` | `0.1840` | `0.2443` |
| `Cloud Storage` | 942 | 0 | `0.0880` | `0.1897` | `0.2301` |
| `Compute Engine` | 976 | 0 | `0.0870` | `0.1893` | `0.2651` |

### `region`

| value | n (normal) | FP @ current | mean score | p95 score | max score |
|---|---|---|---|---|---|
| `us-central1` | 1,004 | 0 | `0.0905` | `0.1889` | `0.2443` |
| `europe-west1` | 915 | 0 | `0.0884` | `0.1895` | `0.2337` |
| `us-east1` | 933 | 0 | `0.0851` | `0.1841` | `0.2651` |

## Missed detections (false-negative complement)

A pure FP-only view is misleading when FP=0 by construction; the inverse
side of the same threshold is the FN set. This section is provided for
audit completeness and for triaging which anomaly types deserve a
score-recipe upgrade.

### Per-anomaly-type miss rate

| Type | Total | Missed | Miss rate | Mean score | Min score | Max score |
|---|---|---|---|---|---|---|
| `budget_breach` | 50 | 35 | `0.7000` | `0.1931` | `0.0015` | `0.9118` |
| `spike` | 98 | 5 | `0.0510` | `0.7350` | `0.2007` | `1.0000` |

### Near-threshold misses (just below the cut-off)

These anomalies almost flipped — they are the cheapest wins for any
recall-improving change.

| # | score | cost | account | service | region | type | timestamp |
|---|---|---|---|---|---|---|---|
| 1 | `0.2693` | `457.32` | `acct-prod-2` | `Compute Engine` | `us-central1` | `spike` | `2026-01-07T20:00:00+00:00` |
| 2 | `0.2626` | `224.93` | `acct-dev-1` | `Cloud Storage` | `europe-west1` | `spike` | `2026-01-04T19:00:00+00:00` |
| 3 | `0.2613` | `224.48` | `acct-dev-1` | `Compute Engine` | `us-east1` | `spike` | `2026-01-11T16:00:00+00:00` |
| 4 | `0.2438` | `439.29` | `acct-prod-2` | `BigQuery` | `europe-west1` | `spike` | `2026-01-01T19:00:00+00:00` |
| 5 | `0.2007` | `508.96` | `acct-prod-1` | `Cloud Storage` | `us-central1` | `spike` | `2026-01-05T21:00:00+00:00` |
| 6 | `0.0859` | `410.61` | `acct-prod-1` | `BigQuery` | `us-east1` | `budget_breach` | `2026-03-06T06:00:00+00:00` |
| 7 | `0.0581` | `308.00` | `acct-prod-2` | `Compute Engine` | `europe-west1` | `budget_breach` | `2026-03-04T16:00:00+00:00` |
| 8 | `0.0581` | `308.00` | `acct-prod-2` | `BigQuery` | `europe-west1` | `budget_breach` | `2026-03-04T12:00:00+00:00` |
| 9 | `0.0581` | `308.00` | `acct-prod-2` | `Cloud Storage` | `europe-west1` | `budget_breach` | `2026-03-06T07:00:00+00:00` |
| 10 | `0.0581` | `308.00` | `acct-prod-2` | `Cloud Storage` | `us-east1` | `budget_breach` | `2026-03-06T04:00:00+00:00` |

### Deeply missed anomalies (lowest scores)

These anomalies are nowhere near the threshold and indicate a *score
recipe* gap, not a *threshold* gap.

| # | score | cost | account | service | region | type | timestamp |
|---|---|---|---|---|---|---|---|
| 1 | `0.0015` | `338.31` | `acct-prod-1` | `BigQuery` | `us-central1` | `budget_breach` | `2026-03-05T11:00:00+00:00` |
| 2 | `0.0037` | `333.89` | `acct-prod-1` | `BigQuery` | `us-central1` | `budget_breach` | `2026-03-05T02:00:00+00:00` |
| 3 | `0.0054` | `332.41` | `acct-prod-1` | `Compute Engine` | `us-central1` | `budget_breach` | `2026-03-06T00:00:00+00:00` |
| 4 | `0.0060` | `331.90` | `acct-prod-1` | `Cloud Storage` | `us-east1` | `budget_breach` | `2026-03-05T23:00:00+00:00` |
| 5 | `0.0138` | `325.28` | `acct-prod-1` | `BigQuery` | `europe-west1` | `budget_breach` | `2026-03-06T13:00:00+00:00` |
| 6 | `0.0153` | `323.95` | `acct-prod-1` | `BigQuery` | `us-central1` | `budget_breach` | `2026-03-05T01:00:00+00:00` |
| 7 | `0.0166` | `351.31` | `acct-prod-1` | `BigQuery` | `us-east1` | `budget_breach` | `2026-03-06T01:00:00+00:00` |
| 8 | `0.0219` | `318.32` | `acct-prod-1` | `Cloud Storage` | `us-central1` | `budget_breach` | `2026-03-05T13:00:00+00:00` |
| 9 | `0.0247` | `358.20` | `acct-prod-1` | `Cloud Storage` | `us-east1` | `budget_breach` | `2026-03-05T10:00:00+00:00` |
| 10 | `0.0328` | `365.18` | `acct-prod-1` | `Compute Engine` | `europe-west1` | `budget_breach` | `2026-03-05T05:00:00+00:00` |

## Caveats

- The validation set and threshold are identical to MLQ-02. Re-run this
  analysis whenever MLQ-02 is re-run so the two reports stay aligned.
- Score recipe is rules / residual-only. Once TS-01 / ML-01 trained
  models contribute, the *score distribution* on this exact validation
  set will shift; the FP curve below should be re-derived rather than
  carried over.
- Validation set is fully synthetic. Re-run from a labeled production
  sample once available — the workflow is unchanged.
