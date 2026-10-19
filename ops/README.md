# ops/

Deployment helpers for the new backend and the migration window.

## Run (one command)

```powershell
$env:PYTHONPATH="backend/src"; $env:SECRET_KEY="dev-secret"; & <shared-python> -m battleship
```

Or through the stack launcher (this is what systemd runs):

```powershell
python ops/run_stack.py --stack rewrite --port 5000 --db ./battleship.db
python ops/run_stack.py --stack legacy  --port 5000 --db ./battleship.db `
    --legacy-worktree D:/develop/battle_ship1.0/.agents/worktrees/refactor
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

## Backend switch (configuration item)

The selected stack is the single variable **BACKEND_STACK** (`legacy` | `rewrite`).
Put it in `/etc/battleship/stack.env` (template: [stack.env.example](stack.env.example))
and have systemd load it with `EnvironmentFile`. `ops/run_stack.py` reads it when
`--stack` is omitted; `ops/stack_switch.py` is the supported way to change it.

```powershell
# Plan only (no backup, no restart)
python ops/stack_switch.py switch --to rewrite --port 5000 --db <db> `
    --restart-command "systemctl restart battleship@{stack}" --dry-run

# Real switch: backup -> migrate -> restart -> health check
python ops/stack_switch.py switch --to rewrite --port 5000 --db <db> `
    --restart-command "systemctl restart battleship@{stack}"

# Rollback: restore the pre-switch DB copy, restart legacy, health check
python ops/stack_switch.py rollback --port 5000 --db <db> `
    --restart-command "systemctl restart battleship@{stack}"
```

What the script guarantees, in order:

1. SQLite **online backup** to `<db>.backup-<UTC stamp>` before any write
   (WAL-safe; no file is touched if the backup fails);
2. rewrite only: `python -m battleship.repositories.migrations --database <db>`
   (itself backed up + row-count verified; failure keeps the old stack);
3. restart via the supplied command, then poll `/api/health` until
   `status == "ok"` (legacy: `/api/online_count` 200), default 180 s;
4. failure => restore the backup, restart the previous stack, re-check health,
   exit code 3;
5. success is written to the state file (`.tmp/stack-state.json` by default,
   override with `--state-file`) so `rollback` knows the previous stack;
6. rollback prints its elapsed time and warns when it exceeds 300 s.

Local drill (managed process, no systemd):

```powershell
python ops/stack_switch.py switch --to rewrite --serve --port 5328 `
    --db .tmp/switch.db --legacy-worktree <legacy worktree> --legacy-python <flask python>
python ops/stack_switch.py status --state-file .tmp/stack-state.json --port 5328
python ops/stack_switch.py rollback --serve --port 5328 `
    --db .tmp/switch.db --legacy-worktree <legacy worktree> --legacy-python <flask python>
```

### 5-minute rollback runbook

| Minute | Action |
| --- | --- |
| 0:00 | `stack_switch.py rollback ...` (it takes its own safety backup first) |
| 0:30 | DB backup restored + legacy process restarted (typical local drill: < 10 s) |
| 1:00 | `GET /api/online_count` 200; `status` shows `stack=legacy, healthy=true` |
| 2:00 | Log in once, open `/` and `/legacy`, finish a placement smoke |
| 3:00 | Announce the rollback in the channel; keep the backup path in the ticket |
| 4:00 | Spot-check online count / one match / replay entry |
| 5:00 | Handover note: current stack, backup path, reason |

If health does not recover, the script itself already restored the backup and
restarted the previous stack; the remaining manual step is only the announcement.

## Dual-stack comparison (different ports + database copies)

```powershell
# legacy on 5330, rewrite on 5331, two independent DB files
python ops/run_stack.py --stack legacy  --port 5330 --db .tmp/dual-legacy.db --legacy-worktree <legacy worktree>
python ops/run_stack.py --stack rewrite --port 5331 --db .tmp/dual-rewrite.db
```

The ticket gate is out of repo: `D:\develop\battleship-verify\cases\20-gate`
(`python gate.py`, `python dual_stack.py`, `python -m pytest -q`). It replays the
frozen eight-session contract against this tree and compares the two stacks'
smoke traces field by field.

## P0 behavior baseline and contract gate (out-of-repo)

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

## P0 contract recorder / replay gate (ticket #2)

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
