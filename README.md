# DDES

Last updated: 2026-09-11 (UTC+8).

DUT Differential Equations Seminar

## About

This repository contains the webpage for the DUT Differential Equations Seminar.

## Usage

Open `index.html` in a browser.

## Website

GitHub Pages publishes the main branch at https://dutdynamics.github.io/ddes/

## Calendar and maintenance

The shared calendar reads reports from the event cards in `index.html`. Its labels
are Past, Upcoming (within seven days), and Scheduled. Report times use Dalian
time (UTC+8). New reports default to Room 114; leave the title and abstract as TBA
until supplied by the organizer. Do not infer missing speakers, dates, or times.

Official holiday ranges are maintained in `holidays.js`, with the source URL,
publication date, and verification date. Only holidays falling on the regular
Thursday seminar slot are marked red and labeled **Public holiday**. Other days
within a holiday range retain their normal calendar appearance. The calendar
displays only Public holiday, without a festival name or source link. Sources
remain in the maintenance data. Reports listed on a highlighted date remain
reachable; a holiday does not silently cancel or reschedule a report.

### Check on 2026-09-10

- Source: [DUT holiday notice, published 2026-09-07](https://kfqxqzhb.dlut.edu.cn/info/1071/2002.htm).
- No public holiday overlaps September 10–24. The announced Mid-Autumn holiday
  is September 25–27 and National Day holiday is October 1–7. Only October 1 is
  a Thursday and receives the red calendar label.
- September 20 and October 10 are makeup workdays, not public holidays.
- The Tencent Time Plan link supplied by the organizer denied anonymous reading
  and export. No new speakers or times could be verified or imported.
- Follow-up cadence: check official DUT notices every two weeks; remind the
  organizer each Monday to submit the latest Time Plan export or screenshot.
  These follow-ups run in the Codex desktop task, not in GitHub Pages.

### Friday archive check (2026-09-11)

The existing Codex desktop follow-up also checks ended reports every Friday at
09:00 Beijing time. It syncs the latest repository, runs the archive program,
reviews the changes and publishes them through a pull request. The computer and
Codex app must be running for this local scheduled task. If no report has ended,
no commit is created.

Run `python scripts/archive_events.py` to preview eligible reports, then add
`--write` to move them from Upcoming Events into the matching Past Events
semester. The program preserves each card's HTML, title, abstract, speaker,
location and ID, changing only its upcoming/past class. Existing shared calendar
styles continue to apply. Missing semester sections and navigation buttons are
created automatically (fall: September–January; spring: February–August).

Reports become eligible at their end time in UTC+8. Multi-day reports wait for
the final day's end time. Missing or invalid end times wait until the next day;
unrecognized dates are left untouched and printed for review. Repeated runs do
not duplicate reports. Structural HTML errors stop the operation before writing.

For a reproducible preview, use
`python scripts/archive_events.py --now 2026-09-11T09:00:00+08:00`.
Run the checks with `python -m unittest discover -s scripts -p 'test_*.py'`.
