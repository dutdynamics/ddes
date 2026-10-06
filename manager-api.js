(() => {
  'use strict';
  const core = window.DDESManagerCore;
  let nonce = '', revision = '', local = false;
  async function read(response) {
    if (!response.ok) {
      let message = `请求失败 (${response.status})`;
      try { message = (await response.json()).error || message; } catch { /* Use the HTTP error. */ }
      throw new Error(message);
    }
    return response;
  }
  async function post(path, data) {
    if (!local) throw new Error('请先双击 start-manager.cmd 启动本地助手，再打开本地管理页。');
    return read(await fetch(path, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-DDES-Nonce': nonce },
      body: JSON.stringify(data), credentials: 'same-origin'
    }));
  }
  async function load() {
    local = ['127.0.0.1', 'localhost'].includes(location.hostname);
    if (!local) throw new Error('此管理工具仅供内部使用，请双击 start-manager.cmd 后从本机助手打开。');
    const status = await (await read(await fetch('/api/status', { cache: 'no-store' }))).json();
    if (status.service !== 'ddes-manager' || !status.local || typeof status.nonce !== 'string' || !status.nonce) {
      local = false;
      throw new Error('未连接到内部日程助手，请使用 start-manager.cmd 启动。');
    }
    nonce = status.nonce;
    const snapshot = await (await read(await fetch('/api/events', { cache: 'no-store' }))).json();
    revision = snapshot.revision;
    return { ...snapshot, status: { ...status, local: true } };
  }
  async function publish(events) {
    const response = await post('/api/publish', { events, revision, confirmPublic: true });
    const result = await response.json();
    if (result.revision && ['merged', 'unchanged'].includes(result.status)) revision = result.revision;
    return { ...result, merged: result.status === 'merged' || result.merged === true, url: result.prUrl || result.url };
  }
  async function generatePDF(event, onStatus = () => {}) {
    onStatus('正在按模板生成 PDF…');
    const response = await post('/api/report', { event: core.validate(event) });
    const blob = await response.blob();
    if (blob.type !== 'application/pdf') throw new Error('生成结果不是有效的 PDF。');
    return { url: URL.createObjectURL(blob), filename: `DDES-Seminar-${event.date}.pdf` };
  }
  window.DDESManagerAPI = { load, publish, generatePDF, validate: core.validate, isEditable: core.isEditable, interestSentence: core.interestSentence };
})();
