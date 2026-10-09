const { test } = require('node:test');
const assert = require('node:assert/strict');
const core = require('../manager-core.js');
const NOW = Date.parse('2026-10-06T00:00:00Z');
const sample = () => ({ id: 'test-event', date: '2026-10-08', speakerName: 'Speaker', experiences: [], interests: [] });

test('role labels normalize without duplicating Student or rewriting completed degrees', () => {
  for (const [input, expected] of [['Associate professor@DUT', 'Associate Professor@DUT'], ['PhD@DUT', 'PhD Student@DUT'],
    ['PhD Student @ DUT', 'PhD Student @ DUT'], ['PhD student', 'PhD Student'], ['Visiting PhD student', 'Visiting PhD Student'],
    ['PhD in Mathematics', 'PhD in Mathematics'], ['PhD (Mathematics)', 'PhD (Mathematics)'], ['PhD/MSc', 'PhD/MSc'], ['Custom position', 'Custom position']]) {
    assert.equal(core.normalizeRole(input), expected);
    assert.equal(core.normalizeRole(core.normalizeRole(input)), expected);
  }
  const event = core.validate({ ...sample(), speakerAffiliation: 'PhD@DUT', title: 'PhD', abstract: 'Associate professor',
    experiences: [{ position: 'Associate professor' }, { position: 'PhD in Mathematics' }] }, NOW);
  assert.equal(event.speakerAffiliation, 'PhD Student@DUT');
  assert.deepEqual(event.experiences.map(row => row.position), ['Associate Professor', 'PhD in Mathematics']);
  assert.deepEqual([event.title, event.abstract], ['PhD', 'Associate professor']);
  assert.throws(() => core.validate({ ...sample(), speakerAffiliation: 'x'.repeat(346) + ' PhD' }, NOW));
});

test('role formatting updates can restore drafts while real report edits still conflict', () => {
  const old = { ...sample(), sourceKey: 'a'.repeat(64), speakerAffiliation: 'Associate professor@DUT' };
  const current = { ...old, sourceKey: 'b'.repeat(64), speakerAffiliation: 'Associate Professor@DUT' };
  assert.equal(core.sameExceptRoleFormatting(current, old), true);
  assert.equal(core.sameExceptRoleFormatting({ ...current, title: 'Remote title edit' }, old), false);
  assert.equal(core.sameExceptRoleFormatting(current, { ...old, speakerAffiliation: current.speakerAffiliation }), true);
  assert.equal(old.sourceKey, 'a'.repeat(64));
  assert.equal(current.sourceKey, 'b'.repeat(64));
});
test('new reports receive the agreed defaults', () => {
  const event = core.validate(sample(), NOW);
  assert.deepEqual([event.startTime, event.endTime, event.place, event.title, event.abstract], ['09:00', '09:45', 'Room 114', 'TBA', 'TBA']);
});
test('past starts, impossible dates and reversed times are rejected', () => {
  for (const changes of [{ date: '2026-10-01' }, { date: '2026-02-30' }, { startTime: '25:00' }, { startTime: '10:00', endTime: '09:00' }]) {
    assert.throws(() => core.validate({ ...sample(), ...changes }, NOW));
  }
});
test('interests use commas and exactly one final period', () => {
  assert.equal(core.interestSentence(['PDE, ', 'Fluid dynamics.', '']), 'PDE, Fluid dynamics.');
  assert.equal(core.interestSentence([]), '');
});
test('custom positions and current filled text survive validation', () => {
  const input = { ...sample(), title: 'Filled title', abstract: 'Filled abstract', experiences: [{ period: '2020–2026', position: 'Custom position', university: 'University', country: 'China' }] };
  assert.equal(core.validate(input, NOW).experiences[0].position, 'Custom position');
  assert.equal(core.validate(input, NOW).title, 'Filled title');
});
test('structured values and path-like identities are rejected', () => {
  assert.throws(() => core.validate({ ...sample(), id: '../file' }, NOW));
  assert.throws(() => core.validate({ ...sample(), title: { html: 'unsafe' } }, NOW));
});
test('editor rejects content which publication or the template cannot accept', () => {
  for (const changes of [{ title: '<img src=x>' }, { title: '\ud800' }, { sourceKey: 'invalid' },
    { date: '0001-10-08' }, { endDate: '2026-11-01' },
    { interests: ['x'.repeat(301)] }, { experiences: [{ period: 'x'.repeat(121) }] }]) {
    assert.throws(() => core.validate({ ...sample(), ...changes }, NOW));
  }
});
