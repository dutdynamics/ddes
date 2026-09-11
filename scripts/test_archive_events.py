import unittest
from datetime import datetime

from archive_events import archive, Document


def card(day='Sep 10, 2026', hours='9:00am - 9:45am', title='A &amp; B'):
    return f'''<article class="seminar upcoming-seminar" id="keep-id">
<h2 class="seminar-title">{title}</h2><dl>
<div class="meta-item"><dt>Date:</dt><dd>{day}</dd></div>
<div class="meta-item"><dt>Time:</dt><dd>{hours}</dd></div>
<div class="meta-item"><dt>Speaker:</dt><dd>Speaker 中文</dd></div>
<div class="meta-item"><dt>Place:</dt><dd>Room 114</dd></div></dl>
<section class="description"><p>Keep $x^2$ and <em>formatting</em>.</p></section></article>'''


def page(cards):
    return f'''<main><div id="semester-navigation"></div><section id="home">{cards}</section>
<section id="past"><section id="past-fall2026" class="sub-page-content semester-section"></section></section></main>'''


class ArchiveTests(unittest.TestCase):
    def check_at(self, html, instant):
        return archive(html, datetime.fromisoformat(instant))

    def test_end_boundary_and_timezone(self):
        original = page(card())
        self.assertEqual(self.check_at(original, '2026-09-10T01:44:59+00:00')[0], original)
        updated, moved, _ = self.check_at(original, '2026-09-10T01:45:00+00:00')
        self.assertEqual(len(moved), 1)
        doc = Document(updated)
        self.assertEqual(doc.by_id('keep-id').parent.attrs['id'], 'past-fall2026')
        self.assertIn(card().replace('upcoming-seminar', 'past-seminar'), updated)
        self.assertEqual(self.check_at(updated, '2026-09-11T09:00:00+08:00')[0], updated)

    def test_multiday_waits_for_last_day(self):
        original = page(card('May 21-22, 2026', '14:00 - 15:00'))
        self.assertEqual(self.check_at(original, '2026-05-21T16:00:00+08:00')[0], original)
        updated, moved, _ = self.check_at(original, '2026-05-22T15:00:00+08:00')
        self.assertEqual(len(moved), 1)
        self.assertEqual(Document(updated).by_id('keep-id').parent.attrs['id'], 'past-spring2026')
        self.assertIn('data-target="past-spring2026"', updated)

    def test_missing_invalid_or_single_time_waits_until_next_day(self):
        for hours in ['', 'TBA', '9am', '9am - 29:00', '9am - 13pm', '9am - 9:99am']:
            original = page(card(hours=hours))
            self.assertEqual(self.check_at(original, '2026-09-10T23:59:59+08:00')[0], original)
            self.assertEqual(len(self.check_at(original, '2026-09-11T00:00:00+08:00')[1]), 1)

    def test_12_hour_clock(self):
        original = page(card(hours='11am – 12pm'))
        self.assertEqual(self.check_at(original, '2026-09-10T11:59:00+08:00')[0], original)
        self.assertEqual(len(self.check_at(original, '2026-09-10T12:00:00+08:00')[1]), 1)

    def test_invalid_date_is_kept_and_reported(self):
        for day in ['TBA', 'Feb 30, 2026', 'May 22-21, 2026']:
            original = page(card(day))
            updated, moved, skipped = self.check_at(original, '2026-09-11T09:00:00+08:00')
            self.assertEqual(updated, original)
            self.assertEqual(moved, [])
            self.assertEqual(len(skipped), 1)

    def test_future_new_semester_and_january(self):
        for day, instant, target in [('Jan 7, 2027', '2027-01-08', 'past-fall2026'),
                                     ('Sep 9, 2027', '2027-09-10', 'past-fall2027')]:
            updated, _, _ = self.check_at(page(card(day)), instant + 'T09:00:00+08:00')
            self.assertEqual(Document(updated).by_id('keep-id').parent.attrs['id'], target)

    def test_multiple_reports_preserved_and_oldest_first(self):
        older = card(title='Older').replace('keep-id', 'older')
        newer = card('Sep 11, 2026', title='Newer').replace('keep-id', 'newer')
        future = card('Sep 17, 2026', title='Future').replace('keep-id', 'future')
        updated, moved, _ = self.check_at(page(newer + older + future), '2026-09-12T09:00:00+08:00')
        self.assertEqual(len(moved), 2)
        doc = Document(updated)
        self.assertEqual(doc.by_id('future').parent.attrs['id'], 'home')
        self.assertLess(doc.by_id('older').start, doc.by_id('newer').start)

    def test_new_archives_append_below_existing_reports(self):
        existing = card('Sep 3, 2026').replace('keep-id', 'existing').replace('upcoming-seminar', 'past-seminar')
        original = page(card()).replace('class="sub-page-content semester-section">',
                                        'class="sub-page-content semester-section">' + existing)
        updated, moved, _ = self.check_at(original, '2026-09-11T09:00:00+08:00')
        doc = Document(updated)
        self.assertEqual(len(moved), 1)
        self.assertLess(doc.by_id('existing').start, doc.by_id('keep-id').start)
        self.assertIn(existing, updated)
        self.assertEqual(self.check_at(updated, '2026-09-11T09:00:00+08:00')[0], updated)

    def test_malformed_structure_fails_without_result(self):
        with self.assertRaises(ValueError):
            self.check_at(page(card()).replace('</article>', ''), '2026-09-11T09:00:00+08:00')
        with self.assertRaises(ValueError):
            self.check_at(page(card()), '2026-09-11T09:00:00')


if __name__ == '__main__':
    unittest.main()
