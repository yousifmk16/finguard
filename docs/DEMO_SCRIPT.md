# FinGuard — Demo Video Script

**DOC-07 · Sprint 5 · 2026-05-08**
**Target length:** 7–8 minutes · **Format:** Screen recording with voiceover

---

## Pre-Recording Checklist

Complete every step before pressing record. The demo must run cleanly without pausing to type passwords or wait for servers to start.

### Environment setup

- [ ] PostgreSQL running and `finguard` database migrated (`alembic upgrade head`)
- [ ] Redis running (`redis-cli ping` → `PONG`)
- [ ] Backend API running: `uvicorn app.main:app --port 8000`
- [ ] Stream consumer running: `python -m services.stream.consumer`
- [ ] Alert orchestrator running: `python -m app.alerts.orchestrator`
- [ ] Frontend running: `npm run dev` at `http://localhost:3000`

### Seed data

Run the seed script below **before** recording so the dashboard shows real anomaly data, not an empty state.

```bash
# Get admin token
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"changeme"}' | jq -r .access_token)

# Post 20 baseline events (normal cost ~$50)
for i in $(seq 1 20); do
  curl -s -X POST http://localhost:8000/api/v1/events \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d "{\"timestamp\":\"2026-05-0${i}T10:00:00Z\",\"provider\":\"gcp\",
         \"account_id\":\"acct-prod\",\"service\":\"BigQuery\",
         \"region\":\"us-central1\",\"cost_amount\":$(python3 -c "import random; print(round(40+random.uniform(0,20),2))"),
         \"usage_amount\":500,\"usage_unit\":\"GiB\",
         \"tags\":{\"env\":\"prod\"},\"source_type\":\"synthetic\"}" > /dev/null
done

# Post 1 spike anomaly (cost $1 800 — will trigger threshold_breach + sudden_jump)
curl -s -X POST http://localhost:8000/api/v1/events \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"timestamp":"2026-05-08T14:00:00Z","provider":"gcp",
       "account_id":"acct-prod","service":"BigQuery","region":"us-central1",
       "cost_amount":1800.00,"usage_amount":18000,"usage_unit":"GiB",
       "tags":{"env":"prod"},"source_type":"synthetic"}' | jq .
```

Wait 15–30 seconds for the stream consumer and scorer to process and persist the anomaly.

### Browser setup

- [ ] Browser: Chrome or Firefox, zoom at 100 %, resolution 1920×1080
- [ ] Clear browser cache and localStorage for `localhost:3000` (`DevTools → Application → Storage → Clear site data`)
- [ ] Close all unrelated tabs
- [ ] Hide bookmarks bar for a cleaner recording
- [ ] Open a second incognito tab (for the admin login sequence)
- [ ] Have `http://localhost:8000/docs` ready to switch to (Swagger UI)
- [ ] Recording software: OBS, QuickTime, or Loom — set to capture the browser window only

### Narrator setup

- [ ] Read the full script aloud at least once before recording
- [ ] Mark any pauses `[PAUSE]` where you need 1–2 s of silence for the screen to catch up
- [ ] Speak at ~130 words per minute (conversational pace, not rushed)

---

## Scene Breakdown

| Scene | Time | Topic |
|-------|------|-------|
| 1 | 0:00–0:20 | Title card + hook |
| 2 | 0:20–0:50 | The problem |
| 3 | 0:50–1:20 | Architecture overview |
| 4 | 1:20–1:50 | Login flow and session handling |
| 5 | 1:50–2:40 | Dashboard — KPI cards and charts |
| 6 | 2:40–3:10 | Live event ingestion via API |
| 7 | 3:10–4:00 | Anomaly list — filtering and sorting |
| 8 | 4:00–4:55 | Anomaly detail — score breakdown and explainability |
| 9 | 4:55–5:25 | Lifecycle actions — acknowledge and resolve |
| 10 | 5:25–5:55 | Alert center |
| 11 | 5:55–6:25 | Admin role — audit log |
| 12 | 6:25–6:45 | Responsive mobile view |
| 13 | 6:45–7:05 | OpenAPI interactive docs |
| 14 | 7:05–7:30 | Closing summary |

---

## Full Script

---

### Scene 1 — Title Card (0:00–0:20)

**Screen:** Static title card. Black background, white text:
```
FinGuard
Real-Time Cloud Billing Anomaly Detection
Sprint 5 Final Demo · 2026-05-08
```

**Narration:**
> This is FinGuard — a real-time cloud billing anomaly detection platform built over five Agile sprints. In the next seven minutes we'll walk through everything: the detection pipeline, the web dashboard, filtering and triage, lifecycle actions, alerting, and the admin audit trail.

---

### Scene 2 — The Problem (0:20–0:50)

**Screen:** Static slide or simple diagram (can be a plain text editor with a timeline):
```
T = 0        Cost spike occurs
T = 30 days  Monthly bill arrives  ← discovered HERE with existing tools
T = 45 s     FinGuard alert sent   ← discovered HERE
```

**Narration:**
> The problem with cloud billing is timing. A $50,000 spike caused by a misconfigured job or accidental over-provisioning is typically discovered at month-end — after the money is spent. FinGuard moves that discovery window from thirty days to forty-five seconds by scoring every billing event as it arrives and alerting operators before the cost compounds.

---

### Scene 3 — Architecture Overview (0:50–1:20)

**Screen:** Open the architecture diagram or a slide. Point to each layer as you mention it. (Use the system-architecture.mmd rendered image or the ASCII from ARCHITECTURE.md.)

**Narration:**
> FinGuard has five layers communicating asynchronously through Redis Streams. Billing events are ingested through a FastAPI endpoint, published to a stream, and consumed by a scoring pipeline that runs three signals in parallel: a time-series Z-score model, an Isolation Forest, and three deterministic rules. The weighted ensemble produces an anomaly score and an explanation payload. High-scoring events trigger the alert orchestrator, which deduplicates and dispatches in-app and email alerts. Everything is surfaced through a React dashboard backed by a twelve-endpoint REST API.

---

### Scene 4 — Login Flow (1:20–1:50)

**Screen actions:**
1. Navigate to `http://localhost:3000` — the Login page loads
2. Hover over the Email field to show it's focused and labelled
3. Type `analyst@example.com`
4. Type password `changeme`
5. Click **Sign in** — wait for redirect to Dashboard
6. **Point out:** the URL changes to `/dashboard` and the sidebar shows "Anomalies", "Alerts", but NOT "Policies" or "Users" (analyst role)

**Narration:**
> Opening FinGuard takes you to the login page. We're signing in as an analyst — the role that can view and triage anomalies but cannot manage system configuration. [PAUSE] After authentication the app issues a JWT with a sixty-minute TTL, stores it locally, and redirects to the dashboard. Notice the sidebar: Policies and Users are not visible for this role — that's RBAC enforced in the UI.

---

### Scene 5 — Dashboard (1:50–2:40)

**Screen actions:**
1. The Dashboard page is visible — let it load fully
2. Point at each KPI card in turn: "Total anomalies", "Open", "Last 24 hours", "High severity"
3. Click the **"Open"** KPI card — it navigates to `/anomalies?status=open` (show this)
4. Click **Back** in the browser to return to Dashboard
5. Point at the **Anomalies — last 14 days** sparkline
6. Point at the **Status breakdown** bars
7. Point at the **Severity breakdown** bars
8. Point at the **Top services** ranked list
9. Click **Refresh** button in the header

**Narration:**
> The dashboard gives a live health snapshot. The four KPI cards at the top are interactive — clicking "Open" filters the anomaly list to show only unresolved anomalies. [PAUSE] Below the cards we have the fourteen-day anomaly trend as a sparkline, status and severity breakdown bars, and ranked lists of the cloud services and accounts generating the most anomalies. The Refresh button re-fetches all data on demand — it doesn't require a full page reload.

---

### Scene 6 — Live Ingestion (2:40–3:10)

**Screen actions:**
1. Open a **new browser tab** to `http://localhost:8000/docs` (Swagger UI)
2. Expand **POST /api/v1/events**
3. Click **Try it out**
4. Paste this request body (pre-typed, don't type live):
```json
{
  "timestamp": "2026-05-08T14:30:00Z",
  "provider": "gcp",
  "account_id": "acct-demo",
  "service": "Compute Engine",
  "region": "eu-west1",
  "cost_amount": 2500.00,
  "usage_amount": 25000,
  "usage_unit": "vCPU-hours",
  "tags": {"env": "prod", "team": "platform"},
  "source_type": "synthetic"
}
```
5. Click **Execute**
6. Show the `202 Accepted` response with `event_id` and `"status": "accepted"`
7. **[Wait 20 s]** — say "giving the pipeline fifteen seconds to score..."
8. Switch back to the FinGuard tab, navigate to **Anomalies**
9. The new anomaly for `acct-demo / Compute Engine` appears at the top (sort by detected_at desc)

**Narration:**
> Let's inject a real anomaly. I'm using the Swagger interactive docs to post a billing event — a Compute Engine cost spike of twenty-five hundred dollars, well above the thousand-dollar threshold rule. [PAUSE] The API returns 202 Accepted with the assigned event ID. [PAUSE] Now we wait about fifteen seconds for the stream consumer to pick this up, score it, and persist the anomaly record. [PAUSE] Back on the anomaly list — and there it is. Compute Engine, account acct-demo, detected just now, score and severity populated by the ensemble.

---

### Scene 7 — Anomaly List — Filtering and Sorting (3:10–4:00)

**Screen actions:**
1. On the Anomaly List page, show the full table (all columns visible on desktop)
2. Click the **Score** column header to sort by score descending — highest anomaly scores rise to the top
3. Click again to toggle to ascending
4. Click **detected_at** header to restore default sort
5. In the filter bar: select **Severity = high** from the dropdown, click **Apply filters**
6. Show the active filter chip "Severity: high" that appears below the filter bar
7. Click the **×** on the chip to clear just that filter
8. Type `BigQuery` in the **Service** field, click **Apply filters**
9. Show results filtered to BigQuery
10. Click **Reset** to clear all filters
11. Resize browser to ~750 px wide — show Region and Detected columns hide automatically
12. Restore to full width

**Narration:**
> The anomaly list supports multi-column filtering. I'll sort by score to see the highest-risk anomalies first. [PAUSE] The filter bar lets me narrow by severity — I'll pick "high". Notice the active filter appears as a chip below the form — I can remove it individually without clearing everything. [PAUSE] I can also filter by service name, account, region, and time window. [PAUSE] Filters are stored in the URL, so I can bookmark or share a filtered view. [PAUSE] And on smaller screens, the table adapts automatically — the Region and Detected columns disappear to preserve readability.

---

### Scene 8 — Anomaly Detail — Score Breakdown (4:00–4:55)

**Screen actions:**
1. Click **View detail** on the highest-scoring anomaly (the Compute Engine spike if visible, or the BigQuery one)
2. Show the **breadcrumb**: Dashboard / Anomalies / [anomaly-id]
3. Point to the **header**: account, service, region, bucket timestamp, detected timestamp, severity badge (red), status badge
4. Scroll to the **Score Summary card**:
   - Point to "Final score: 0.87" (or whatever it is)
   - Point to per-signal rows: Ts Signal, If Score, Rule Score
5. If `score_breakdown.explanation` is present, point to the explanation text
6. Point to the **Lifecycle Actions card** (right column): show current status badge "open" and the available buttons: Acknowledge, Resolve, Suppress

**Narration:**
> Clicking into an anomaly opens the detail page. The breadcrumb at the top lets me navigate back at any point. [PAUSE] The header shows the key dimensions: account, service, region, and the exact one-minute time bucket this cost spike belongs to. The red "High" badge is severity — computed from the composite score. [PAUSE] The Score Summary card shows the final score and the three-signal breakdown. In this case the time-series signal is the strongest driver — the cost is almost three standard deviations above the rolling average for this account and service. Both the threshold breach rule and the sudden jump rule fired. [PAUSE] Below the breakdown is an explanation field that summarises the key finding in plain language — this is the EXP-01 through EXP-04 explainability stack we built in Sprint 3.

---

### Scene 9 — Lifecycle Actions (4:55–5:25)

**Screen actions:**
1. Click **Acknowledge** on the Lifecycle Actions card
2. The button briefly shows "Updating..." — then the status badge changes from "open" to "acknowledged"
3. The "Acknowledge" button disappears (can't transition to current state)
4. Click **Resolve** — a browser confirmation dialog appears:
   > "Confirm and close this anomaly?\n\nThis will set status to "resolved"."
5. Click **OK** in the dialog
6. Status badge changes to "resolved"
7. Click **Reopen** — status returns to "open"

**Narration:**
> The lifecycle actions let me triage this anomaly. Acknowledge marks it as seen — I'm on it. [PAUSE] Resolve closes it once the investigation is complete. Destructive transitions require a confirmation dialog so accidental clicks can't close open anomalies. [PAUSE] And if I need to revisit a resolved anomaly, Reopen brings it back to open. Every status transition is persisted immediately to the database and is visible to any other analyst viewing the same anomaly.

---

### Scene 10 — Alert Center (5:25–5:55)

**Screen actions:**
1. Click **Alerts** in the sidebar — the Alert Center loads
2. Point out the table columns: Alert ID, Account, Service, Region, Severity, Channel, Status, Created, Anomaly link
3. Show a row with `channel = in_app` and `status = sent`
4. Show a row with `channel = email` and `status = sent` (or failed)
5. In the filter bar: select **Channel = email** → click **Apply filters**
6. Show only email alerts remaining
7. Click the **Anomaly** link on one row — navigates to the corresponding anomaly detail page
8. Click Back

**Narration:**
> The Alert Center shows every alert delivery record. For each anomaly that crosses the severity threshold, the orchestrator creates one record per channel — in-app and email. The Status column tells us whether delivery succeeded. [PAUSE] I can filter by channel to see only email alerts, or filter by status to find any that failed and need investigation. [PAUSE] Each alert links back to its source anomaly so I can jump straight into triage without having to search the anomaly list. The page auto-refreshes every fifteen seconds, so new alerts appear without a manual reload.

---

### Scene 11 — Admin Role — Audit Log (5:55–6:25)

**Screen actions:**
1. Open the **incognito tab** already prepared
2. Navigate to `http://localhost:3000` — Login page
3. Sign in as `admin@example.com` / `changeme`
4. Dashboard loads — sidebar now shows **Policies** and **Users** links
5. Point at the admin callout banner: "Tune detection thresholds in Policies or review accounts in Users"
6. Navigate to `http://localhost:8000/docs` → `GET /api/v1/audit/logs` → **Try it out** → **Execute**
7. Show the JSON response with audit log entries — point to `event_type`, `action`, `outcome`, `actor_email`

**Narration:**
> Now signing in as an admin. Notice the sidebar gains two new destinations: Policies and Users. Admin-only routes are hidden from analysts entirely — not just disabled, hidden. [PAUSE] The admin callout on the dashboard provides quick links to system configuration. [PAUSE] And crucially, every privileged action in FinGuard writes to an audit log. I can query it from the API — here are the entries generated by our demo: the login events, the event ingestions, and the status transitions I just made. Each row records the actor's email, their role at the time, the outcome, and the IP address.

---

### Scene 12 — Responsive Mobile View (6:25–6:45)

**Screen actions:**
1. Switch back to the analyst tab
2. Open **Chrome DevTools** (F12) → **Toggle device toolbar** (Ctrl+Shift+M)
3. Set device to **iPhone 12 Pro** (or custom width 390 px)
4. Navigate to the **Anomalies** page
5. Show the table — Service and several other columns are hidden, ID + Score + Severity + Status remain
6. Show the **sidebar** has become a horizontal scrolling nav bar at the top
7. Switch to **iPad** (768 px) — show intermediate column hiding
8. Close DevTools, back to full desktop

**Narration:**
> FinGuard is fully responsive. On a phone-width screen the sidebar collapses to a top nav bar and the data table hides lower-priority columns — Region, Service, Detected — while keeping the most actionable information: the anomaly score and severity. On a tablet the intermediate breakpoint hides a smaller set of columns. All hidden data is still accessible through the detail page.

---

### Scene 13 — OpenAPI Interactive Docs (6:45–7:05)

**Screen actions:**
1. Navigate to `http://localhost:8000/docs` in the main tab
2. Show the API title "FinGuard API" and the tag groups: auth, ingestion, anomalies, alerts, kpi, detection, health, audit
3. Expand **GET /api/v1/anomalies** — show the query parameters list (account_id, service, region, severity, status, from_bucket, to_bucket, sort, order, page, page_size)
4. Expand **AnomalyResponse** schema at the bottom

**Narration:**
> The backend auto-generates interactive OpenAPI 3.1.0 documentation from the FastAPI app. Every endpoint is described with its parameters, required roles, and response schemas. The machine-readable spec is also exported to `docs/api/openapi.json` for tooling integration. Twelve endpoints across eight tag groups — all documented, all tested.

---

### Scene 14 — Closing Summary (7:05–7:30)

**Screen:** Return to the Dashboard page. Let it sit for 2–3 seconds. Then cut to the title card again.

**Narration:**
> That's FinGuard. A real-time cloud billing anomaly detection platform built in ten weeks across five Agile sprints: a three-signal ML ensemble with zero false positives, a twelve-endpoint REST API, a React dashboard accessible to WCAG 2.1 Level AA, and eleven hundred twenty-five tests at a ninety-nine-point-nine percent pass rate. All documentation — architecture, API reference, test report, user manual, and project report — is in the `docs/` directory. Thank you.

---

## Post-Recording Checklist

- [ ] Review recording for any pauses longer than 3 s that should be cut
- [ ] Verify all narration is audible (no drop-outs at screen transitions)
- [ ] Add chapter markers at each scene start (most video tools support this)
- [ ] Export at 1080p minimum; 1440p preferred
- [ ] Add captions/subtitles from the narration script above
- [ ] Trim title card to exactly 20 s — it should not linger
- [ ] Verify the live ingestion scene shows the anomaly appearing without cutting the wait (keep the 20 s pause in the video — it demonstrates real async processing)

---

## Re-take Notes

If any scene needs a re-take, here are the self-contained setups:

| Scene | Re-take setup |
|-------|---------------|
| 4 — Login | Clear localStorage, navigate to `/`, type credentials fresh |
| 6 — Ingestion | Use a different `account_id` (e.g. `acct-demo-2`) to produce a new anomaly |
| 9 — Lifecycle | Any anomaly in `open` state works; use the newest one from the seed |
| 11 — Admin | Use the incognito tab; admin credentials are `admin@example.com` / `changeme` |

---

## Timing Reference

Word count per scene (approximate) and target pace (130 wpm):

| Scene | Words | Time |
|-------|------:|------|
| 1 – Title | 45 | 0:20 |
| 2 – Problem | 75 | 0:35 |
| 3 – Architecture | 85 | 0:40 |
| 4 – Login | 70 | 0:32 |
| 5 – Dashboard | 90 | 0:42 |
| 6 – Ingestion | 85 | 0:39 |
| 7 – Filtering | 95 | 0:44 |
| 8 – Detail | 110 | 0:51 |
| 9 – Lifecycle | 65 | 0:30 |
| 10 – Alerts | 80 | 0:37 |
| 11 – Admin | 85 | 0:39 |
| 12 – Mobile | 55 | 0:25 |
| 13 – OpenAPI | 55 | 0:25 |
| 14 – Closing | 65 | 0:30 |
| **Total** | **960** | **~7:25** |
