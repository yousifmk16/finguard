# FinGuard User Manual

**Version:** 0.1.0 · **Sprint:** 5 · **Task:** DOC-04
**Audience:** Operations analysts and platform administrators

---

## Overview

FinGuard is a real-time cloud billing anomaly detection platform. It monitors GCP, AWS, and Azure billing events, automatically scores cost spikes and unusual usage patterns, and surfaces them through a web dashboard with alerting, lifecycle management, and explainable scoring.

### Roles

| Role | What they can do |
|------|-----------------|
| **Analyst** | View Dashboard, Anomalies, Alerts. Update anomaly lifecycle status. |
| **Admin** | Everything an Analyst can do, plus: ingest events via the API, access audit logs, manage Policies and Users. |

---

## 1. Signing In

Open the FinGuard web app in a browser (default: `http://localhost:3000`).

1. Enter your registered **email** and **password**.
2. Click **Sign in**.

On success you are redirected to the Dashboard. On failure, an error message appears below the form:

| Error | Cause |
|-------|-------|
| "Invalid email or password." | Credentials do not match any registered account. |
| "Authentication service is unavailable." | Backend is not reachable — try again in a moment. |
| "Could not reach the server." | Network connectivity issue. |

**Session expiry:** Sessions last 60 minutes. When your session expires you are automatically redirected to the login page with the message *"Your session expired. Please sign in again."*

**Returning to your page:** After signing in, the app returns you to the page you were trying to reach before the session ended.

---

## 2. Navigation

The sidebar on the left provides access to all sections. On small screens the sidebar collapses to a horizontal scrolling nav bar at the top.

| Link | Who sees it | Description |
|------|-------------|-------------|
| **Dashboard** | All | KPI overview and anomaly trend charts |
| **Anomalies** | All | Paginated anomaly list with filters |
| **Alerts** | All | Alert delivery records |
| **Policies** | Admin only | Detection threshold and alert policy settings |
| **Users** | Admin only | User account management |
| **Settings** | All | Personal account settings |

A **"Skip to main content"** link is available at the top of every page for keyboard navigation — press Tab once after loading to reveal it.

---

## 3. Dashboard

The Dashboard is the default landing page after login. It gives a live snapshot of anomaly health.

### KPI Cards

Four metric cards appear at the top of the page:

| Card | What it shows |
|------|---------------|
| **Total anomalies** | All-time count of detected anomalies. Clicking navigates to the full anomaly list. |
| **Open** | Anomalies still in the `open` state, requiring attention. Clicking filters the anomaly list to `status=open`. |
| **Last 24 hours** | Anomalies detected in the last 24 hours. |
| **High severity** | Anomalies with severity `high`. Clicking filters the anomaly list to `severity=high`. |

Cards show `...` while loading and `—` if data is unavailable.

### Charts

| Chart | Description |
|-------|-------------|
| **Anomalies — last 14 days** | Sparkline bar chart showing daily anomaly counts over the trailing 14 days. The total count for the window appears below the chart. |
| **Status breakdown** | Horizontal bar chart showing the split between Open, Acknowledged, Resolved, and Suppressed anomalies. |
| **Severity breakdown** | Horizontal bar chart showing the split between High, Medium, and Low severity anomalies. |
| **Top services** | Ranked list of cloud services with the highest anomaly counts. |
| **Top accounts** | Ranked list of cloud accounts with the highest anomaly counts. |

### Refreshing

Click **Refresh** in the page header to reload all KPI data and charts. The button shows "Refreshing..." while the request is in flight.

### Admin callout

Admin users see a banner with quick links to **Policies** and **Users** for common administrative tasks.

---

## 4. Anomalies

### Anomaly List

Navigate to **Anomalies** in the sidebar to see the full paginated list. The table shows:

| Column | Description |
|--------|-------------|
| Anomaly ID | Short identifier (first 8 characters of the UUID). Clicking navigates to the detail page. |
| Account | Cloud account / project identifier |
| Service | Cloud service (e.g. BigQuery, GCS, EC2) |
| Region | Cloud region (e.g. us-central1) |
| Score | Composite anomaly score from 0.00 to 1.00 |
| Severity | `high` / `medium` / `low` / `none` — color coded |
| Status | Current lifecycle status |
| Detected | When the anomaly was first detected |
| Action | Link to the detail page |

On tablet screens the Region and Detected columns are hidden to conserve space. On phone screens Service is also hidden. All data is still accessible via the detail page.

#### Filtering

The filter bar above the table provides:

| Filter | Options |
|--------|---------|
| Severity | `none` / `low` / `medium` / `high` |
| Status | `open` / `acknowledged` / `resolved` / `suppressed` |
| Sort | `Detected at` / `Bucket` / `Score` / `Severity` |
| Order | `Descending` / `Ascending` |

Filters are reflected in the URL — you can bookmark or share a filtered view. Click **Reset filters** to clear all active filters.

#### Pagination

Results are paginated 50 per page by default. Use **Previous** and **Next** buttons to navigate. The page counter reads "Page N of M". When there are no results the pagination controls are hidden and the table shows an empty-state message.

#### Sorting

Click any column header with an arrow icon to sort by that column. Click again to toggle between ascending and descending order.

---

### Anomaly Severity

Severity is determined by the composite anomaly score:

| Severity | Score range | Visual |
|----------|-------------|--------|
| **High** | ≥ 0.75 | Red badge |
| **Medium** | 0.50 – 0.74 | Orange badge |
| **Low** | 0.25 – 0.49 | Yellow badge |
| **None** | < 0.25 | Grey badge |

---

### Anomaly Detail Page

Click **View detail** on a list row, or the anomaly ID link, to open the detail page.

#### Header

Shows the full anomaly UUID, severity badge, status badge, and a summary of:
- **Account** — cloud account / project
- **Service** — cloud service name
- **Region** — cloud region
- **Bucket** — the 1-minute time window this anomaly covers
- **Detected** — when the anomaly was first persisted

A **Back to list** link appears in both the breadcrumb and the top-right corner.

#### Score Summary

Shows the composite **Final score** and, where available, the per-signal score breakdown:

| Signal | Weight | What it measures |
|--------|--------|-----------------|
| **Ts Signal** | 35 % | Deviation from the rolling average cost (Z-score, normalized to 0–1) |
| **If Score** | 40 % | Isolation Forest outlier score |
| **Rule Score** | 25 % | Blended deterministic rule signal (threshold breach, sudden jump, sustained increase) |

The `Final score = (0.35 × ts_signal + 0.40 × if_score + 0.25 × rule_score)`. Signals weight-renormalize automatically if one is unavailable (e.g. no trained model). An explanation text may appear below the breakdown summarizing why the score is high.

#### Lifecycle Actions

Shows the current status and buttons to transition the anomaly to a new state.

##### Status lifecycle

```
open  →  acknowledged  →  resolved
  \                          /
   ↘    suppressed          /
         ↑________________/
                ↑
              open  (reopen from any state)
```

| Action | New status | When to use | Confirmation required |
|--------|-----------|-------------|----------------------|
| **Acknowledge** | `acknowledged` | Mark as seen — you are actively investigating | No |
| **Resolve** | `resolved` | Investigation complete, anomaly is closed | Yes |
| **Suppress** | `suppressed` | Known false-positive — silence future alerts for this pattern | Yes |
| **Reopen** | `open` | Re-open a resolved or suppressed anomaly for further review | No |

The button for the current state is hidden — you cannot transition to the same state. Actions that require confirmation show a browser dialog before proceeding. While the update is in flight all buttons show as disabled and the active button shows "Updating...".

If the update fails, a red error banner appears with a **Dismiss** button to clear it.

#### Related Alerts

Shows alert delivery records linked to this anomaly. Alert linkage by `anomaly_id` is planned for a future release; for now, use the **Alerts** page and filter by account/service/region to find related alerts.

---

## 5. Alert Center

Navigate to **Alerts** in the sidebar to view alert delivery records. Alerts are generated automatically when an anomaly is detected and exceed the alert policy thresholds.

### Alert List

| Column | Description |
|--------|-------------|
| Alert ID | Short identifier. |
| Account | Cloud account |
| Service | Cloud service |
| Region | Cloud region |
| Severity | Severity inherited from the source anomaly |
| Channel | `In-app` or `Email` |
| Status | Delivery status |
| Created | When the alert was created |
| Sent | When the alert was successfully delivered (blank if not yet sent) |
| Anomaly | Link to the source anomaly detail page |

On tablet screens Region, Created, and Sent are hidden. On phone screens Service and Channel are also hidden.

The alert list auto-refreshes every 15 seconds while the page is in the foreground.

### Alert Status

| Status | Meaning |
|--------|---------|
| `pending` | Alert queued but not yet dispatched |
| `sent` | Successfully delivered to the channel |
| `failed` | Delivery attempt failed (see error detail in the API) |
| `suppressed` | Alert was suppressed by the deduplication / cooldown policy |

### Filtering

| Filter | Options |
|--------|---------|
| Severity | `none` / `low` / `medium` / `high` |
| Status | `pending` / `sent` / `failed` / `suppressed` |
| Channel | `In-app` / `Email` |

Filters are URL-persistent and can be bookmarked.

### Alert Channels

| Channel | Description |
|---------|-------------|
| **In-app** | Alert visible within the FinGuard web UI |
| **Email** | Alert sent to configured recipient email addresses via SMTP |

---

## 6. Policies (Admin only)

Accessible only to users with the `admin` role. Manage detection thresholds and alert routing policies.

> **Note:** Policy configuration UI is scaffolded in Sprint 5. Full policy management arrives in a future sprint.

---

## 7. Users (Admin only)

Accessible only to users with the `admin` role. View and manage user accounts and role assignments.

> **Note:** User management UI is scaffolded in Sprint 5. Full user administration arrives in a future sprint.

---

## 8. Settings

Personal account settings page. Available to all roles.

---

## 9. Understanding Anomaly Scores

FinGuard uses a three-signal weighted ensemble to score each 1-minute cost aggregate.

### How the score is calculated

```
anomaly_score = (0.35 × ts_signal + 0.40 × if_score + 0.25 × rule_score)
```

All signals are normalized to the range [0, 1] before blending. If a signal is unavailable (for example, the Isolation Forest model has not been trained yet), its weight is redistributed proportionally to the remaining signals.

### The three signals

**Time-series signal (TS-03)** — compares the current cost against the rolling mean and standard deviation for the same account/service/region. A large upward deviation produces a high signal.

**Isolation Forest (ML-01)** — a machine learning model trained on a clean baseline of cost data. It assigns a high score to points that look structurally different from the training distribution.

**Rule signal (RUL-01/02/03)** — three deterministic rules, blended together:

| Rule | Trigger | Weight within rule signal |
|------|---------|--------------------------|
| Threshold breach | Cost exceeds $1 000 in the current bucket | 50 % |
| Sudden jump | Cost increased by more than 50 % vs the previous bucket | 30 % |
| Sustained increase | Three consecutive rising buckets | 20 % |

### Severity thresholds

| Score | Severity |
|-------|----------|
| ≥ 0.75 | High |
| 0.50 – 0.74 | Medium |
| 0.25 – 0.49 | Low |
| < 0.25 | None |

---

## 10. Keyboard Navigation and Accessibility

FinGuard is built to WCAG 2.1 Level AA.

- **Skip link:** Press Tab once on any page to reveal a "Skip to main content" link and bypass the navigation sidebar.
- **Keyboard navigation:** All interactive elements (buttons, links, form fields, filter dropdowns) are reachable by Tab and operable by Enter or Space.
- **Screen reader support:** All tables have column headers with `scope` attributes. Severity badges carry descriptive text. Status banners use `role="alert"` for live-region announcements. Pagination announces the current page with `aria-live="polite"`.
- **Colour contrast:** All text meets the WCAG 4.5:1 contrast ratio requirement against the dark background.

---

## 11. Error States

All pages handle the following states explicitly:

| State | What you see |
|-------|-------------|
| **Loading** | Skeleton or "Loading..." indicator |
| **Empty** | "No results" message with a prompt to adjust filters |
| **Network error** | Red error banner with a **Try again** button |
| **Not found (404)** | "Anomaly could not be found." with a back link |
| **Forbidden (403)** | "You do not have permission to view this page." with a return link |

---

## 12. Session Management

- Sessions last **60 minutes** from login.
- The session is stored in `localStorage` in your browser. Closing the tab or browser does not immediately end the session — you can reopen the app and continue until the token expires.
- In private browsing mode, session storage may not persist across tabs.
- Signing out clears the local session immediately. Navigate to the sign-in page and your credentials will be required again.

---

## 13. Frequently Asked Questions

**Q: Why is my anomaly score high but severity is "medium"?**
Score ranges determine severity. A score of 0.74 is at the top of the medium range. Check the score breakdown in the detail page to see which signal is driving the score.

**Q: Why are some score breakdown fields missing?**
The Isolation Forest score (`if_score`) is only available after the model has been trained on a baseline dataset. Before the first training run, that weight is redistributed to the time-series and rule signals.

**Q: I suppressed an anomaly but I'm still getting alerts for the same account.**
Suppression silences the anomaly record itself. New anomalies for the same account/service/region will still be detected and scored independently. If you want to prevent alerts for a recurring pattern, use the Policies page to raise the alert threshold for that account or service (Admin only).

**Q: The alert list shows "failed" — what does that mean?**
The alert delivery channel encountered an error (for example, an SMTP connection failure). The system retries failed alerts. If alerts remain in the `failed` state, check the backend logs or contact your platform administrator.

**Q: My session expired while I was in the middle of a status update.**
If the token expired between when you opened the page and when you clicked the action button, you will see a network or authorization error. Sign in again — the anomaly will still be in its pre-update state.

**Q: Can I bookmark a filtered anomaly view?**
Yes. Filters are stored in the URL query string, so any filtered view can be bookmarked or shared directly.
