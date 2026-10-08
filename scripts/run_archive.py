"""Remote archive runner, 2026-10-08 (UTC+8).

Preview by default. --write publishes already-ended reports through ordinary PRs.
Uses the current user's existing gh login; never changes the local checkout.
"""
from contextlib import contextmanager
from datetime import datetime
import argparse
import json
import os
from pathlib import Path
import sys

from archive_events import DALIAN
from manager_store import Store, ConflictError

STATE = Path(__file__).resolve().parents[1] / '.manager-state'


def run(store, *, write=False, emit=None):
    emit = emit or (lambda value: print(json.dumps(value, ensure_ascii=False), flush=True))
    total, conflicts = 0, 0
    while True:
        preview = store.archive_preview()
        result = preview
        if write and preview['count']:
            try:
                result = store.archive(preview['revision'])
            except ConflictError:
                conflicts += 1
                if conflicts >= 3:
                    raise
                continue  # Re-read the latest main; no stale retry or overwrite.
            conflicts = 0
            total += result.get('archived', 0)
        entry = dict(result, totalArchived=total)
        entry.setdefault('status', 'preview' if not write else 'unchanged')
        emit(entry)
        return entry  # A pending PR is preserved, never retried into duplicate PRs.


@contextmanager
def instance_lock(directory):
    """OS-owned lock releases on exit/crash. A stale file never blocks a run."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'archive.lock').open('a+b') as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def recorder(directory):
    directory.mkdir(parents=True, exist_ok=True)
    def emit(value):
        entry = dict(value, recordedAt=datetime.now(DALIAN).isoformat())
        raw = json.dumps(entry, ensure_ascii=False)
        temp = directory / 'archive-status.json.tmp'
        temp.write_text(raw + '\n', encoding='utf-8')
        temp.replace(directory / 'archive-status.json')
        log = directory / 'archive-log.jsonl'
        if log.exists() and log.stat().st_size > 1_000_000:
            log.replace(directory / 'archive-log.previous.jsonl')
        with log.open('a', encoding='utf-8') as stream:
            stream.write(raw + '\n')
        print(raw, flush=True)
    return emit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--gh', default='gh', help='Installed GitHub CLI executable')
    parser.add_argument('--state-dir', type=Path, default=STATE)
    args = parser.parse_args()
    if not args.write:
        run(Store(gh=args.gh))
        return 0
    emit = recorder(args.state_dir)
    with instance_lock(args.state_dir) as acquired:
        if not acquired:
            print(json.dumps({'status': 'already_running'}))
            return 0
        try:
            run(Store(gh=args.gh), write=True, emit=emit)
            return 0
        except Exception as error:
            # Store errors are deliberately redacted; do not log traceback/env.
            emit({'status': 'failed', 'message': str(error)})
            return 1


if __name__ == '__main__':
    sys.exit(main())
