const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { runInNewContext } = require('node:vm');
const source = readFileSync(join(__dirname, '../manager-api.js'), 'utf8');
function setup(hostname, fetch) {
  const window = { DDESManagerCore: { validate: event => event, isEditable: () => true, interestSentence: () => '' } };
  runInNewContext(source, { window, location: { hostname }, fetch });
  return window.DDESManagerAPI;
}
const response = value => ({ ok: true, json: async () => value });
test('public and network hosts cannot load or submit management data', async () => {
  for (const hostname of ['dutdynamics.github.io', '192.168.1.20', 'example.com']) {
    let calls = 0;
    const api = setup(hostname, async () => { calls++; throw new Error('Unexpected network access'); });
    await assert.rejects(api.load(), /仅供内部使用/);
    await assert.rejects(api.publish([]), /本地助手/);
    assert.equal(calls, 0);
  }
});
test('opening the file without the local assistant cannot load management data', async () => {
  const api = setup('', async () => { throw new Error('Unexpected network access'); });
  await assert.rejects(api.load(), /仅供内部使用/);
});
test('an unrelated localhost service cannot enable publishing', async () => {
  let calls = 0;
  const api = setup('localhost', async () => { calls++; return response({ service: 'other', local: true, nonce: 'other' }); });
  await assert.rejects(api.load(), /未连接到内部日程助手/);
  await assert.rejects(api.publish([]), /本地助手/);
  assert.equal(calls, 1);
});
test('the verified local assistant retains the source revision and request protection', async () => {
  const requests = [];
  const api = setup('127.0.0.1', async (path, options) => {
    requests.push({ path, options });
    if (path === '/api/status') return response({ service: 'ddes-manager', local: true, nonce: 'test-nonce' });
    if (path === '/api/events') return response({ events: [{ id: 'test' }], revision: 'main-revision' });
    return response({ status: 'pending_review', revision: 'pr-revision' });
  });
  const data = await api.load();
  assert.equal(data.events.length, 1);
  await api.publish(data.events);
  await api.publish(data.events);
  for (const request of requests.filter(item => item.path === '/api/publish')) {
    assert.equal(request.options.headers['X-DDES-Nonce'], 'test-nonce');
    assert.equal(JSON.parse(request.options.body).revision, 'main-revision');
    assert.equal(request.options.credentials, 'same-origin');
  }
});
