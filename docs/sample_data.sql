-- FinGuard Sample Data
-- Generated: 2026-05-09
-- Load AFTER applying db_schema.sql (or alembic upgrade head).
-- Passwords below are bcrypt hashes of the literal string shown in comments.

-- ---------------------------------------------------------------------------
-- users  (role: admin | analyst)
-- ---------------------------------------------------------------------------
INSERT INTO users (user_id, email, hashed_password, role, is_active) VALUES
(
    'aaaaaaaa-0001-0001-0001-aaaaaaaaaaaa',
    'admin@finguard.dev',
    -- password: AdminPass1!
    '$2b$12$KIXc3oSaLuqzpFpAqK9uCOq1Gv3P.y5F8wWjP1xL7mZaR2kTqH3Oi',
    'admin',
    true
),
(
    'aaaaaaaa-0002-0002-0002-aaaaaaaaaaaa',
    'analyst@finguard.dev',
    -- password: AnalystPass1!
    '$2b$12$9cVNjZlL1lN3mNQaF5xHR.uBZdT6eJkYmX2bP8wSdA0QzKvCqF1Ma',
    'analyst',
    true
);

-- ---------------------------------------------------------------------------
-- billing_events_raw
-- ---------------------------------------------------------------------------
INSERT INTO billing_events_raw
    (event_id, "timestamp", provider, account_id, service, region,
     cost_amount, usage_amount, usage_unit, tags, source_type, ingested_at)
VALUES
(
    'bbbbbbbb-0001-0001-0001-bbbbbbbbbbbb',
    '2026-04-01 00:00:00+00',
    'aws', 'acct-001', 'EC2', 'us-east-1',
    12.500000, 100.000000, 'Hrs',
    '{"env": "prod", "team": "platform"}', 'api',
    '2026-04-01 00:05:00+00'
),
(
    'bbbbbbbb-0002-0002-0002-bbbbbbbbbbbb',
    '2026-04-01 01:00:00+00',
    'aws', 'acct-001', 'S3', 'us-east-1',
    0.023000, 23000.000000, 'GB',
    '{"env": "prod", "team": "data"}', 'api',
    '2026-04-01 01:05:00+00'
),
(
    'bbbbbbbb-0003-0003-0003-bbbbbbbbbbbb',
    '2026-04-01 02:00:00+00',
    'azure', 'acct-002', 'VirtualMachines', 'eastus',
    980.000000, 720.000000, 'Hrs',
    '{"env": "prod", "team": "ml"}', 'stream',
    '2026-04-01 02:05:00+00'
),
(
    'bbbbbbbb-0004-0004-0004-bbbbbbbbbbbb',
    '2026-04-01 03:00:00+00',
    'gcp', 'acct-003', 'BigQuery', 'us-central1',
    45.200000, 1500.000000, 'GB',
    '{"env": "staging", "team": "analytics"}', 'api',
    '2026-04-01 03:05:00+00'
);

-- ---------------------------------------------------------------------------
-- anomalies
-- ---------------------------------------------------------------------------
INSERT INTO anomalies
    (anomaly_id, account_id, service, region, bucket,
     anomaly_score, severity, score_breakdown, status, detected_at)
VALUES
(
    'cccccccc-0001-0001-0001-cccccccccccc',
    'acct-002', 'VirtualMachines', 'eastus',
    '2026-04-01 02:00:00+00',
    0.921000, 'critical',
    '{"if_score": 0.91, "zscore": 0.93, "hybrid": 0.921}',
    'open',
    '2026-04-01 02:10:00+00'
),
(
    'cccccccc-0002-0002-0002-cccccccccccc',
    'acct-001', 'EC2', 'us-east-1',
    '2026-04-01 00:00:00+00',
    0.410000, 'low',
    '{"if_score": 0.38, "zscore": 0.44, "hybrid": 0.410}',
    'resolved',
    '2026-04-01 00:15:00+00'
);

-- ---------------------------------------------------------------------------
-- alerts
-- ---------------------------------------------------------------------------
INSERT INTO alerts
    (alert_id, anomaly_id, account_id, service, region,
     severity, channel, status, dedup_key, created_at, sent_at)
VALUES
(
    'dddddddd-0001-0001-0001-dddddddddddd',
    'cccccccc-0001-0001-0001-cccccccccccc',
    'acct-002', 'VirtualMachines', 'eastus',
    'critical', 'in_app', 'sent',
    'acct-002:VirtualMachines:eastus:critical:2026-04-01T02',
    '2026-04-01 02:10:00+00',
    '2026-04-01 02:10:05+00'
),
(
    'dddddddd-0002-0002-0002-dddddddddddd',
    'cccccccc-0001-0001-0001-cccccccccccc',
    'acct-002', 'VirtualMachines', 'eastus',
    'critical', 'email', 'sent',
    'acct-002:VirtualMachines:eastus:critical:2026-04-01T02:email',
    '2026-04-01 02:10:00+00',
    '2026-04-01 02:10:07+00'
);

-- ---------------------------------------------------------------------------
-- audit_logs
-- ---------------------------------------------------------------------------
INSERT INTO audit_logs
    (audit_id, event_type, action, outcome, user_id,
     actor_email, actor_role, target_type, target_id, ip_address, created_at)
VALUES
(
    'eeeeeeee-0001-0001-0001-eeeeeeeeeeee',
    'auth', 'login', 'success',
    'aaaaaaaa-0001-0001-0001-aaaaaaaaaaaa',
    'admin@finguard.dev', 'admin',
    NULL, NULL, '127.0.0.1',
    '2026-04-01 00:00:30+00'
),
(
    'eeeeeeee-0002-0002-0002-eeeeeeeeeeee',
    'ingestion', 'ingest_event', 'success',
    'aaaaaaaa-0001-0001-0001-aaaaaaaaaaaa',
    'admin@finguard.dev', 'admin',
    'billing_event', 'bbbbbbbb-0003-0003-0003-bbbbbbbbbbbb', '127.0.0.1',
    '2026-04-01 02:05:00+00'
),
(
    'eeeeeeee-0003-0003-0003-eeeeeeeeeeee',
    'anomaly', 'resolve', 'success',
    'aaaaaaaa-0002-0002-0002-aaaaaaaaaaaa',
    'analyst@finguard.dev', 'analyst',
    'anomaly', 'cccccccc-0002-0002-0002-cccccccccccc', '10.0.0.5',
    '2026-04-01 01:00:00+00'
);
