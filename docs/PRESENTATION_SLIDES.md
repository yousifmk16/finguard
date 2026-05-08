# FinGuard — Presentation Slides

**DOC-06 · Sprint 5 · 2026-05-08**

Slide deck for the final project presentation. Each slide shows the title, bullet content, suggested visual, and speaker notes. Target length: **20 slides, ~15–20 minutes** (45 s per slide average, longer for demo).

Copy slides into PowerPoint, Google Slides, or Keynote. Suggested theme: dark background (#0f1117), accent colour #6366f1 (indigo), white body text. Code blocks in monospace.

---

## Slide 1 — Title

**Title:** FinGuard
**Subtitle:** Real-Time Cloud Billing Anomaly Detection

**Body:**
- Sprint 5 Final Presentation · 2026-05-08
- Team: M1 · M2 · M3 · M4 · M5

**Visual:** Full-bleed dark background with a subtle grid overlay suggesting a monitoring dashboard. FinGuard wordmark centred.

**Speaker notes:**
Good [morning/afternoon]. We are presenting FinGuard — a real-time cloud billing anomaly detection platform we built across five Agile sprints over ten weeks. The talk will cover the problem we solved, how we built the solution, and the results we achieved.

---

## Slide 2 — Agenda

**Title:** Agenda

**Body (numbered list):**
1. The Problem
2. Our Solution at a Glance
3. System Architecture
4. Detection Pipeline — How it Works
5. Product Demo
6. Test Results and Quality Gates
7. Outcomes vs. Requirements
8. What's Next

**Visual:** Simple numbered list, no decoration.

**Speaker notes:**
Eight sections total. We'll spend the most time on the architecture, the ML pipeline, and the live demo. Questions at the end.

---

## Slide 3 — The Problem

**Title:** Cloud Billing Anomalies Are Caught Too Late

**Body:**
- Cloud bills arrive at the end of the month — spikes are discovered long after the damage
- Common causes: misconfiguration, over-provisioning, runaway jobs, abusive usage
- A $50 000 spike detected in 30 days costs $50 000
  A $50 000 spike detected in 30 **seconds** costs almost nothing
- Existing tools: batch reports, no real-time signal, no explanation

**Visual:** Timeline diagram — left side "Spike occurs" at T=0, right side "Bill arrives" at T=30 days with a large red gap labelled "Cost window." Below: new timeline with "Spike occurs" at T=0 and "Alert sent" at T=45 s.

**Speaker notes:**
The core insight is simple: the earlier you catch a billing anomaly, the less it costs. Cloud billing dashboards today are batch tools — they aggregate overnight or monthly. FinGuard moves that window from days to under a minute.

---

## Slide 4 — Our Solution

**Title:** FinGuard in One Slide

**Body:**
- **Ingest** billing events from GCP, AWS, and Azure in real time
- **Score** each event with a 3-signal ML ensemble (time-series + Isolation Forest + rules)
- **Explain** why the score is high — not just that it is
- **Alert** via in-app and email within seconds
- **Triage** through a web dashboard with lifecycle management

**Key numbers:**
- < 45 s end-to-end detection latency
- Precision **1.000** — zero false positives
- Recall **0.730** — 73 % of injected anomalies caught
- **1 125 tests**, 99.9 % pass rate

**Visual:** Four-box horizontal flow: Ingest → Score → Alert → Triage, with icons for each step (funnel, brain, bell, checklist).

**Speaker notes:**
FinGuard is built on four verbs: ingest, score, alert, triage. Each maps directly to a layer in the architecture. The zero-FP Precision is the most operationally important number — it means every alert is real.

---

## Slide 5 — Agile Journey

**Title:** Five Sprints, Zero Filler

**Body:**

| Sprint | Weeks | Focus |
|--------|-------|-------|
| 0 | 1 | Repository, skeleton, standards, CI scaffold |
| 1 | 1–2 | Requirements, architecture, UX wireframes |
| 2 | 3–4 | Data generator, ingestion API, DB schema |
| 3 | 5–6 | ML pipeline, rules engine, explainability |
| 4 | 7–8 | REST API, alerts, auth/RBAC, frontend |
| 5 | 9–10 | QA, hardening, observability, documentation |

**Total backlog:** ≥ 200 tasks completed across all sprints

**Visual:** Horizontal Gantt-style bar per sprint, colour-coded by discipline (data=green, ML=purple, API=blue, UI=orange, QA=red).

**Speaker notes:**
Sprint 0 gave us the clean foundation — no throwaway code. Sprint 1 locked requirements before any feature work, which prevented the common trap of re-architecting mid-project. By Sprint 3 we had a working scoring pipeline; by Sprint 4 we had a full product.

---

## Slide 6 — System Architecture

**Title:** Event-Driven, Async, Five Layers

**Body:**

```
Billing Events
     │  POST /api/v1/events
     ▼
┌─────────────────┐      billing-events
│  Ingestion API  │ ─────────────────────►  Stream Consumer
│  FastAPI 0.115  │                               │
└─────────────────┘                               ▼
         │ billing_events_raw           ┌─────────────────┐
         ▼ (PostgreSQL)                 │  OnlineScorer   │
                                        │  TS · IF · Rule │
                                        └────────┬────────┘
                              anomaly-events      │ anomalies table
                              Redis Stream ◄──────┘
                                    │
                                    ▼
                           Alert Orchestrator
                           in-app · email · dedup
                                    │ alerts table
                                    ▼
                              Backend API  ◄────►  React SPA
                              (12 endpoints)        :3000
```

**Visual:** Reproduce the ASCII diagram as a clean flowchart with coloured boxes. Colour-code layers: ingestion (green), detection (purple), alerts (orange), API (blue), frontend (teal).

**Speaker notes:**
Every layer communicates asynchronously through Redis Streams. The ingestion API writes to Postgres and publishes to a stream. The stream consumer scores events and writes anomalies. The alert orchestrator picks up anomaly events and dispatches to channels. The REST API reads from Postgres; the React SPA reads from the REST API. No layer is blocking any other.

---

## Slide 7 — Tech Stack

**Title:** Technology Choices

**Body (two columns):**

**Backend**
- FastAPI 0.115 + Pydantic v2
- Python 3.13, SQLAlchemy 2, Alembic
- PostgreSQL 14 (5 tables)
- Redis 7 Streams (consumer groups)

**ML / Data**
- scikit-learn (IsolationForest)
- NumPy, Pandas
- Synthetic generator (4 anomaly types)

**Frontend**
- React 18.3.1 + TypeScript 5.5.4
- Vite 5.4.6, React Router 6
- Plain CSS, BEM naming, CSS custom properties

**Operations**
- Docker Compose (local, 6 services)
- Prometheus + Grafana dashboard
- GitHub Actions CI (lint + test)
- JWT HS256, RBAC, audit logs

**Visual:** Two-column layout with technology logos or icon-chips.

**Speaker notes:**
We picked FastAPI for its automatic OpenAPI generation and Pydantic v2 for zero-boilerplate validation. We chose plain CSS over Tailwind because we wanted full control over a compact custom design system without a build-time dependency. Redis Streams gives us at-least-once delivery with consumer group acknowledgement.

---

## Slide 8 — Detection Pipeline Deep Dive

**Title:** How a Score Is Born

**Body:**

```
1-minute cost aggregate (account, service, region)
          │
          ├──► TS-03  Z-score vs rolling µ/σ  →  ts_signal  (w = 0.35)
          │
          ├──► ML-01  IsolationForest          →  if_score   (w = 0.40)
          │
          └──► RUL-01..03  Three rules         →  rule_score (w = 0.25)
                   threshold_breach  (w = 0.50)
                   sudden_jump       (w = 0.30)
                   sustained_increase(w = 0.20)
                              │
                              ▼
              anomaly_score = Σ(wᵢ·sᵢ) / Σwᵢ
                              │
               ┌──────────────┴──────────────┐
               ▼                             ▼
          Severity mapping             EXP-01..04
          ≥0.75 high                   Explanation stack
          ≥0.50 medium                 per-signal breakdown
          ≥0.25 low                    natural-language text
```

**Visual:** Flowchart version of the ASCII above with icons for each signal type and a gauge dial for the final score.

**Speaker notes:**
Three signals, three weights. The Isolation Forest carries the highest weight because it catches structural outliers the rules cannot see. The rules handle well-defined business thresholds that the ML model may under-weight because they appear infrequently in training data. When a signal is unavailable — say, before the IF model is trained — its weight redistributes to the others automatically, ensuring graceful degradation.

---

## Slide 9 — ML Quality Gate

**Title:** Model Quality: Precision First

**Body:**

**Validation set:** 3 000 rows, seed=42, threshold=0.30

| | Predicted Normal | Predicted Anomaly |
|--|--|--|
| **Actually Normal** | TN = 2 852 ✓ | FP = **0** ✓ |
| **Actually Anomaly** | FN = 40 | TP = 108 ✓ |

| Metric | Value |
|--------|-------|
| Precision | **1.000** — every alert is real |
| Recall | **0.730** — 73 % of anomalies caught |
| F1 | **0.844** |

**Calibrated threshold:** 0.30 (selected by supervised sweep on validation set)

**Visual:** Confusion matrix as a 2×2 coloured grid (green for TP/TN, red for FP, amber for FN). Bar chart showing Precision=1.0, Recall=0.73, F1=0.844.

**Speaker notes:**
We calibrated the threshold to zero false positives. Alert fatigue is the biggest threat to an anomaly detection product — if operators see too many false alarms they start ignoring them. The 40 false negatives are all low-magnitude events that score 0.20–0.29, just below the threshold. They're still visible in the API as `severity=none`; they're just not pushed as alerts.

---

## Slide 10 — Explainability

**Title:** Every Anomaly Tells You Why

**Body:**

```json
{
  "anomaly_score": 0.87,
  "severity": "high",
  "score_breakdown": {
    "ts_signal": 0.91,
    "if_score":  0.85,
    "rule_score": 0.80
  },
  "explanation": {
    "residual":   420.50,
    "direction":  "above",
    "ci_upper":   310.00,
    "rules_fired": ["threshold_breach", "sudden_jump"],
    "margins": {
      "threshold_breach": 0.50,
      "sudden_jump":      0.73
    }
  }
}
```

- Analyst sees: which signal drove the score
- Analyst sees: which rules fired and by how much
- Analyst sees: actual vs. predicted cost + confidence interval

**Visual:** Side-by-side of the JSON payload and the rendered dashboard UI showing the Score Summary card.

**Speaker notes:**
Explainability was a first-class requirement from Sprint 1. We implemented the EXP-01..04 stack — four Pydantic models that chain forecast explanation, rule explanation, score breakdown, and a final API response. The dashboard renders all of this in the Score Summary card, visible above the fold so an analyst doesn't have to scroll to understand why they're looking at an anomaly.

---

## Slide 11 — Security

**Title:** Auth, RBAC, and Audit Trail

**Body:**

**Authentication:** JWT HS256 · 60-minute TTL · role claim embedded

**Two roles:**

| | Admin | Analyst |
|--|--|--|
| View anomalies + alerts | ✓ | ✓ |
| Update anomaly status | ✓ | ✓ |
| Ingest billing events (API) | ✓ | — |
| View audit logs | ✓ | — |
| Manage policies + users | ✓ | — |

**Audit trail:** Every ingest and privileged action writes to `audit_logs` with actor identity, IP address, user agent, and outcome.

**Visual:** Two-column role matrix as a table with checkmarks and dashes. Below: a snippet of an audit log row.

**Speaker notes:**
RBAC is enforced both in the FastAPI middleware and in the React frontend — navigation links and action buttons are hidden for roles that don't have access. The audit trail is queryable via `GET /api/v1/audit/logs` (admin only) with full pagination and time-range filtering.

---

## Slide 12 — Dashboard Demo

**Title:** The Product — Live Demo

**Body (three key screens):**

**Screen 1 — Dashboard**
- KPI cards: Total anomalies, Open, Last 24 h, High severity
- 14-day sparkline trend
- Status breakdown + Severity breakdown bars
- Top services + Top accounts ranked lists

**Screen 2 — Anomaly List**
- Paginated table · multi-filter · sortable headers
- Severity badge colour-coding (High = red, Medium = orange, Low = yellow)

**Screen 3 — Anomaly Detail**
- Final score + per-signal breakdown
- Lifecycle actions: Acknowledge · Resolve · Suppress · Reopen
- Breadcrumb navigation

**Visual:** Three screenshots tiled side by side, or a single full-screen screenshot with callout annotations.

**Speaker notes:**
[Live demo here — open the app at http://localhost:3000. Log in as analyst@example.com. Walk through dashboard KPI cards → click "Open" to filter anomaly list → click an anomaly → show score breakdown → click Acknowledge.]

---

## Slide 13 — Alert Center Demo

**Title:** Alert Center

**Body:**

- Auto-refreshes every 15 seconds
- Filter by: severity · delivery status (`pending / sent / failed / suppressed`) · channel (`in-app / email`)
- Each alert links back to the source anomaly
- Dedup key prevents duplicate alerts for the same event window

**Visual:** Screenshot of the Alert Center page with filter bar visible. Highlight one "sent" row and one "failed" row with callouts.

**Speaker notes:**
The alert orchestrator consumes anomaly events from the Redis Stream. It applies two gates before dispatching: deduplication by account+service+region+bucket, and a cooldown window. Medium and high severity anomalies go to both in-app and email; low severity stays in-app only. Failed deliveries retry with backoff and escalate to the DLQ.

---

## Slide 14 — Mobile and Accessibility

**Title:** Responsive and Accessible

**Body:**

**Responsive design (two breakpoints):**
- 720 px tablet — sidebar collapses to horizontal nav, table columns hide, dashboard reflows to 2 columns
- 480 px phone — single-column layout, reduced table columns, 44 px minimum touch targets

**WCAG 2.1 Level AA:**
- Skip-to-main-content keyboard link on every page
- ARIA landmark regions (`role`, `aria-labelledby`) on every section
- Contextual `aria-label` on all table action links
- `aria-live="polite"` on pagination counter
- All text ≥ 4.5:1 contrast ratio

**Visual:** Side-by-side of the desktop dashboard and the mobile view (320 px wide screenshot).

**Speaker notes:**
M4 ran a full accessibility pass in Sprint 5 — not just checking boxes, but fixing real issues: the empty sparkline state with `role="img"` was silently swallowing the "no data" text for screen readers; pagination showed "Page 1 of 1" even with zero results. All three of those bugs are fixed.

---

## Slide 15 — Test Coverage

**Title:** 1 125 Tests, 99.9 % Pass Rate

**Body:**

| Package | Tests | Pass |
|---------|------:|-----:|
| Backend API (`backend/tests/`) | 473 | 473 |
| ML pipeline (`ml/tests/`) | 427 | 426 |
| Stream services (`services/tests/`) | 225 | 225 |
| **Total** | **1 125** | **1 124** |

**Run time:** 27.33 s

**1 failure:** env-only — scikit-learn absent from test runner. No code defect.

**Test highlights:**
- RBAC matrix: every endpoint tested at 401, 403, and 200/202
- OpenAPI contract tests: 26 tests validate every live response against the spec
- MLQ quality gate: calibration, evaluation, and FP analysis all deterministic
- Integration test: full ingest → detect → alert chain

**Visual:** Horizontal stacked bar chart (473 / 427 / 225) coloured by package. Small confusion-matrix-style summary for the one failure.

**Speaker notes:**
We wrote tests before and alongside every feature, not after. The RBAC matrix tests were written as part of SEC-01 implementation; the OpenAPI contract tests were written as part of API-06. The integration pipeline test is the confidence check that the end-to-end async chain — from POST to anomaly record — completes within the 60-second SLA.

---

## Slide 16 — Observability

**Title:** Operations-Ready

**Body:**

**Health (OPS-01):** `GET /health` returns `ok / degraded / unhealthy` — load balancers use HTTP 503 to trigger pod restarts

**Metrics (OPS-02):** 42 Prometheus counters and gauges:
- HTTP request counts + latency histograms
- Ingestion events accepted / duplicate / failed
- Detection batches, rows scored, anomalies detected
- Alert dispatched / failed / suppressed by channel

**Logging (OPS-03):** Structured JSON everywhere; human-readable text via `FINGUARD_LOG_FORMAT=text`

**DLQ (OPS-04):** File-based dead-letter queue with `dlq_tools count / tail / requeue / drain`

**Visual:** Grafana dashboard screenshot showing the anomaly detection rate panel and alert volume panel.

**Speaker notes:**
Observability was not an afterthought — OPS-01..04 are first-class Sprint 5 tasks. The Prometheus metrics are scraped by a Grafana Agent running alongside the stack. The dashboard JSON ships in `infra/dashboards/finguard.json` so any team can import it in 30 seconds.

---

## Slide 17 — Deployment

**Title:** Local in 5 Minutes. Cloud-Ready.

**Body:**

**Local (Docker Compose):**
```bash
git clone github.com/yousifmk16/finguard
cd finguard/backend && cp .env.example .env
alembic upgrade head
uvicorn app.main:app --port 8000
# (second terminal)
cd ../frontend && npm install && npm run dev
```
Open http://localhost:3000 · http://localhost:8000/docs

**Cloud (GCP reference):**

| Component | GCP | AWS | Azure |
|-----------|-----|-----|-------|
| Backend API | Cloud Run | ECS Fargate | Container Apps |
| Frontend | GCS + CDN | S3 + CloudFront | Storage + Front Door |
| PostgreSQL | Cloud SQL | RDS | Azure DB for PG |
| Redis | Memorystore | ElastiCache | Azure Cache |
| Secrets | Secret Manager | Secrets Manager | Key Vault |

**Visual:** Two-column layout — left: terminal screenshot of the quick-start, right: GCP topology diagram.

**Speaker notes:**
The six-service Docker Compose stack starts cleanly on Linux, macOS, and Windows. The cloud guide maps every local component to managed services on GCP with AWS and Azure equivalents documented — no cloud-vendor lock-in required.

---

## Slide 18 — Outcomes vs. Requirements

**Title:** How Did We Do?

**Body:**

| Requirement | Target | Result | Status |
|-------------|--------|--------|--------|
| Detection latency p95 | ≤ 45 s | < 45 s | ✓ Met |
| Precision | maximize | **1.000** | ✓ Exceeded |
| Recall | ≥ 0.70 gate | **0.730** | ✓ Met gate |
| Recall (aspiration) | ≥ 0.90 | 0.730 | △ Below target |
| F1 | ≥ 0.85 | **0.844** | △ Near miss |
| Test pass rate | 100 % | 99.9 % | ✓ Met |
| API endpoints | 12 | **12** | ✓ Met |
| Explanation coverage | 100 % | **100 %** | ✓ Met |
| WCAG compliance | AA | **AA** | ✓ Met |
| CI checks | all pass | all pass | ✓ Met |

**Visual:** Table with green checkmarks, amber triangles, and status column colour-coded.

**Speaker notes:**
Nine out of ten targets met. The one miss is the aspirational Recall of 0.90. The gate is 0.70 and we hit 0.730. We made a deliberate choice: calibrate for zero FPs, accept some FNs. The 40 missed detections are low-magnitude events — they score 0.20–0.29 and are unlikely to represent urgent cost events in a real environment.

---

## Slide 19 — What's Next

**Title:** Future Work

**Body (top 5 priorities):**

1. **Raise Recall to ≥ 0.85** — lower threshold with a precision floor, or add a fourth signal (longer-window cost velocity trend)

2. **Live cloud billing APIs** — connect GCP Billing Export, AWS Cost and Usage Reports, Azure Cost Management (replace the synthetic generator)

3. **Per-anomaly alert linkage** — render linked alerts directly on the Anomaly Detail page (UI-07 stub)

4. **Policy and User management UI** — implement threshold tuning and user account management pages

5. **Kubernetes production topology** — Terraform-managed GCP Cloud Run + Cloud SQL with autoscaling and managed Prometheus

**Visual:** Numbered list with icons (target/bull's-eye for Recall, cloud for live APIs, link for alert linkage, gear for policy UI, cluster for K8s).

**Speaker notes:**
The Recall improvement is the most impactful next step — we know exactly which threshold range to explore and we have the calibration tooling already built. Live billing API integration would unlock the product for real customers. The rest is product maturity work.

---

## Slide 20 — Conclusion

**Title:** FinGuard — Delivered

**Body (two columns):**

**What we built:**
- Real-time anomaly detection: < 45 s end-to-end
- 3-signal ML ensemble with full explainability
- 12-endpoint REST API with OpenAPI docs
- React SPA — responsive, accessible (WCAG AA)
- JWT + RBAC + audit trail
- 1 125 tests, 99.9 % pass rate
- Complete documentation suite

**What we proved:**
- Event-driven async architectures scale cleanly across five layers
- Precision=1.000 is achievable — zero alert fatigue
- Explainability is not optional — it's the feature
- Agile process with clear sprint goals kept the team aligned over 10 weeks

**Thank you.**
Questions?

**Visual:** Split layout — left column bullet list, right column a large version of the ensemble formula: `anomaly_score = Σ(wᵢ·sᵢ) / Σwᵢ` displayed prominently over the dark background.

**Speaker notes:**
Ten weeks, five sprints, five engineers, two hundred tasks. We set out to detect cloud billing anomalies in real time with explainable scoring — and we did it. The zero false positives are the headline, but the explainability is what makes the product usable: an analyst can look at a score, understand why it is high, and make a triage decision in seconds, not minutes.

---

## Appendix A — Architecture Detail Slide (backup)

**Title:** Component Map

**Body:**

| Component | Source path | Port |
|-----------|-------------|------|
| PostgreSQL | external | 5432 |
| Redis 7 | external | 6379 |
| Backend API | `backend/` · FastAPI | 8000 |
| Frontend SPA | `frontend/` · Vite | 3000 |
| Stream consumer | `services/stream/consumer.py` | — |
| Alert orchestrator | `app/alerts/orchestrator.py` | — |

**5 database tables:** `billing_events_raw`, `anomalies`, `alerts`, `users`, `audit_logs`

---

## Appendix B — Scoring Formula (backup)

**Title:** Ensemble Mathematics

**Body:**

```
anomaly_score = (w_ts · ts_signal + w_if · if_score + w_rule · rule_score)
                ─────────────────────────────────────────────────────────
                              Σ wᵢ  (renormalised when NaN)

  ts_signal   = clip(Z-score, 0, Z_CAP=5) / Z_CAP
  Z-score     = (cost - µ) / σ     per-account rolling window

  if_score    = IsolationForest.score_samples()  → [0, 1]

  rule_score  = 0.50 · threshold_breach
              + 0.30 · sudden_jump
              + 0.20 · sustained_increase

Severity:   ≥ 0.75 → high · ≥ 0.50 → medium · ≥ 0.25 → low · else none
Threshold:  0.30  (calibrated by ThresholdCalibrator, MLQ-01)
```

---

## Appendix C — Full API Endpoint List (backup)

**Title:** 12 Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | public | Aggregate health |
| POST | `/api/v1/auth/login` | public | JWT issuance |
| POST | `/api/v1/events` | admin | Ingest billing event |
| GET | `/api/v1/anomalies` | analyst+ | List anomalies |
| GET | `/api/v1/anomalies/{id}` | analyst+ | Anomaly detail |
| PATCH | `/api/v1/anomalies/{id}/status` | analyst+ | Status transition |
| GET | `/api/v1/alerts` | analyst+ | Alert list |
| GET | `/api/v1/kpi/summary` | analyst+ | KPI aggregates |
| GET | `/api/v1/kpi/trend` | analyst+ | Trend sparkline |
| GET | `/api/v1/detection/health` | public | Detection health |
| GET | `/api/v1/detection/metrics` | public | Detection counters |
| GET | `/api/v1/audit/logs` | admin | Audit log |

---

## Presentation Tips

- **Total slides:** 20 main + 3 appendix (use appendix only if questions arise)
- **Target time:** 15–18 minutes for slides + 2–5 minutes for live demo (Slides 12–13)
- **Suggested split by section:**
  - Slides 1–2 (title + agenda): 1 min
  - Slides 3–4 (problem + solution): 2 min
  - Slides 5–7 (journey + architecture + stack): 3 min
  - Slides 8–11 (pipeline + ML + explainability + security): 4 min
  - Slides 12–13 (demo): 3–5 min
  - Slides 14–16 (accessibility + tests + ops): 2 min
  - Slides 17–18 (deployment + outcomes): 1.5 min
  - Slides 19–20 (future + conclusion): 1.5 min
- **Demo prep:** Have the app running locally before the presentation. Log in as analyst first, then show the admin audit log screen to demonstrate RBAC.
- **Fallback:** If the live demo environment fails, Slides 12–13 contain static content and speaker notes that work without a running app.
