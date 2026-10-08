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
    await assert.rejects(api.previewArchive(), /本地助手/);
    await assert.rejects(api.archive('revision'), /本地助手/);
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
  await assert.rejects(api.previewArchive(), /本地助手/);
  await assert.rejects(api.archive('revision'), /本地助手/);
  assert.equal(calls, 1);
});
test('archiving verifies its preview revision without advancing the browser draft revision', async () => {
  const requests = [];
  const api = setup('localhost', async (path, options) => {
    requests.push({ path, options });
    if (path === '/api/status') return response({ service: 'ddes-manager', local: true, nonce: 'archive-nonce' });
    if (path === '/api/events') return response({ events: [{ id: 'editable' }], revision: 'draft-source' });
    if (path === '/api/archive' && options?.method === 'POST') return response({ status: 'merged', revision: 'archive-result', count: 1, prUrl: 'https://github.com/dutdynamics/ddes/pull/20' });
    if (path === '/api/archive') return response({ revision: 'latest-main', candidates: [{ date: '2026-10-08', speaker: 'Jiexin Sun' }], warnings: [] });
    return response({ status: 'pending_review' });
  });
  const snapshot = await api.load();
  const preview = await api.previewArchive();
  const result = await api.archive(preview.revision);
  assert.equal(result.merged, true);
  assert.equal(result.url, 'https://github.com/dutdynamics/ddes/pull/20');
  const archiveRequests = requests.filter(item => item.path === '/api/archive');
  assert.equal(archiveRequests[0].options.cache, 'no-store');
  for (const request of archiveRequests) {
    assert.equal(request.options.headers['X-DDES-Nonce'], 'archive-nonce');
    assert.equal(request.options.credentials, 'same-origin');
  }
  assert.deepEqual(JSON.parse(archiveRequests[1].options.body), { revision: 'latest-main', confirmArchive: true });
  await api.publish(snapshot.events);
  assert.equal(JSON.parse(requests.at(-1).options.body).revision, 'draft-source');
});
test('archive preview errors stay visible and incomplete previews cannot be submitted', async () => {
  let archiveRequests = 0;
  const api = setup('127.0.0.1', async path => {
    if (path === '/api/status') return response({ service: 'ddes-manager', local: true, nonce: 'test-nonce' });
    if (path === '/api/events') return response({ events: [], revision: 'main-revision' });
    archiveRequests++;
    return { ok: false, status: 409, json: async () => ({ error: '网站已有更新，请重新检测。' }) };
  });
  await api.load();
  await assert.rejects(api.previewArchive(), /网站已有更新/);
  await assert.rejects(api.archive('main-revision'), /网站已有更新/);
  for (const revision of ['', null, {}]) await assert.rejects(api.archive(revision), /重新检测/);
  assert.equal(archiveRequests, 2);
});
test('a failed verification cannot retain authorization from an earlier connection', async () => {
  let verifyFails = false;
  let archiveRequests = 0;
  const api = setup('localhost', async path => {
    if (path === '/api/status') {
      if (verifyFails) throw new Error('助手未连接');
      return response({ service: 'ddes-manager', local: true, nonce: 'test-nonce' });
    }
    if (path === '/api/events') return response({ events: [], revision: 'main-revision' });
    archiveRequests++;
    return response({ candidates: [] });
  });
  await api.load();
  verifyFails = true;
  await assert.rejects(api.load(), /助手未连接/);
  await assert.rejects(api.previewArchive(), /本地助手/);
  await assert.rejects(api.archive('revision'), /本地助手/);
  assert.equal(archiveRequests, 0);
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
