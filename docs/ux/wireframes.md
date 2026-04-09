# UX Wireframes

Date: 2026-04-09
Owner: M4
Sprint: S1

This document captures low-fidelity wireframes for the first dashboard-facing user flows in `finguard`. The layouts align with:

- `REQ-03` personas and roles
- anomaly list/detail/filter workflows from `FR-07`
- lifecycle actions from `FR-08`
- alert policies from `REQ-08`
- login and RBAC requirements from `FR-01` and `ARC-07`

## UX-01 Dashboard Wireframe

Purpose:
- Give Admin and Analyst users a single monitoring surface for KPIs, anomaly volume, severity mix, and investigation entry points.

Primary users:
- Analyst
- Admin

Key API dependencies:
- `GET /api/v1/kpis`
- `GET /api/v1/anomalies`
- `GET /api/v1/alerts`

States to support:
- loading
- empty dataset
- filtered results
- degraded backend/API error

```text
+--------------------------------------------------------------------------------------------------+
| FinGuard                                                                 User: Analyst | Logout |
+----------------------+-------------------------------------------------------------------+-------+
| Navigation           | Top Bar                                                           |       |
| - Dashboard          | [ Global search......... ] [ Time: Last 24h v ] [ Provider: GCP ] |       |
| - Anomalies          +-------------------------------------------------------------------+       |
| - Alerts             | KPI Cards                                                         |       |
| - Policies (Admin)   | [ Open Anomalies ] [ High Severity ] [ Alerts Sent ] [ p95 Lat ] |       |
| - Users (Admin)      +-------------------------------------------------------------------+       |
| - Settings           | Charts / Trends                                                   |       |
|                      | [ Spend Trend ---------------- ] [ Severity Split ------------- ] |       |
|                      | [ Top Accounts at Risk ------- ] [ Alert Volume --------------- ] |       |
|                      +-------------------------------------------------------------------+       |
| Quick Filters        | Active Anomalies Table                                            |       |
| [Severity v]         | [ID] [Account] [Provider] [Score] [Severity] [Status] [Time]      |       |
| [Status v]           | A-104  acct-prod   gcp      .91     High      New      10:24      |       |
| [Provider v]         | A-103  acct-dev    gcp      .78     Medium    Notified 09:58      |       |
| [Account v]          | A-099  acct-fin    aws      .66     Low       Ack      09:11      |       |
| [Reset]              |                                              [View detail ->]     |       |
+----------------------+-------------------------------------------------------------------+-------+
```

Notes:
- Dashboard should default to GCP-first filters while preserving provider-agnostic controls.
- KPI cards should reflect near-real-time health and anomaly counts rather than deep report views.
- Admin-only destinations remain visible only for users with elevated role claims.

## UX-02 Anomaly Detail Wireframe

Purpose:
- Support triage, investigation, explanation review, and lifecycle action updates for a single anomaly.

Primary users:
- Analyst
- Admin

Key API dependencies:
- `GET /api/v1/anomalies/{id}`
- `PATCH /api/v1/anomalies/{id}/status`

States to support:
- loading
- action in progress
- missing anomaly / `404`
- concurrent status change warning

```text
+--------------------------------------------------------------------------------------------------+
| Breadcrumbs: Dashboard / Anomalies / A-104                                    [Back to list]   |
+--------------------------------------------------------------------------------------------------+
| Header                                                                                           |
| A-104 | High Severity | Status: New | Account: acct-prod | Provider: gcp | Detected: 10:24 UTC  |
+--------------------------------------+-----------------------------------------------------------+
| Score Summary                        | Lifecycle Actions                                         |
| Final Score: 0.91                    | [Acknowledge] [Dismiss] [Resolve]                        |
| TS: 0.94  IF: 0.82  Rule: 0.96       | Note: [ Investigation comment......................... ] |
| Explanation: Cost exceeded baseline  | Audit preview: last action / actor / timestamp          |
+--------------------------------------+-----------------------------------------------------------+
| Timeline / Spend Context                                                                         |
| [ Current spike vs baseline chart ------------------------------------------------------------- ] |
+--------------------------------------------------------------------------------------------------+
| Evidence / Dimensions                                                                           |
| Service: BigQuery   Region: us-central1   Usage Unit: GB   Source: synthetic                    |
| Tags: env=prod, team=finance, owner=platform                                                    |
+--------------------------------------------------------------------------------------------------+
| Related Alerts                                                                                  |
| [Alert ID] [Channel] [Status] [Sent At] [Cooldown Window]                                       |
| AL-21      in-app     delivered  10:25      active                                              |
| AL-22      email      attempted  10:25      active                                              |
+--------------------------------------------------------------------------------------------------+
```

Notes:
- The score breakdown must stay visible above the fold because explainability is a core product promise.
- Lifecycle controls should enforce RBAC and state transition rules from `REQ-09`.
- Audit visibility is important for privileged changes and handoffs between analysts.

## UX-03 Alert Center Wireframe

Purpose:
- Provide a queue-oriented workspace for alert review, prioritization, acknowledgment, and cooldown awareness.

Primary users:
- Analyst
- Admin

Key API dependencies:
- `GET /api/v1/alerts`
- linked navigation to `GET /api/v1/anomalies/{id}`

States to support:
- unread-first queue
- deduplicated alert groups
- empty queue
- notification delivery failure state

```text
+--------------------------------------------------------------------------------------------------+
| Alert Center                                                                  [Auto-refresh: On] |
+--------------------------------------------------------------------------------------------------+
| Filters: [Channel v] [Severity v] [Delivery Status v] [Unread Only] [Cooldown Active] [Reset]  |
+-----------------------------+--------------------------------------------------------------------+
| Alert Queue                 | Selected Alert / Group                                             |
| High (4)                    | Alert: AL-21                                                       |
| > acct-prod spike           | Severity: High   Channel: in-app   Delivery: delivered            |
| > acct-data burst           | Linked anomaly: A-104 [Open detail ->]                            |
|                             |                                                                    |
| Medium (8)                  | Summary                                                            |
| > acct-dev threshold        | Spend spike detected with matching rule hit and email attempt.    |
| > acct-ops increase         |                                                                    |
|                             | Delivery Timeline                                                  |
| Low (5)                     | 10:24 anomaly created                                              |
| > acct-sandbox drift        | 10:25 in-app delivered                                             |
| > acct-test burst           | 10:25 email attempted                                              |
|                             |                                                                    |
|                             | Actions                                                            |
|                             | [Mark read] [Acknowledge anomaly] [Mute group] [Escalate]         |
+-----------------------------+--------------------------------------------------------------------+
```

Notes:
- The queue should group by severity first because medium/high alerts trigger operator attention and email policy.
- Deduplication visibility matters so users understand why multiple events may collapse into one alert group.
- Alert center should not duplicate full anomaly analysis; it should route to the anomaly detail view for deep triage.

## UX-04 Login and Role Flow Wireframe

Purpose:
- Define the secure entry path, role-aware landing, and authorization guard behavior for Admin and Analyst users.

Primary users:
- Admin
- Analyst

Key architecture dependencies:
- JWT authentication
- RBAC enforcement at protected routes and actions
- audit logging for login and privileged actions

States to support:
- valid login
- invalid credentials
- expired session
- unauthorized route/action

```text
+-------------------------------------------------------------+
| FinGuard                                                    |
| Real-Time Cloud Billing Anomaly Detection                   |
+-------------------------------------------------------------+
| Email     [ analyst@company.com......................... ]  |
| Password  [ ............................................ ]  |
| [ Sign In ]                                                 |
|                                                             |
| Error state: Invalid credentials or expired session         |
+-------------------------------------------------------------+
                 |
                 v
+-----------------------------------+      +-----------------------------------+
| Role Resolution                   |      | Session Guard                     |
| JWT issued                        |----->| validates token + role claims     |
| role = analyst | admin            |      | redirects if token missing/expired |
+-----------------------------------+      +-----------------------------------+
                 |                                      |
        +--------+--------+                             |
        |                 |                             v
        v                 v              +--------------------------------------+
+-------------------+  +-------------------+  | Unauthorized Action / Route     |
| Analyst Landing   |  | Admin Landing     |  | "You do not have permission."   |
| Dashboard         |  | Dashboard         |  | [Return to dashboard]           |
| Anomalies         |  | Anomalies         |  +----------------------------------+
| Alerts            |  | Alerts            |
| no policy/users   |  | policy + users    |
+-------------------+  +-------------------+
```

Notes:
- Analyst and Admin can share the same dashboard shell; navigation and actions differ by role.
- Role checks should happen both in the UI and in backend-protected endpoints.
- Expired sessions should redirect back to login with a clear reason instead of failing silently.

## Global UX Rules

- Always show explicit `loading`, `empty`, and `error` states.
- Keep anomaly severity visually prominent on list, detail, and alert queue surfaces.
- Preserve a clear handoff from summary views to detail views.
- Default filter presets should favor GCP while leaving room for AWS and Azure expansion.
- Avoid exposing admin navigation or privileged actions to Analyst users.
