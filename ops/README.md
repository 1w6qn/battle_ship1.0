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

Missing/blank SECRET_KEY exits before binding the port and prints the variable name.

## Endpoints

| Path | Purpose |
| --- | --- |
| GET /health / GET /healthz / GET /api/health | config / database / contracts / Socket.IO checks; 503 when degraded |
| GET /metrics / GET /api/metrics | counters, gauges (connections/rooms/online), latency p50/p95/max, error rate |
| GET /api/contracts/schema | {hash, bundle}; ETag is the canonical schema hash |
| GET / / GET /legacy | old SPA during the migration window |
| GET /static/* | old static assets from the repo root |

## Contract artifact

```powershell
$env:PYTHONPATH="backend/src"; & <shared-python> -m battleship.contracts.export_schema --out ..\contracts.schema.json
$env:PYTHONPATH="backend/src"; & <shared-python> -m battleship.contracts.export_schema --check ..\contracts.schema.json
$env:PYTHONPATH="backend/src"; & <shared-python> -m battleship.contracts.export_schema --format ts --out frontend\src\socket\events.gen.ts
```

The TS artifact embeds CONTRACT_SCHEMA_HASH; rebuild/compare it whenever contracts change.

## P0 behavior baseline (out-of-repo)

Behavior gates are not stored in this repository (spec testing-asset policy).
They live outside the repo and drive the legacy (later: new) stack only through
HTTP + Socket.IO:

```powershell
cd D:\develop\battleship-verify\cases\3-baseline
$env:PYTHONIOENCODING='utf-8'
D:\develop\battleship-verify\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Baseline numbers, the source-assertion mapping and reproducible commands:

- D:\develop\battleship-verify\notes\baseline.md
- D:\develop\battleship-verify\cases\3-baseline\BEHAVIOR_MAPPING.md
- D:\develop\battleship-verify\cases\3-baseline\runner.py

Ports 5303 (test-event server) / 5304 (production-mode server), isolated databases
under D:\develop\battleship-verify\.tmp\3-baseline. No test file is added to the repo.

## P0 contract recorder / replay gate (ticket #2, out-of-repo)

The recorder, replay comparator, samples and normalization rules live in
`D:\develop\battleship-verify` (spec testing-asset policy: no tests/fixtures in
this repository). Only this pointer is committed.

```powershell
# One command: fresh isolated legacy stack per session (fixed RNG seed + DB),
# record, replay, then replay a second time and compare the two runs.
D:/develop/battleship-verify/.venv/Scripts/python.exe `
  D:/develop/battleship-verify/tools/run_gate.py `
  --legacy-worktree D:/develop/battle_ship1.0/.agents/worktrees/refactor `
  --repeat 2

# Replay against any candidate backend; exit code is the gate.
D:/develop/battleship-verify/.venv/Scripts/python.exe `
  D:/develop/battleship-verify/tools/verify.py replay --target http://127.0.0.1:5401
```

Session matrix, normalization rules and known limits:
`D:/develop/battleship-verify/notes/CONTRACT_NORMALIZATION.md`.
