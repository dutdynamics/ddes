from datetime import datetime
import unittest

from run_archive import run
from manager_store import ConflictError


def stamp(value):
    return datetime.fromisoformat('2026-10-08T' + value + '+08:00')


class FakeStore:
    def __init__(self, clock, end='09:45:00', pending=False):
        self.clock, self.end, self.pending = clock, stamp(end), pending
        self.written, self.previews = 0, 0

    def archive_preview(self):
        self.previews += 1
        due = self.clock() >= self.end and not self.written
        return {'revision': str(self.previews), 'count': int(due), 'candidates': [],
                'nextEndAt': self.end.isoformat() if not due and not self.written else None}

    def archive(self, revision):
        self.written += 1
        assert self.clock() >= self.end
        return {'status': 'pending_review' if self.pending else 'merged', 'count': 1,
                'archived': 0 if self.pending else 1, 'nextEndAt': None}


class RunnerTests(unittest.TestCase):
    def test_ten_am_archives_ended_morning_report(self):
        store = FakeStore(lambda: stamp('10:00:00'))
        result = run(store, write=True, emit=lambda value: None)
        self.assertEqual(store.written, 1)
        self.assertEqual(result['totalArchived'], 1)
        self.assertEqual(store.previews, 1)

    def test_one_shot_at_nine_does_not_wait_or_archive(self):
        store = FakeStore(lambda: stamp('09:00:00'))
        run(store, write=True, emit=lambda value: None)
        self.assertEqual(store.written, 0)

    def test_preview_never_publishes(self):
        store = FakeStore(lambda: stamp('10:00:00'))
        run(store, emit=lambda value: None)
        self.assertEqual(store.written, 0)

    def test_pending_review_stops_no_duplicate_pr(self):
        store = FakeStore(lambda: stamp('10:00:00'), pending=True)
        result = run(store, write=True, emit=lambda value: None)
        self.assertEqual(result['status'], 'pending_review')
        self.assertEqual(store.written, 1)
        self.assertEqual(store.previews, 1)

    def test_ten_am_preserves_afternoon_report(self):
        store = FakeStore(lambda: stamp('10:00:00'), end='14:45:00')
        run(store, write=True, emit=lambda value: None)
        self.assertEqual(store.written, 0)

    def test_conflict_reloads_instead_of_reusing_revision(self):
        store = FakeStore(lambda: stamp('10:00:00'))
        original = store.archive
        seen = []
        def archive(revision):
            seen.append(revision)
            if len(seen) == 1:
                raise ConflictError('changed')
            return original(revision)
        store.archive = archive
        run(store, write=True, emit=lambda value: None)
        self.assertEqual(seen, ['1', '2'])
        self.assertEqual(store.written, 1)


if __name__ == '__main__':
    unittest.main()
