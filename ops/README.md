# ops/

Deployment helpers for the new backend.

## Run (one command)

From the worktree root (PowerShell):

```powershell
$env:PYTHONPATH="backend/src"; $env:SECRET_KEY="dev-secret"; & <shared-python> -m battleship
```

Or with uvicorn directly (same ASGI composition root):

```powershell
$env:PYTHONPATH="backend/src"; $env:SECRET_KEY="dev-secret"; & <shared-python> -m uvicorn battleship.main:app --host 0.0.0.0 --port 5000
```

Missing/blank `SECRET_KEY` exits before binding the port and prints the variable name.

## Endpoints

| Path | Purpose |
| --- | --- |
| `GET /health` / `GET /healthz` / `GET /api/health` | config / database / contracts / Socket.IO checks; 503 when degraded |
| `GET /metrics` / `GET /api/metrics` | counters, gauges (connections/rooms/online), latency p50/p95/max, error rate |
| `GET /api/contracts/schema` | `{hash, bundle}`; `ETag` is the canonical schema hash |
| `GET /` / `GET /legacy` | old SPA during the migration window |
| `GET /static/*` | old static assets from the repo root |

## Contract artifact

```powershell
$env:PYTHONPATH="backend/src"; & <shared-python> -m battleship.contracts.export_schema --out ..\contracts.schema.json
$env:PYTHONPATH="backend/src"; & <shared-python> -m battleship.contracts.export_schema --check ..\contracts.schema.json
$env:PYTHONPATH="backend/src"; & <shared-python> -m battleship.contracts.export_schema --format ts --out frontend\src\socket\events.gen.ts
```

The TS artifact embeds `CONTRACT_SCHEMA_HASH`; rebuild/compare it whenever contracts change.
