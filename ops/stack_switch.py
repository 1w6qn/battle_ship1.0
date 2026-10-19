"""Switch the serving backend (migration window) and roll back in one command.

Contract (spec user story 41/52/53):

* the selected stack is the configuration item BACKEND_STACK (legacy|rewrite);
* switching takes a SQLite online backup *before* touching anything, upgrades
  the database for the rewrite, restarts the stack and waits for a healthy
  /api/health (rewrite) or /api/online_count (legacy);
* any failure restores the backup, restarts the previous stack and exits 3;
* rollback is the same flow in the other direction and must finish in < 5 min.

Usage (local drill, managed process):

    python ops/stack_switch.py switch --to rewrite --port 5328 \
        --db .tmp/switch.db --serve --legacy-worktree <legacy worktree>

    python ops/stack_switch.py rollback --serve ...

Production uses --restart-command instead of --serve, e.g.
    --restart-command "systemctl restart battleship@{stack}"
(see ops/README.md).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STACKS = ('legacy', 'rewrite')
HEALTH_PATHS = {'legacy': '/api/online_count', 'rewrite': '/api/health'}
DEFAULT_STATE = ROOT / '.tmp' / 'stack-state.json'
ROLLBACK_BUDGET_SECONDS = 300


# --------------------------------------------------------------------------- io


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'version': 1, 'stack': None, 'history': [], 'last_backup': None,
                'managed_pid': None, 'port': None, 'db': None}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                         encoding='utf-8')
    os.replace(temporary, path)


def backup_database(db: Path) -> Path | None:
    if not db.exists() or db.stat().st_size == 0:
        return None
    backup = db.with_name(f'{db.name}.backup-{_stamp()}')
    source = sqlite3.connect(f'file:{db.as_posix()}?mode=ro', uri=True)
    try:
        target = sqlite3.connect(str(backup))
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    return backup


def restore_database(db: Path, backup: Path | None) -> None:
    if backup is None or not backup.exists():
        return
    for suffix in ('', '-wal', '-shm'):
        try:
            Path(str(db) + suffix).unlink()
        except FileNotFoundError:
            pass
    shutil.copy2(backup, db)


# ---------------------------------------------------------------------- process


def _spawn(command: list[str], log_path: Path) -> subprocess.Popen:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(log_path, 'a', encoding='utf-8')
    kwargs = {}
    if os.name == 'nt':
        kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs['start_new_session'] = True
    process = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT,
                               cwd=str(ROOT), **kwargs)
    process._gate_log = handle  # type: ignore[attr-defined]
    return process


def stop_managed(state: dict) -> None:
    pid = state.get('managed_pid')
    if not pid:
        return
    try:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'],
                           capture_output=True, timeout=20)
        else:
            os.killpg(int(pid), 15)
            time.sleep(1)
            os.killpg(int(pid), 9)
    except Exception:
        pass


def start_stack(args: argparse.Namespace, stack: str,
                state: dict) -> tuple[dict, subprocess.Popen | None]:
    if args.restart_command:
        command = args.restart_command.replace('{stack}', stack)
        subprocess.run(command, shell=True, check=False, cwd=str(ROOT))
        return {'managed_pid': None}, None
    python = args.legacy_python if stack == 'legacy' else args.rewrite_python
    command = [python, str(ROOT / 'ops' / 'run_stack.py'),
               '--stack', stack, '--root', str(ROOT),
               '--port', str(args.port), '--db', str(Path(args.db).resolve())]
    if args.legacy_worktree:
        command += ['--legacy-worktree', args.legacy_worktree]
    log_path = ROOT / '.tmp' / 'logs' / f'stack-{stack}.log'
    process = _spawn(command, log_path)
    return {'managed_pid': process.pid, 'log': str(log_path)}, process


# ----------------------------------------------------------------------- health


def health_ok(port: int, stack: str, path: str | None = None) -> tuple[bool, str]:
    url = f'http://127.0.0.1:{port}{path or HEALTH_PATHS[stack]}'
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            body = response.read(4000).decode('utf-8', errors='replace')
            if response.status != 200:
                return False, f'HTTP {response.status}'
            if stack == 'rewrite':
                try:
                    payload = json.loads(body)
                except ValueError:
                    return False, 'non-JSON health body'
                if payload.get('status') != 'ok':
                    return False, f"status={payload.get('status')}"
            return True, 'ok'
    except Exception as error:  # noqa: BLE001 - reported, never raised
        return False, f'{type(error).__name__}: {error}'


def wait_healthy(args: argparse.Namespace, stack: str, timeout: float,
                 process: subprocess.Popen | None = None) -> tuple[bool, str]:
    deadline = time.monotonic() + timeout
    last = 'not checked'
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            return False, f'process exited ({process.returncode})'
        last = health_ok(args.port, stack, args.health_path)[1]
        if last == 'ok':
            return True, last
        time.sleep(0.5)
    return False, last


# ------------------------------------------------------------------------ switch


def _migrate_rewrite(args: argparse.Namespace, db: Path) -> tuple[bool, str]:
    python = args.rewrite_python
    env = dict(os.environ)
    env['PYTHONPATH'] = str((ROOT / 'backend' / 'src').resolve())
    env['BATTLESHIP_DB_PATH'] = str(db)
    result = subprocess.run(
        [python, '-m', 'battleship.repositories.migrations', '--database', str(db)],
        capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=180)
    return result.returncode == 0, (result.stdout + result.stderr)[-2000:]


def switch(args: argparse.Namespace, target: str, *, rollback: bool) -> int:
    started = time.monotonic()
    state_file = Path(args.state_file)
    state = load_state(state_file)
    previous = state.get('stack')
    db = Path(args.db).resolve()

    if previous == target and health_ok(args.port, target, args.health_path)[0]             and not args.force:
        print(f'[switch] already on {target} and healthy; nothing to do')
        return 0

    print(f'[switch] {previous or "(none)"} -> {target}  db={db}')
    if args.dry_run:
        print('[switch] dry-run: backup -> migrate(rewrite) -> restart -> health')
        return 0

    backup = backup_database(db)
    print(f'[switch] database backup: {backup or "(no database yet)"}')
    rollback_backup = state.get('last_backup') if rollback else state.get('last_backup')

    # Stop the old process before any DDL/restore: Windows keeps the SQLite file
    # locked while the server is running, so restoring in place would fail.
    stop_managed(state)
    try:
        if rollback and rollback_backup:
            # Restore the exact pre-switch copy so data does not move backwards
            # relative to the legacy schema.
            restore_database(db, Path(rollback_backup))
            print(f'[switch] restored rollback snapshot: {rollback_backup}')
        elif target == 'rewrite':
            ok, output = _migrate_rewrite(args, db)
            if not ok:
                print(f'[switch] migration failed; keeping {previous}:\n{output}',
                      file=sys.stderr)
                restore_database(db, backup)
                if previous:
                    _, previous_process = start_stack(args, previous, state)
                    wait_healthy(args, previous, args.health_timeout, previous_process)
                return 2
    except Exception as error:  # noqa: BLE001 - restore + restart previous
        print(f'[switch] database step failed: {type(error).__name__}: {error}',
              file=sys.stderr)
        restore_database(db, backup)
        if previous:
            _, previous_process = start_stack(args, previous, state)
            wait_healthy(args, previous, args.health_timeout, previous_process)
        return 2

    started_state, started_process = start_stack(args, target, state)
    healthy, detail = wait_healthy(args, target, args.health_timeout, started_process)
    if not healthy:
        print(f'[switch] {target} unhealthy ({detail}); rolling back to {previous}',
              file=sys.stderr)
        stop_managed(started_state)
        restore_database(db, backup if not rollback else rollback_backup)
        if previous:
            previous_state, previous_process = start_stack(args, previous, state)
            ok_previous, detail_previous = wait_healthy(args, previous,
                                                       args.health_timeout,
                                                       previous_process)
            print(f'[switch] rollback stack healthy={ok_previous} ({detail_previous})',
                  file=sys.stderr)
        else:
            previous_state = {}
        return 3

    history = list(state.get('history') or [])
    if previous:
        history.append(previous)
    new_state = {
        'version': 1,
        'stack': target,
        'history': history[-10:],
        'last_backup': str(backup) if backup else rollback_backup,
        'port': args.port,
        'db': str(db),
        'switched_at': datetime.now(timezone.utc).isoformat(),
        **started_state,
    }
    save_state(state_file, new_state)
    elapsed = time.monotonic() - started
    print(f'[switch] {target} healthy in {elapsed:.1f}s '
          f'(budget {ROLLBACK_BUDGET_SECONDS}s for rollback)')
    if rollback and elapsed > ROLLBACK_BUDGET_SECONDS:
        print('[switch] WARNING: rollback exceeded the 5-minute budget',
              file=sys.stderr)
        return 4
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='stack_switch')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('switch', 'rollback'):
        command = sub.add_parser(name)
        command.add_argument('--to', choices=STACKS, default=None,
                             help='switch only; rollback derives it from history')
        command.add_argument('--root', default=str(ROOT))
        command.add_argument('--db', default=os.environ.get('BATTLESHIP_DB_PATH',
                                                            './battleship.db'))
        command.add_argument('--port', type=int,
                             default=int(os.environ.get('PORT', '5000')))
        command.add_argument('--legacy-worktree',
                             default=os.environ.get('LEGACY_WORKTREE', ''))
        command.add_argument('--state-file', default=str(DEFAULT_STATE))
        command.add_argument('--health-path', default=None)
        command.add_argument('--health-timeout', type=float, default=180.0)
        command.add_argument('--restart-command', default=None,
                             help='e.g. "systemctl restart battleship@{stack}"')
        command.add_argument('--serve', action='store_true',
                             help='spawn/kill ops/run_stack.py (local drill)')
        command.add_argument('--legacy-python', default=os.environ.get(
            'LEGACY_PYTHON', shutil.which('python') or 'python'))
        command.add_argument('--rewrite-python', default=sys.executable)
        command.add_argument('--dry-run', action='store_true')
        command.add_argument('--force', action='store_true')

    status = sub.add_parser('status')
    status.add_argument('--state-file', default=str(DEFAULT_STATE))
    status.add_argument('--port', type=int,
                        default=int(os.environ.get('PORT', '5000')))

    args = parser.parse_args(argv)
    if args.command == 'status':
        state = load_state(Path(args.state_file))
        stack = state.get('stack')
        healthy = bool(stack) and health_ok(args.port, stack)[0]
        print(json.dumps({**state, 'healthy': healthy}, ensure_ascii=False, indent=2))
        return 0

    # --serve is the local process manager; without it the deployment restart
    # command must be supplied explicitly (fail closed instead of silently
    # leaving the old process serving).
    if not args.dry_run and not args.serve and not args.restart_command:
        print('[switch] need --serve (local) or --restart-command (deploy)',
              file=sys.stderr)
        return 2

    if args.command == 'rollback':
        state = load_state(Path(args.state_file))
        history = list(state.get('history') or [])
        target = history[-1] if history else 'legacy'
        if state.get('stack') == target and not history:
            target = 'rewrite' if target == 'legacy' else 'legacy'
        return switch(args, target, rollback=True)
    target = args.to or 'rewrite'
    return switch(args, target, rollback=False)


if __name__ == '__main__':
    raise SystemExit(main())
