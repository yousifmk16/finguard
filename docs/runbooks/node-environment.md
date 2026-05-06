# Node Environment Runbook

This runbook documents frontend Node.js setup for local development.

## Version

- Node.js `20` (see `frontend/.nvmrc`)

## Setup

```bash
cd frontend
npm install
```

## Verify

```bash
cd frontend
npm run lint
npm test
```

## Scripts

- `npm run dev`        Vite dev server on `http://localhost:3000` (proxies `/api` to
                       `VITE_API_PROXY_TARGET`, default `http://localhost:8000`).
- `npm run build`      Type-checks and produces a production build under `dist/`.
- `npm run preview`    Serves the production build locally on port 3000.
- `npm run typecheck`  `tsc --noEmit` on the whole frontend.
- `npm run lint`       ESLint over `src/**/*.{ts,tsx}`; warnings fail the run.

## Environment Variables

Copy `frontend/.env.example` to `frontend/.env.local` and adjust as needed:

- `VITE_API_BASE_URL`       request base path used by the frontend (default `/api/v1`)
- `VITE_API_PROXY_TARGET`   upstream the Vite dev server proxies to (default
                            `http://localhost:8000`)

## Notes

- Lockfile is produced by the first `npm install` and committed per REL-02.
