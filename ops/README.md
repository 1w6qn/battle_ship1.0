# ops/

Deployment helpers (planned): build, migrate, systemd unit, health check, rollback.
Scripts are added with the rewrite phases.

## P0 behavior baseline (out-of-repo)

Behavior gates are not stored in this repository (spec testing-asset policy).
They live outside the repo and drive the legacy (later: new) stack only through
HTTP + Socket.IO:

    cd D:\develop\battleship-verify\cases\3-baseline
    $env:PYTHONIOENCODING='utf-8'
    D:\develop\battleship-verify\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider

Baseline numbers, the source-assertion mapping and reproducible commands:

- D:\develop\battleship-verify\notes\baseline.md
- D:\develop\battleship-verify\cases\3-baseline\BEHAVIOR_MAPPING.md
- D:\develop\battleship-verify\cases\3-baseline\runner.py

Ports 5303 (test-event server) / 5304 (production-mode server), isolated databases
under D:\develop\battleship-verify\.tmp\3-baseline. No test file is added to the repo.
