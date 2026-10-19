"""Start one backend stack (migration-window launcher).

Both stacks read the same environment variables as before; this script only
selects which process tree serves the port:

    python ops/run_stack.py --stack rewrite --port 5000 --db ./battleship.db
    python ops/run_stack.py --stack legacy  --port 5000 --db ./battleship.db \
        --legacy-worktree D:/develop/battle_ship1.0/.agents/worktrees/refactor

The stack is chosen by --stack or the BACKEND_STACK environment variable
(default rewrite).  In production systemd runs this same command with
EnvironmentFile=/etc/battleship/stack.env so a switch is a one-variable change.
"""

from __future__ import annotations

import argparse
import os
import runpy
import sys
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[1]


def _prepare_env(args: argparse.Namespace) -> Path:
    db_path = Path(args.db).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    os.environ['BATTLESHIP_DB_PATH'] = str(db_path)
    os.environ['PORT'] = str(args.port)
    os.environ['HOST'] = args.host
    os.environ.setdefault('CORS_ORIGINS', f'http://127.0.0.1:{args.port}')
    os.environ.setdefault('TURN_TIMEOUT_SECONDS', '90')
    os.environ.setdefault('CHAIN_DISPLAY_DELAY_SECONDS', '1.2')
    return db_path


def run_rewrite(args: argparse.Namespace, root: Path) -> int:
    src = root / 'backend' / 'src'
    if not (src / 'battleship' / 'main.py').is_file():
        print(f'[run_stack] new backend not found under {root}', file=sys.stderr)
        return 2
    db_path = _prepare_env(args)
    os.chdir(root)
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    if not args.skip_migrate:
        from battleship.repositories.migrations import migrate_database
        migrate_database(db_path, backup=True)
    import uvicorn
    uvicorn.run('battleship.main:app', host=args.host, port=args.port,
                log_config=None, access_log=False)
    return 0


def run_legacy(args: argparse.Namespace) -> int:
    worktree = Path(args.legacy_worktree or os.environ.get('LEGACY_WORKTREE', '')).resolve()
    server_py = worktree / 'server.py'
    if not server_py.is_file():
        print(f'[run_stack] legacy server.py not found: {server_py}', file=sys.stderr)
        return 2
    _prepare_env(args)
    os.chdir(worktree)
    if str(worktree) not in sys.path:
        sys.path.insert(0, str(worktree))
    runpy.run_path(str(server_py), run_name='__main__')
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='run_stack')
    parser.add_argument('--stack', choices=('legacy', 'rewrite'),
                        default=os.environ.get('BACKEND_STACK', 'rewrite'))
    parser.add_argument('--root', default=str(DEFAULT_ROOT))
    parser.add_argument('--legacy-worktree',
                        default=os.environ.get('LEGACY_WORKTREE', ''))
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', '5000')))
    parser.add_argument('--host', default=os.environ.get('HOST', '0.0.0.0'))
    parser.add_argument('--db', default=os.environ.get('BATTLESHIP_DB_PATH',
                                                       './battleship.db'))
    parser.add_argument('--skip-migrate', action='store_true')
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if args.stack == 'legacy':
        return run_legacy(args)
    return run_rewrite(args, root)


if __name__ == '__main__':
    raise SystemExit(main())
