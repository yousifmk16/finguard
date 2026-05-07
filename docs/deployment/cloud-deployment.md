# OPS-06 — Cloud deployment profile guide

This guide takes the local stack from [`local-deployment.md`](local-deployment.md) and
maps every component to a concrete cloud profile. The reference profile is
**GCP** (per ARC-08), with AWS and Azure equivalents called out for each step.

> **Audience:** SRE / platform engineers shipping FinGuard to a managed
> environment. Assumes familiarity with the cloud's IaC tooling
> (Terraform, Pulumi, gcloud/aws/az CLI).

## 1. Reference topology

```
┌───────────────┐      ┌────────────────┐      ┌───────────────────┐
│  Frontend SPA │──────│  Backend API   │──┬───│  PostgreSQL (RDB) │
│  (CDN + obj.) │      │  (containers)  │  │   └───────────────────┘
└───────────────┘      └────────────────┘  │
                              │            └──┐
                              │               │
                              ▼               ▼
                       ┌────────────┐   ┌────────────────┐
                       │   Redis    │   │  Object store  │
                       │ (managed)  │   │  for DLQ + ML  │
                       └────────────┘   └────────────────┘
                              │
                              ▼
                  ┌──────────────────────────┐
                  │  Stream consumer worker  │
                  │  Alert orchestrator      │
                  │  (containers, scaled to  │
                  │   N replicas)            │
                  └──────────────────────────┘
                              │
                              ▼
                  ┌──────────────────────────┐
                  │  Observability stack     │
                  │  (Prom + Grafana, logs)  │
                  └──────────────────────────┘
```

## 2. Component → cloud-service mapping

| Local component | GCP (reference) | AWS | Azure |
| --- | --- | --- | --- |
| Backend API container | **Cloud Run** (or GKE Autopilot) | ECS Fargate / EKS | Container Apps / AKS |
| Frontend SPA | **Cloud Storage + Cloud CDN** | S3 + CloudFront | Storage Static Web + Front Door |
| Stream consumer worker | **Cloud Run job / GKE Deployment** | ECS service / EKS | Container Apps / AKS |
| Alert orchestrator worker | **Cloud Run job / GKE Deployment** | ECS service / EKS | Container Apps / AKS |
| PostgreSQL | **Cloud SQL for PostgreSQL** | RDS for PostgreSQL | Azure DB for PostgreSQL Flexible |
| Redis Streams | **Memorystore for Redis** | ElastiCache for Redis | Azure Cache for Redis |
| Secrets | **Secret Manager** | Secrets Manager | Key Vault |
| Container registry | **Artifact Registry** | ECR | ACR |
| Logs | **Cloud Logging** (JSON ingest) | CloudWatch Logs | Log Analytics |
| Metrics | Managed Prometheus / **Cloud Monitoring** | Managed Prometheus / CloudWatch | Azure Monitor + Managed Prometheus |
| Dashboards | Grafana on Cloud Run / Managed Grafana | Managed Grafana | Managed Grafana |
| DLQ persistence | Bucket + mounted CSI / GCS Fuse | EFS / S3 | Azure Files |

The choice of **Cloud Run vs. Kubernetes** is independent for each
service: the API and the workers run identical container images and
read identical env vars, so you can mix-and-match (e.g. API on Cloud Run,
workers on GKE) without code changes.

## 3. Container images

### Backend image (`backend/Dockerfile` — needs to be added if missing)

```dockerfile
FROM python:3.11-slim AS base
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install -r /app/backend/requirements.txt

COPY backend /app/backend
COPY services /app/services
ENV PYTHONPATH=/app/backend:/app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Build & push:

```bash
# GCP
gcloud auth configure-docker us-central1-docker.pkg.dev
docker build -t us-central1-docker.pkg.dev/$PROJECT/finguard/backend:$SHA -f backend/Dockerfile .
docker push  us-central1-docker.pkg.dev/$PROJECT/finguard/backend:$SHA

# AWS
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin $ACCOUNT.dkr.ecr.us-east-1.amazonaws.com
docker build -t $ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/finguard/backend:$SHA -f backend/Dockerfile .
docker push  $ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/finguard/backend:$SHA

# Azure
az acr login --name $REGISTRY
docker build -t $REGISTRY.azurecr.io/finguard/backend:$SHA -f backend/Dockerfile .
docker push  $REGISTRY.azurecr.io/finguard/backend:$SHA
```

### Frontend image — production build, not the dev server

The current [`frontend/Dockerfile`](../../frontend/Dockerfile) runs `npm run dev`
which is fine for compose but **not for production**. For cloud, build a
static bundle and host it on a CDN, or use this prod-mode Dockerfile:

```dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY frontend/package*.json /app/
RUN npm ci
COPY frontend/ /app/
RUN npm run build         # writes /app/dist

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
# Optional: SPA fallback so every route serves index.html
RUN printf 'server { listen 80; root /usr/share/nginx/html; \
location / { try_files $uri /index.html; } }' \
    > /etc/nginx/conf.d/default.conf
EXPOSE 80
```

Static-CDN flow (preferred): `npm run build`, sync `dist/` to
GCS / S3 / Storage, point the CDN at the bucket, and configure SPA-style
rewrites to `/index.html`.

## 4. Environment / secret mapping

Translate the env vars from [`local-deployment.md` § 4.1](local-deployment.md)
into managed-secret references. Example for GCP Secret Manager + Cloud Run:

```bash
# Create secrets
echo -n "$REAL_JWT_SECRET" | gcloud secrets create finguard-jwt-secret --data-file=-
gcloud secrets create finguard-db-url --data-file=-
gcloud secrets create finguard-smtp-password --data-file=-

# Wire to the service
gcloud run deploy finguard-backend \
  --image us-central1-docker.pkg.dev/$PROJECT/finguard/backend:$SHA \
  --region us-central1 \
  --port 8000 \
  --set-env-vars "FINGUARD_LOG_FORMAT=json,FINGUARD_CORS_ORIGINS=https://app.finguard.io" \
  --set-secrets "DATABASE_URL=finguard-db-url:latest,JWT_SECRET=finguard-jwt-secret:latest,SMTP_PASSWORD=finguard-smtp-password:latest"
```

Equivalent flows: AWS Secrets Manager → ECS task definition `secrets:`
block; Azure Key Vault → Container Apps `secretRef`. **Never** rely on
the dev-only `JWT_SECRET` fallback in production — the app prints a
warning but does start, so this is easy to miss.

## 5. Database migrations during deploy

Alembic must run **before** the new image starts serving traffic:

  - **Cloud Run / Container Apps** — ship a one-shot job that runs
    `alembic upgrade head` against the production DSN, gated on success
    of the new image build. Do not run migrations in the API entrypoint.
  - **GKE / EKS / AKS** — use a `Job` resource that runs to completion;
    chain the rollout to the Job's success.

Reference job:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: finguard-migrate-{{ git_sha }}
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: migrate
          image: us-central1-docker.pkg.dev/$PROJECT/finguard/backend:$SHA
          command: ["alembic", "upgrade", "head"]
          envFrom:
            - secretRef:
                name: finguard-db
```

The migrations live in [`backend/alembic/versions`](../../backend/alembic/versions)
and are idempotent on re-run.

## 6. Health, readiness, and metrics wiring

OPS-01 / OPS-02 / OPS-03 give the cloud operator three orthogonal
control planes:

### 6.1 Liveness + readiness probes

`/health` returns 200 for `ok|degraded` and 503 for `unhealthy`. Wire
both probes to the same path — the orchestrator interprets the status
code, not the body.

```yaml
livenessProbe:
  httpGet: { path: /health, port: 8000 }
  initialDelaySeconds: 5
  periodSeconds: 10
readinessProbe:
  httpGet: { path: /health, port: 8000 }
  initialDelaySeconds: 5
  periodSeconds: 5
```

Cloud Run honours the same `/health` automatically when configured as
the **startup probe**.

### 6.2 Logs

OPS-02 emits one JSON object per line on stdout with `request_id` set
from the `X-Request-ID` header. Cloud Logging / CloudWatch / Log
Analytics ingest this directly — no additional shipping agent needed
inside the container. Set `FINGUARD_LOG_FORMAT=json` (the default).

To correlate frontend → backend, configure the SPA / API gateway to
forward an inbound `X-Request-ID` header. The middleware will honour
incoming IDs unchanged and stamp generated UUIDs only when absent.

### 6.3 Metrics

`/metrics` exposes Prometheus 0.0.4 text format (OPS-03). Scrape config
template:

```yaml
- job_name: finguard
  scrape_interval: 15s
  metrics_path: /metrics
  static_configs:
    - targets: ["finguard-backend.internal:8000"]
```

Managed Prometheus services (GMP, AMP, Azure Managed Prometheus)
auto-scrape based on annotations:

```yaml
metadata:
  annotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "8000"
    prometheus.io/path: "/metrics"
```

Import [`infra/dashboards/finguard.json`](../../infra/dashboards/finguard.json)
into Grafana — see [`metrics-dashboards.md`](../runbooks/metrics-dashboards.md).

## 7. State that does **not** scale across replicas

A few in-process registries are safe for a single replica but become
inconsistent when the API is scaled out. Pin them down before going
multi-instance:

| Component | Risk | Fix |
| --- | --- | --- |
| `app.core.idempotency.store` | Each replica has its own duplicate check; cross-replica dupes only caught by the `event_id` unique index in `billing_events_raw` | Replace with Redis `SET` (the in-line comment in [idempotency.py](../../backend/app/core/idempotency.py) flags this — ING-03 follow-up) |
| `app.core.http_metrics.http_metrics` | Each replica serves its own `/metrics`; Prometheus aggregates by scraping all replicas (designed) | None — this is correct. Make sure the scraper hits each replica, not a single load-balanced address |
| `services.detection.metrics.detection_metrics` | Same as above — per-replica counters | Same — Prometheus aggregates |
| `app.core.logging_config.request_id_var` | ContextVar is request-scoped; safe across replicas | None |

## 8. Worker deployments

The stream consumer and alert orchestrator are stateless workers — no
HTTP listener. Deploy them as separate workloads to scale independently
of the API:

```yaml
# Excerpt — full manifests live in infra/k8s once authored
apiVersion: apps/v1
kind: Deployment
metadata: { name: finguard-stream-consumer }
spec:
  replicas: 2
  template:
    spec:
      containers:
        - name: worker
          image: $REGISTRY/finguard/backend:$SHA
          command: ["python", "-m", "services.stream.consumer"]
          envFrom:
            - secretRef: { name: finguard-runtime }
          volumeMounts:                # for the DLQ
            - name: dlq
              mountPath: /var/lib/finguard
      volumes:
        - name: dlq
          persistentVolumeClaim:
            claimName: finguard-dlq
```

Set `STREAM_DLQ_PATH=/var/lib/finguard/dlq.jsonl` so the file lands on
the persistent volume — see [`retry-and-dlq.md`](../runbooks/retry-and-dlq.md).

For Cloud Run jobs, mount a GCS bucket via Cloud Run's GCS volume mount
(or fall back to writing the DLQ to GCS through a small adapter — left
as an extension; the current writer is a plain file API).

## 9. Networking & TLS

  - **Edge TLS** — terminate at the cloud LB / API gateway (Cloud Run
    HTTPS load balancer, ALB, App Gateway). The container itself only
    needs to listen on plain HTTP.
  - **CORS** — set `FINGUARD_CORS_ORIGINS` to the SPA's public origin(s),
    comma-separated. The default (`localhost:3000`) does not work in
    production.
  - **Internal traffic** — keep Postgres and Redis on private networks
    (VPC, peering). Public endpoints are not needed and increase risk.
  - **`X-Forwarded-For`** — the audit recorder already honours this for
    client IPs; ensure the LB sets it (default for all three clouds).

## 10. Rollout & rollback

Recommended rollout order — each step gated on the previous step's
health:

  1. Push image, run schema migration job (§ 5).
  2. Deploy backend API to a 5–10 % canary; watch `/metrics`
     (`finguard_http_requests_total{status=~"5.."}`).
  3. Deploy stream consumer / alert orchestrator workers.
  4. Promote API to 100 %.
  5. Sync the frontend build to the CDN bucket and invalidate cache.

Rollback is the inverse: re-deploy the previous tag (idempotent),
**do not** reverse-run a migration unless the data shape has changed
incompatibly. Every Alembic revision in `backend/alembic/versions`
ships a `downgrade()` step, but exercise them with care.

## 11. GCP-specific quick start

```bash
# Project + billing already configured.
PROJECT=$(gcloud config get-value project)
REGION=us-central1

# Postgres (~5 min)
gcloud sql instances create finguard-pg \
  --database-version POSTGRES_15 --tier db-g1-small --region $REGION
gcloud sql databases create finguard --instance finguard-pg

# Redis
gcloud redis instances create finguard-redis \
  --size 1 --region $REGION --redis-version redis_7_0

# Artifact registry
gcloud artifacts repositories create finguard \
  --repository-format docker --location $REGION

# Build, push, deploy backend
docker build -t $REGION-docker.pkg.dev/$PROJECT/finguard/backend:v1 -f backend/Dockerfile .
docker push  $REGION-docker.pkg.dev/$PROJECT/finguard/backend:v1
gcloud run deploy finguard-backend \
  --image $REGION-docker.pkg.dev/$PROJECT/finguard/backend:v1 \
  --region $REGION --port 8000 \
  --set-secrets "DATABASE_URL=finguard-db-url:latest,JWT_SECRET=finguard-jwt-secret:latest" \
  --set-env-vars "FINGUARD_LOG_FORMAT=json,REDIS_URL=redis://10.x.x.x:6379/0"
```

## 12. Related docs

- [Architecture baseline (ARC-01..08)](../architecture/sprint-1-architecture-baseline.md)
- [Local deployment guide (OPS-05)](local-deployment.md)
- [Metrics & dashboards (OPS-03)](../runbooks/metrics-dashboards.md)
- [Retry & dead-letter (OPS-04)](../runbooks/retry-and-dlq.md)
