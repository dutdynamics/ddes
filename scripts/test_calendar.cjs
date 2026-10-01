// Run with: node --test scripts/test_calendar.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const cases = require('./event_time_cases.json');
const { dateKey, dalianDateKey, parseEventDates, reportTimes, reportBoundary } = require('../script.js');

for (const entry of cases.dates) {
  test(`calendar date: ${entry.raw || '(empty)'}`, () => {
    assert.deepEqual(parseEventDates(entry.raw).map(dateKey), entry.days);
  });
}
for (const entry of cases.times) {
  test(`report times on ${entry.day}: ${entry.raw || '(empty)'}`, () => {
    assert.deepEqual(reportTimes(entry.raw, entry.day), entry.minutes);
    const midnight = Date.parse(`${entry.day}T00:00:00+08:00`);
    assert.equal(reportBoundary(entry.raw, entry.day, true), midnight + (entry.minutes ? entry.minutes[1] : 1440) * 60000);
  });
}
test('Beijing date rolls over at UTC 16:00, independently of the visitor timezone', () => {
  assert.equal(dalianDateKey(new Date('2026-09-30T15:59:59Z')), '2026-09-30');
  assert.equal(dalianDateKey(new Date('2026-09-30T16:00:00Z')), '2026-10-01');
});
test('unknown end stays future until next Beijing midnight', () => {
  const end = reportBoundary('TBA', '2026-09-24', true);
  assert.equal(new Date(end).toISOString(), '2026-09-24T16:00:00.000Z');
  assert.ok(end > Date.parse('2026-09-24T15:59:59Z'));
});
