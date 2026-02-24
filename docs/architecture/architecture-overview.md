# Architecture Overview (Run 1)

## Selected Style

Event-driven services with clear boundaries:

- ingestion
- normalization
- detection
- alerting
- API/dashboard

## Core Components

- Synthetic data generator
- Ingestion API + stream broker
- Detection engine (TS + IF + rules)
- Alert service (in-app + email)
- PostgreSQL/Timescale + Redis
- Web dashboard

## Core Event Schema (v1)

- event_id
- timestamp
- provider
- account_id
- service
- region
- cost_amount
- usage_amount
- usage_unit
