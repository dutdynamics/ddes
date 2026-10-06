"""Remote-independent safety checks for the seminar manager (2026-10-06)."""
from copy import deepcopy
import base64
from datetime import datetime
from hashlib import sha256
import unittest
from unittest.mock import patch

from archive_events import archive
from manager_store import ConflictError, GitHubError, Store, apply_events, parse_events, validate_event


NOW = datetime.fromisoformat('2026-10-06T10:00:00+08:00')
REVISION = '1' * 40


def card(identity='', day='Oct 8, 2026', hours='9:00am - 9:45am', speaker='Alice (PhD@DUT)', title='A &amp; B', past=False):
    attr = f' id="{identity}"' if identity else ''
    status = 'past' if past else 'upcoming'
    return f'''<article class="seminar {status}-seminar"{attr} data-extra="preserve-me">
<h2 class="seminar-title">{title}</h2><dl class="meta-info">
<div class="meta-item"><dt>Speaker:</dt><dd>{speaker}</dd></div>
<div class="meta-item"><dt>Date:</dt><dd>{day}</dd></div>
<div class="meta-item"><dt>Time:</dt><dd>{hours}</dd></div>
<div class="meta-item"><dt>Place:</dt><dd>Room 111-A</dd></div></dl>
<section class="description"><p>Keep $x^2$ and <em>formatting</em>.<br>
Another paragraph.</p></section><footer>Unknown content stays.</footer></article>'''


def page(cards, old=''):
    return f'<main><section id="home">{cards}</section><section id="past"><section id="past-fall2026">{old}</section></section></main>'


class ParsingTests(unittest.TestCase):
    def test_defaults_and_strict_future_start(self):
        event = validate_event({'id': 'new-report', 'date': '2026-10-08', 'speakerName': 'Bob'}, NOW)
        self.assertEqual((event['startTime'], event['endTime'], event['place'], event['title'], event['abstract']),
                         ('09:00', '09:45', 'Room 114', 'TBA', 'TBA'))
        with self.assertRaisesRegex(ValueError, 'not started'):
            validate_event(event, datetime.fromisoformat('2026-10-08T09:00:00+08:00'))
        self.assertEqual(validate_event(event, datetime.fromisoformat('2026-10-08T00:59:59+00:00'))['date'], '2026-10-08')

    def test_preserves_existing_values_and_profile(self):
        identity = 'event-2026-10-08-a-b'
        profile = {identity: {'experiences': [{'period': '2024–Present', 'position': 'Custom professor', 'university': 'DUT', 'country': 'China'}],
                              'interests': ['Partial differential equations,', 'Dynamics.']}}
        html = page(card())
        result = parse_events(html, profile, NOW)
        self.assertEqual(result['warnings'], [])
        event = result['events'][0]
        self.assertEqual(event['id'], identity)
        self.assertEqual(event['place'], 'Room 111-A')
        self.assertEqual(event['title'], 'A & B')
        self.assertEqual(event['speakerName'], 'Alice')
        self.assertEqual(event['speakerAffiliation'], 'PhD@DUT')
        self.assertEqual(event['abstract'], 'Keep $x^2$ and formatting.\nAnother paragraph.')
        self.assertEqual(event['sourceKey'], sha256(card().encode()).hexdigest())
        self.assertEqual(event['interests'], ['Partial differential equations', 'Dynamics'])
        self.assertEqual(profile[identity]['interests'][0], 'Partial differential equations,')

    def test_started_and_archived_reports_are_excluded(self):
        html = page(card('started', 'Oct 6, 2026', '9am - 12pm') + card('future'), card('past', past=True))
        self.assertEqual([event['id'] for event in parse_events(html, now=NOW)['events']], ['future'])

    def test_unknown_date_time_and_multiple_sessions_keep_warnings(self):
        html = page(card('bad-date', 'Feb 30, 2027') + card('bad-time', hours='TBA') +
                    card('sessions', hours='9am - 10am and 2pm - 3pm'))
        result = parse_events(html, now=NOW)
        self.assertEqual(result['events'], [])
        self.assertEqual(len(result['warnings']), 3)

    def test_multiday_retains_dates(self):
        event = parse_events(page(card('range', 'Oct 8-9, 2026')), now=NOW)['events'][0]
        self.assertEqual(event['endDate'], '2026-10-09')

    def test_fallback_id_reserves_later_explicit_and_non_report_ids(self):
        reserved = 'event-2026-10-08-a-b'
        html = page(card() + card(reserved, 'Oct 15, 2026', speaker='Later'))
        events = parse_events(html, now=NOW)['events']
        self.assertEqual([event['id'] for event in events], [reserved + '-2', reserved])
        html = '<a id="' + reserved + '">Unrelated anchor</a>' + page(card())
        self.assertEqual(parse_events(html, now=NOW)['events'][0]['id'], reserved + '-2')

    def test_explicit_id_precedes_manager_attribute_like_calendar(self):
        html = page(card('calendar-id').replace('data-extra="preserve-me"', 'data-extra="preserve-me" data-manager-id="older-id"'))
        self.assertEqual(parse_events(html, now=NOW)['events'][0]['id'], 'calendar-id')

    def test_invalid_input(self):
        base = {'id': 'new', 'date': '2026-10-08', 'speakerName': 'Bob'}
        for key, value in [('id', '../escape'), ('date', '2026-02-30'), ('startTime', '24:00'),
                           ('endTime', '08:59'), ('title', '<script>alert(1)</script>'),
                           ('abstract', 'A\x00B'), ('speakerName', ''), ('interests', 'not a list'),
                           ('endDate', '2026-11-01'), ('title', 'a' * 801)]:
            with self.subTest(key=key, value=value):
                with self.assertRaises(ValueError):
                    validate_event(dict(base, **{key: value}), NOW)
        # Mathematics comparisons and TeX are ordinary inert text.
        self.assertEqual(validate_event(dict(base, title='For x < y & z > 0: $x^2$'), NOW)['title'], 'For x < y & z > 0: $x^2$')

    def test_builder_field_limits_and_numeric_uuid_ids(self):
        base = {'id': '9bdcedef-19e6-4f29-98b2-0eb6a49341d4', 'date': '2026-10-08', 'speakerName': 'Bob'}
        self.assertEqual(validate_event(base, NOW)['id'], base['id'])
        for field, maximum in (('id', 160), ('title', 800), ('abstract', 20000),
                               ('speakerName', 180), ('speakerAffiliation', 350), ('place', 180)):
            with self.subTest(field=field):
                self.assertEqual(len(validate_event(dict(base, **{field: 'a' * maximum}), NOW)[field]), maximum)
                with self.assertRaises(ValueError):
                    validate_event(dict(base, **{field: 'a' * (maximum + 1)}), NOW)
        for field, maximum in (('period', 120), ('position', 180), ('university', 260), ('country', 120)):
            with self.subTest(field=field):
                valid = dict(base, experiences=[{field: 'a' * maximum}])
                self.assertEqual(len(validate_event(valid, NOW)['experiences'][0][field]), maximum)
                with self.assertRaises(ValueError):
                    validate_event(dict(base, experiences=[{field: 'a' * (maximum + 1)}]), NOW)
        self.assertEqual(len(validate_event(dict(base, interests=['x' * 300] * 100), NOW)['interests']), 100)
        with self.assertRaises(ValueError):
            validate_event(dict(base, interests=['x'] * 101), NOW)
        with self.assertRaises(ValueError):
            validate_event(dict(base, interests=['x' * 301]), NOW)
        self.assertEqual(len(validate_event(dict(base, experiences=[{'period': '2025'}] * 50), NOW)['experiences']), 50)
        with self.assertRaises(ValueError):
            validate_event(dict(base, experiences=[{'period': '2025'}] * 51), NOW)

    def test_internal_started_read_retains_strict_default_validation(self):
        html = page(card('already-started', 'Oct 6, 2026', '9am - 12pm'))
        self.assertEqual(parse_events(html, now=NOW)['events'], [])
        events = parse_events(html, now=NOW, include_started=True)['events']
        self.assertEqual(len(events), 1)
        with self.assertRaises(ValueError):
            validate_event(events[0], NOW)
        self.assertEqual(validate_event(events[0], NOW, allow_started=True)['id'], 'already-started')


class PatchingTests(unittest.TestCase):
    def setUp(self):
        self.past = card('past-report', 'Sep 24, 2026', past=True)
        self.other = card('keep-future', 'Oct 15, 2026', speaker='Carol (Professor)')
        self.html = page(card('editable') + self.other, self.past)
        self.original = parse_events(self.html, now=NOW)['events']

    def test_noop_is_byte_identical(self):
        self.assertEqual(apply_events(self.html, self.original, deepcopy(self.original)), self.html)

    def test_single_field_changes_keep_unknown_html_and_archives(self):
        updated = deepcopy(self.original)
        updated[0]['title'] = 'For x < y & $x^2$'
        result = apply_events(self.html, self.original, updated)
        self.assertIn('For x &lt; y &amp; $x^2$', result)
        self.assertIn('data-extra="preserve-me"', result)
        self.assertIn('<em>formatting</em>', result)
        self.assertIn('<footer>Unknown content stays.</footer>', result)
        self.assertIn(self.other, result)
        self.assertIn(self.past, result)
        self.assertIn('data-manager-id="editable"', result)

    def test_abstract_changes_only_description(self):
        updated = deepcopy(self.original)
        updated[0]['abstract'] = 'Paragraph one & two\nParagraph three.'
        result = apply_events(self.html, self.original, updated)
        self.assertIn('<p>Paragraph one &amp; two<br>Paragraph three.</p>', result)
        self.assertIn('<footer>Unknown content stays.</footer>', result)

    def test_dates_and_times_patch_with_shared_parser_formats(self):
        updated = deepcopy(self.original)
        updated[0].update({'date': '2026-10-10', 'endDate': '2026-10-11', 'startTime': '14:00', 'endTime': '14:45'})
        result = apply_events(self.html, self.original, updated)
        reparsed = parse_events(result, now=NOW)['events'][0]
        self.assertEqual((reparsed['date'], reparsed['endDate'], reparsed['startTime']), ('2026-10-10', '2026-10-11', '14:00'))

    def test_append_new_reports_ascending_without_reordering_existing(self):
        later = validate_event({'id': 'later', 'date': '2026-11-19', 'speakerName': 'Later'}, NOW)
        earlier = validate_event({'id': 'earlier', 'date': '2026-11-05', 'speakerName': 'Earlier'}, NOW)
        result = apply_events(self.html, self.original, self.original + [later, earlier])
        self.assertLess(result.index(self.other), result.index('id="earlier"'))
        self.assertLess(result.index('id="earlier"'), result.index('id="later"'))
        self.assertIn(self.past, result)

    def test_earlier_new_report_is_inserted_between_existing_dates(self):
        middle = validate_event({'id': 'new-oct9', 'date': '2026-10-09', 'speakerName': 'Middle'}, NOW)
        same_day = validate_event({'id': 'new-oct8-afternoon', 'date': '2026-10-08', 'startTime': '14:00', 'endTime': '14:45', 'speakerName': 'Afternoon'}, NOW)
        result = apply_events(self.html, self.original, self.original + [middle, same_day])
        ids = [event['id'] for event in parse_events(result, now=NOW)['events']]
        self.assertEqual(ids, ['editable', 'new-oct8-afternoon', 'new-oct9', 'keep-future'])
        self.assertIn(card('editable'), result)
        self.assertIn(self.other, result)
        self.assertIn(self.past, result)

    def test_new_id_cannot_shadow_page_navigation(self):
        shadow = validate_event({'id': 'home', 'date': '2026-11-19', 'speakerName': 'Shadow'}, NOW)
        with self.assertRaisesRegex(ValueError, 'already used'):
            apply_events(self.html, self.original, self.original + [shadow])

    def test_no_deletion_duplicate_or_archive_replacement(self):
        with self.assertRaisesRegex(ValueError, 'deleted'):
            apply_events(self.html, self.original, self.original[:1])
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            apply_events(self.html, self.original, self.original + [self.original[0]])
        replacement = validate_event({'id': 'past-report', 'date': '2026-11-19', 'speakerName': 'Intruder'}, NOW)
        with self.assertRaisesRegex(ValueError, 'replace'):
            apply_events(self.html, self.original, self.original + [replacement])
        duplicate = deepcopy(self.original[0])
        duplicate.update({'id': 'duplicate-new', 'sourceKey': ''})
        with self.assertRaisesRegex(ValueError, 'Duplicate speaker'):
            apply_events(self.html, self.original, self.original + [duplicate])

    def test_source_key_cannot_be_stale_or_forged(self):
        changed_html = self.html.replace('data-extra="preserve-me"', 'data-extra="changed"', 1)
        with self.assertRaises(ConflictError):
            apply_events(changed_html, self.original, self.original)
        forged = deepcopy(self.original)
        forged[0]['sourceKey'] = '0' * 64
        with self.assertRaises(ConflictError):
            apply_events(self.html, self.original, forged)

    def test_pdf_uploads_are_rejected_and_empty_legacy_argument_is_safe(self):
        for attachment in ({'editable': 'ignored.pdf'}, {'unknown': 'ignored.pdf'},
                           'ignored.pdf', [], {'editable': object()}):
            with self.subTest(attachment=type(attachment).__name__):
                with self.assertRaisesRegex(ValueError, 'offline use only'):
                    apply_events(self.html, self.original, self.original, attachment)
        self.assertEqual(apply_events(self.html, self.original, self.original, {}), self.html)

    def test_changed_title_keeps_calendar_id_after_archiving_without_pdf_link(self):
        original_html = page(card(), self.past)
        events = parse_events(original_html, now=NOW)['events']
        identity = events[0]['id']
        updated = deepcopy(events)
        updated[0]['title'] = 'Completely different title'
        result = apply_events(original_html, events, updated)
        reparsed = parse_events(result, now=NOW)['events']
        self.assertEqual(reparsed[0]['id'], identity)
        self.assertNotIn('Download seminar PDF', result)
        self.assertNotIn('data-manager-pdf', result)
        archived, moved, warnings = archive(result, datetime.fromisoformat('2026-10-09T09:00:00+08:00'))
        self.assertEqual(len(moved), 1)
        self.assertEqual(warnings, [])
        self.assertIn(f'id="{identity}"', archived)
        self.assertNotIn('Download seminar PDF', archived)
        self.assertIn(self.past, archived)
        self.assertEqual(parse_events(archived, now=NOW)['events'], [])

    def test_unedited_data_date_and_time_markup_are_preserved(self):
        html = self.html.replace('id="editable"', 'id="editable" data-date="2026-10-08"', 1)
        events = parse_events(html, now=NOW)['events']
        changed = deepcopy(events)
        changed[0]['title'] = 'Only the title changes'
        result = apply_events(html, events, changed)
        self.assertIn('data-date="2026-10-08"', result)
        self.assertIn('<dd>9:00am - 9:45am</dd>', result)
        self.assertIn('<em>formatting</em>', result)


class FakeStore(Store):
    def __init__(self, html, profile=None):
        super().__init__(now=NOW)
        self.html, self.profile = html, profile or {}
        self.main_revision = REVISION
        self.calls = []
        self.protected = False
        self.race = False

    def _read(self):
        return self.main_revision, self.html, self.profile

    def _head(self):
        return self.main_revision

    def _api(self, endpoint, method='GET', payload=None, missing_ok=False):
        self.calls.append((endpoint, method, deepcopy(payload)))
        if '/git/commits/' in endpoint:
            return {'tree': {'sha': '2' * 40}}
        if endpoint.endswith('git/blobs'):
            return {'sha': '3' * 40}
        if endpoint.endswith('git/trees'):
            return {'sha': '4' * 40}
        if endpoint.endswith('git/commits'):
            if self.race:
                self.main_revision = '9' * 40
            return {'sha': '5' * 40}
        if endpoint.endswith('git/refs'):
            return {'ref': payload['ref']}
        if endpoint.endswith('pulls'):
            return {'number': 7, 'html_url': 'https://github.com/dutdynamics/ddes/pull/7'}
        if endpoint.endswith('pulls/7'):
            return {'head': {'sha': '5' * 40}, 'mergeable': True, 'mergeable_state': 'blocked' if self.protected else 'clean'}
        if endpoint.endswith('/merge'):
            return {'merged': True, 'sha': '6' * 40}
        raise AssertionError(endpoint)


class PublishingTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore(page(card('editable')))
        self.events = self.store.snapshot()['events']

    def test_no_changes_do_not_create_commits(self):
        result = self.store.publish(self.events, REVISION)
        self.assertEqual(result['status'], 'unchanged')
        self.assertEqual(self.store.calls, [])

    def test_revision_conflict_stops_before_any_write(self):
        self.store.main_revision = '0' * 40
        with self.assertRaises(ConflictError):
            self.store.publish(self.events, REVISION)
        self.assertEqual(self.store.calls, [])

    def test_race_stops_before_publishing_branch(self):
        self.events[0]['title'] = 'New title'
        self.store.race = True
        with self.assertRaises(ConflictError):
            self.store.publish(self.events, REVISION)
        self.assertFalse(any(path.endswith('git/refs') for path, _, _ in self.store.calls))

    def test_atomic_tree_branch_and_matching_head_merge(self):
        self.events[0]['title'] = 'New title'
        self.events[0]['experiences'] = [{'period': '2025–Present', 'position': 'Professor', 'university': 'DUT', 'country': 'China'}]
        result = self.store.publish(self.events, REVISION)
        self.assertEqual(result['status'], 'merged')
        tree = next(body for endpoint, _, body in self.store.calls if endpoint.endswith('git/trees'))
        self.assertEqual({item['path'] for item in tree['tree']}, {'index.html', 'seminar-profiles.json'})
        ref = next(body for endpoint, _, body in self.store.calls if endpoint.endswith('git/refs'))
        self.assertTrue(ref['ref'].startswith('refs/heads/codex/seminar-manager-'))
        merge = next(body for endpoint, _, body in self.store.calls if endpoint.endswith('/merge'))
        self.assertEqual(merge['sha'], '5' * 40)
        self.assertFalse(any(body and body.get('force') for _, _, body in self.store.calls))

    def test_branch_protection_returns_reviewable_pr(self):
        self.events[0]['title'] = 'New title'
        self.store.protected = True
        result = self.store.publish(self.events, REVISION)
        self.assertEqual(result['status'], 'pending_review')
        self.assertIn('/pull/7', result['prUrl'])
        self.assertFalse(any(path.endswith('/merge') for path, _, _ in self.store.calls))

    def test_pdf_upload_is_rejected_before_remote_reads_or_writes(self):
        for attachment in ({'editable': 'generated.pdf'}, {'unknown': object()},
                           'generated.pdf', []):
            with self.subTest(attachment=type(attachment).__name__):
                with patch.object(self.store, '_read') as remote_read:
                    with self.assertRaisesRegex(ValueError, 'offline use only'):
                        self.store.publish(self.events, REVISION, attachment)
                    remote_read.assert_not_called()
        self.assertEqual(self.store.calls, [])

    def test_empty_legacy_pdf_argument_keeps_noop_unchanged(self):
        self.assertEqual(self.store.publish(self.events, REVISION, {})['status'], 'unchanged')
        self.assertEqual(self.store.calls, [])

    def test_adding_report_never_generates_pdf_download_link(self):
        added = validate_event({'id': 'new-report', 'date': '2026-11-19', 'speakerName': 'Bob'}, NOW)
        self.assertEqual(self.store.publish(self.events + [added], REVISION)['status'], 'merged')
        tree = next(body for path, _, body in self.store.calls if path.endswith('git/trees'))
        self.assertEqual({item['path'] for item in tree['tree']}, {'index.html'})
        html_blob = next(body for path, _, body in self.store.calls if path.endswith('git/blobs'))
        published = base64.b64decode(html_blob['content']).decode()
        self.assertIn('id="new-report"', published)
        self.assertNotIn('Download seminar PDF', published)
        self.assertNotIn('data-manager-pdf', published)

    def crossing_start(self):
        first = card('starting', 'Oct 8, 2026')
        second = card('future', 'Oct 15, 2026', speaker='Future (DUT)')
        self.store = FakeStore(page(first + second))
        self.events = self.store.snapshot()['events']
        self.store.now = datetime.fromisoformat('2026-10-08T09:00:00+08:00')
        return first, second

    def test_started_unchanged_baseline_does_not_block_other_update(self):
        first, _ = self.crossing_start()
        self.events[1]['title'] = 'Changed future title'
        result = self.store.publish(self.events, REVISION)
        self.assertEqual(result['status'], 'merged')
        html_blob = next(body for path, _, body in self.store.calls if path.endswith('git/blobs'))
        published_html = base64.b64decode(html_blob['content']).decode()
        self.assertIn(first, published_html)
        self.assertIn('Changed future title', published_html)
        self.assertNotIn('data-manager-id="starting"', published_html)

    def test_started_unchanged_row_can_be_omitted(self):
        first, _ = self.crossing_start()
        self.events[1]['title'] = 'Changed future title'
        self.assertEqual(self.store.publish(self.events[1:], REVISION)['status'], 'merged')
        html_blob = next(body for path, _, body in self.store.calls if path.endswith('git/blobs'))
        self.assertIn(first, base64.b64decode(html_blob['content']).decode())

    def test_started_modified_row_is_refused(self):
        self.crossing_start()
        self.events[0]['title'] = 'Cannot edit started'
        with self.assertRaisesRegex(ValueError, 'started'):
            self.store.publish(self.events, REVISION)
        self.assertEqual(self.store.calls, [])

    def test_still_future_deletion_is_refused_after_another_starts(self):
        self.crossing_start()
        with self.assertRaisesRegex(ValueError, 'deleted'):
            self.store.publish(self.events[:1], REVISION)
        self.assertEqual(self.store.calls, [])

    def test_started_unchanged_noop_remains_noop(self):
        self.crossing_start()
        self.assertEqual(self.store.publish(self.events, REVISION)['status'], 'unchanged')
        self.assertEqual(self.store.calls, [])


if __name__ == '__main__':
    unittest.main()
