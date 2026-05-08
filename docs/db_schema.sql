-- FinGuard Database Schema
-- Generated: 2026-05-09
-- PostgreSQL >= 14 required (uses gen_random_uuid(), JSONB)
-- Apply via Alembic: alembic upgrade head
-- Or apply manually in order below.

-- ---------------------------------------------------------------------------
-- 0001: billing_events_raw
-- ---------------------------------------------------------------------------
CREATE TABLE billing_events_raw (
    event_id        UUID            PRIMARY KEY,
    "timestamp"     TIMESTAMPTZ     NOT NULL,
    provider        VARCHAR(16)     NOT NULL,
    account_id      VARCHAR(255)    NOT NULL,
    service         VARCHAR(255)    NOT NULL,
    region          VARCHAR(128)    NOT NULL,
    cost_amount     NUMERIC(18,6)   NOT NULL,
    usage_amount    NUMERIC(18,6)   NOT NULL,
    usage_unit      VARCHAR(64)     NOT NULL,
    tags            JSONB           NOT NULL DEFAULT '{}'::jsonb,
    source_type     VARCHAR(16)     NOT NULL,
    ingested_at     TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX ix_billing_events_raw_account_id ON billing_events_raw (account_id);
CREATE INDEX ix_billing_events_raw_timestamp  ON billing_events_raw ("timestamp");

-- ---------------------------------------------------------------------------
-- 0002: anomalies
-- ---------------------------------------------------------------------------
CREATE TABLE anomalies (
    anomaly_id      UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id      VARCHAR(255)    NOT NULL,
    service         VARCHAR(255)    NOT NULL,
    region          VARCHAR(128)    NOT NULL,
    bucket          TIMESTAMPTZ     NOT NULL,
    anomaly_score   NUMERIC(8,6)    NOT NULL,
    severity        VARCHAR(16)     NOT NULL DEFAULT 'none',
    score_breakdown JSONB,
    status          VARCHAR(32)     NOT NULL DEFAULT 'open',
    detected_at     TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX ix_anomalies_account_id ON anomalies (account_id);
CREATE INDEX ix_anomalies_bucket     ON anomalies (bucket);
CREATE INDEX ix_anomalies_status     ON anomalies (status);

-- ---------------------------------------------------------------------------
-- 0003: alerts
-- ---------------------------------------------------------------------------
CREATE TABLE alerts (
    alert_id     UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    anomaly_id   UUID         NOT NULL,
    account_id   VARCHAR(255) NOT NULL,
    service      VARCHAR(255) NOT NULL,
    region       VARCHAR(128) NOT NULL,
    severity     VARCHAR(16)  NOT NULL,
    channel      VARCHAR(16)  NOT NULL,
    status       VARCHAR(16)  NOT NULL DEFAULT 'pending',
    dedup_key    VARCHAR(255) NOT NULL,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    sent_at      TIMESTAMPTZ,
    error_detail VARCHAR(512),
    CONSTRAINT uq_alerts_dedup_key UNIQUE (dedup_key)
);

CREATE INDEX ix_alerts_anomaly_id ON alerts (anomaly_id);
CREATE INDEX ix_alerts_account_id ON alerts (account_id);
CREATE INDEX ix_alerts_status     ON alerts (status);

-- ---------------------------------------------------------------------------
-- 0004: users
-- ---------------------------------------------------------------------------
CREATE TABLE users (
    user_id         UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(320) NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    role            VARCHAR(32)  NOT NULL,
    is_active       BOOLEAN      NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_users_email UNIQUE (email)
);

CREATE INDEX ix_users_email ON users (email);

-- ---------------------------------------------------------------------------
-- 0005: audit_logs
-- ---------------------------------------------------------------------------
CREATE TABLE audit_logs (
    audit_id    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type  VARCHAR(64)  NOT NULL,
    action      VARCHAR(64)  NOT NULL,
    outcome     VARCHAR(16)  NOT NULL,
    user_id     UUID,
    actor_email VARCHAR(320),
    actor_role  VARCHAR(32),
    target_type VARCHAR(32),
    target_id   VARCHAR(255),
    ip_address  VARCHAR(45),
    user_agent  VARCHAR(512),
    meta        JSONB,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX ix_audit_logs_event_type ON audit_logs (event_type);
CREATE INDEX ix_audit_logs_user_id    ON audit_logs (user_id);
CREATE INDEX ix_audit_logs_created_at ON audit_logs (created_at);
CREATE INDEX ix_audit_logs_outcome    ON audit_logs (outcome);
