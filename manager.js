(() => {
  'use strict';

  const STORAGE_KEY = 'ddes-seminar-manager-draft-v1';
  const fields = ['speakerName', 'speakerAffiliation', 'date', 'startTime', 'endTime', 'place', 'title', 'abstract'];
  const weekdays = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
  const $ = id => document.getElementById(id);
  const clone = value => JSON.parse(JSON.stringify(value));
  const state = { events: [], baseline: [], revision: '', selectedId: null, local: false, busy: false, ready: false, savedAt: null };
  let saveTimer;

  const api = () => window.DDESManagerAPI;
  const eventById = id => state.events.find(event => event.id === id);
  const selected = () => eventById(state.selectedId);
  const timestamp = () => new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false });
  const editable = event => {
    try { return api().isEditable(event); } catch { return false; }
  };
  const plain = value => typeof value === 'string' ? value : '';
  const interestSentence = interests => {
    if (api()?.interestSentence) return api().interestSentence(interests);
    return interests.length ? `${interests.join(', ')}.` : '';
  };
  const fingerprint = event => JSON.stringify(event);
  const baselineById = id => state.baseline.find(event => event.id === id);
  const changed = event => !baselineById(event.id) || fingerprint(event) !== fingerprint(baselineById(event.id));
  const changedCount = () => state.events.filter(changed).length;
  const sortedEditable = () => state.events.filter(event => editable(event) || !event.date).sort((a, b) => (a.date || '9999').localeCompare(b.date || '9999') || plain(a.startTime).localeCompare(plain(b.startTime)));

  function notify(message, type = '') {
    $('message').textContent = message;
    $('message').className = `notice ${type}`;
    $('message').hidden = !message;
  }

  function operation(message, result, target = 'operation-status') {
    const box = $(target);
    box.replaceChildren();
    box.hidden = false;
    const content = document.createElement('span');
    content.textContent = message;
    box.append(content);
    if (result?.url) {
      try {
        const url = new URL(result.url, location.href);
        if (!['http:', 'https:', 'blob:'].includes(url.protocol)) throw new Error('invalid URL');
        const link = document.createElement('a');
        link.href = url.href;
        link.textContent = result.filename ? '下载 PDF' : '查看结果 ↗';
        link.style.marginLeft = '10px';
        if (result.filename) link.download = result.filename;
        else { link.target = '_blank'; link.rel = 'noopener noreferrer'; }
        box.append(link);
      } catch { /* An invalid returned URL is never inserted into the page. */ }
    }
  }

  function confirmAction(title, copy, label = '确认') {
    const dialog = $('confirm-dialog');
    $('dialog-title').textContent = title;
    $('dialog-copy').textContent = copy;
    $('dialog-confirm').textContent = label;
    return new Promise(resolve => {
      dialog.addEventListener('close', () => resolve(dialog.returnValue === 'confirm'), { once: true });
      dialog.returnValue = '';
      dialog.showModal();
    });
  }

  function setBusy(busy) {
    state.busy = busy;
    $('form-fields').disabled = busy || !selected();
    $('new-event').disabled = busy || !state.ready;
    $('new-event-empty').disabled = busy || !state.ready;
    $('import-file').disabled = busy || !state.ready;
    updateActions();
    renderList();
  }

  function updateActions() {
    const count = changedCount();
    const hasSelection = Boolean(selected());
    $('change-count').textContent = count ? `${count} 场报告有待发布的变更` : '没有待发布的变更';
    $('save-draft').disabled = !hasSelection || state.busy;
    $('generate-pdf').disabled = !hasSelection || !state.local || state.busy;
    $('publish').disabled = state.busy || !state.local || !count || !$('public-confirm').checked;
    $('archive-events').disabled = state.busy || !state.local || !state.ready;
    $('public-confirm').disabled = state.busy;
    $('discard-draft').disabled = state.busy || !count;
    $('export-draft').disabled = state.busy || !state.ready;
    $('publish-hint').textContent = state.local
      ? '发布仅更新日程与报告资料；PDF 只在本机生成和下载，供线下发布使用。'
      : '此管理工具仅供内部使用，请通过本机助手打开。';
    if (!count) $('draft-status').textContent = '网站内容尚未修改';
    else if (state.savedAt) $('draft-status').textContent = `草稿已保存 · ${state.savedAt.toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit' })}`;
    else $('draft-status').textContent = '草稿正在保存…';
  }

  function writeDraft(showFeedback = false) {
    clearTimeout(saveTimer);
    try {
      if (!changedCount()) {
        localStorage.removeItem(STORAGE_KEY);
      } else {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: 1, revision: state.revision, baseline: state.baseline, events: state.events, selectedId: state.selectedId, savedAt: new Date().toISOString() }));
      }
      state.savedAt = new Date();
      updateActions();
      if (showFeedback) notify('草稿已保存到当前浏览器。可以继续编辑，或导出文件备份。', 'success');
    } catch {
      $('draft-status').textContent = '浏览器无法保存草稿，请导出文件备份';
      if (showFeedback) notify('当前浏览器无法保存草稿。请使用“导出草稿”保存到文件。', 'warning');
    }
  }

  function markChanged() {
    state.savedAt = null;
    $('public-confirm').checked = false;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => writeDraft(), 350);
    renderList();
    updateActions();
    if (!$('preview-panel').hidden) renderPreview();
  }

  function renderList() {
    const reports = sortedEditable();
    const query = $('event-search').value.trim().toLocaleLowerCase();
    $('event-count').textContent = String(reports.length);
    const list = $('event-list');
    list.replaceChildren();
    reports.filter(event => `${event.speakerName} ${event.speakerAffiliation} ${event.title}`.toLocaleLowerCase().includes(query)).forEach(event => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `event-card${event.id === state.selectedId ? ' selected' : ''}`;
      button.disabled = state.busy;
      button.setAttribute('aria-pressed', String(event.id === state.selectedId));
      const date = document.createElement('span');
      date.className = 'event-date';
      date.textContent = event.date ? `${event.date} · ${weekday(event.date)}` : '请选择日期';
      if (changed(event)) {
        const badge = document.createElement('span');
        badge.className = 'modified-mark';
        badge.textContent = baselineById(event.id) ? '已修改' : '新报告';
        date.append(badge);
      }
      const speaker = document.createElement('span');
      speaker.className = 'speaker';
      speaker.textContent = event.speakerName || '新的报告人';
      const topic = document.createElement('span');
      topic.className = 'topic';
      topic.textContent = event.title || 'TBA';
      button.append(date, speaker, topic);
      button.addEventListener('click', () => selectEvent(event.id));
      list.append(button);
    });
    if (!list.children.length) {
      const note = document.createElement('p');
      note.className = 'empty-note';
      note.textContent = query ? '没有匹配的报告' : '暂无尚未开始的报告，可以添加新报告。';
      list.append(note);
    }
  }

  function weekday(date) {
    const day = new Date(`${date}T12:00:00Z`);
    return Number.isNaN(day.getTime()) ? '' : weekdays[day.getUTCDay()];
  }

  function updateWeekday() {
    const date = $('event-date').value;
    $('weekday-hint').textContent = date ? `${weekday(date)} · 常规报告日为周四，其他日期也可以选择。` : '常规报告安排在周四，请选择日期。';
  }

  function selectEvent(id) {
    state.selectedId = id;
    const event = selected();
    const noSelection = !event;
    $('no-selection').hidden = !noSelection;
    $('edit-panel').hidden = noSelection || $('preview-tab').getAttribute('aria-selected') === 'true';
    $('preview-panel').hidden = noSelection || $('edit-tab').getAttribute('aria-selected') === 'true';
    $('editor-footer').hidden = noSelection;
    $('form-fields').disabled = noSelection || state.busy;
    $('editor-heading').textContent = event?.speakerName || (event ? '新报告' : '报告信息');
    $('editor-eyebrow').textContent = event && !baselineById(id) ? 'NEW REPORT' : 'REPORT DETAILS';
    if (event) {
      for (const name of fields) $('event-form').elements.namedItem(name).value = plain(event[name]);
      updateWeekday();
      $('multi-day-note').hidden = !event.endDate || event.endDate === event.date;
      $('multi-day-note').textContent = `此报告包含多日，最后一天 ${event.endDate} 已保留。`;
      renderExperiences();
      renderInterests();
      renderPreview();
    }
    renderList();
    updateActions();
  }

  function newEvent() {
    if (state.busy) return;
    const event = { id: `event-${crypto.randomUUID()}`, date: '', startTime: '09:00', endTime: '09:45', place: 'Room 114', title: 'TBA', abstract: 'TBA', speakerName: '', speakerAffiliation: '', experiences: [], interests: [] };
    state.events.push(event);
    setTab('edit');
    selectEvent(event.id);
    markChanged();
    $('speaker-name').focus();
  }

  function renderExperiences() {
    const list = $('experience-list');
    list.replaceChildren();
    const rows = Array.isArray(selected()?.experiences) ? selected().experiences : [];
    if (!rows.length) {
      const note = document.createElement('p');
      note.className = 'experience-empty';
      note.textContent = '尚未添加经历。可填写学习、任职或交流经历。';
      list.append(note);
      return;
    }
    rows.forEach((experience, index) => {
      const card = document.createElement('div');
      card.className = 'experience-card';
      const top = document.createElement('div');
      top.className = 'experience-top';
      const label = document.createElement('span');
      label.textContent = `经历 ${String(index + 1).padStart(2, '0')}`;
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'remove-experience';
      remove.textContent = '删除';
      remove.setAttribute('aria-label', `删除第 ${index + 1} 条经历`);
      remove.addEventListener('click', () => { selected().experiences.splice(index, 1); renderExperiences(); markChanged(); });
      top.append(label, remove);
      card.append(top);
      [['period', '时间', '例如 2023–present'], ['position', '职位', '选择或填写职位'], ['university', '大学 / 机构', '例如 Dalian University of Technology'], ['country', '国家', '例如 China']].forEach(([key, title, placeholder], fieldIndex) => {
        if (fieldIndex % 2 === 0) {
          const row = document.createElement('div');
          row.className = 'form-grid';
          card.append(row);
        }
        const field = document.createElement('label');
        field.className = 'field';
        field.textContent = title;
        const input = document.createElement('input');
        input.value = plain(experience[key]);
        input.placeholder = placeholder;
        input.maxLength = { period: 120, position: 180, university: 260, country: 120 }[key];
        if (key === 'position') input.setAttribute('list', 'positions');
        input.addEventListener('input', () => { experience[key] = input.value; markChanged(); });
        field.append(input);
        card.lastElementChild.append(field);
      });
      list.append(card);
    });
  }

  function renderInterests() {
    const interests = Array.isArray(selected()?.interests) ? selected().interests : [];
    const list = $('interest-list');
    list.replaceChildren();
    interests.forEach((interest, index) => {
      const chip = document.createElement('span');
      chip.className = 'interest-chip';
      const text = document.createElement('span');
      text.textContent = interest;
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.textContent = '×';
      remove.setAttribute('aria-label', `删除关键词 ${interest}`);
      remove.addEventListener('click', () => { selected().interests.splice(index, 1); renderInterests(); markChanged(); });
      chip.append(text, remove);
      list.append(chip);
    });
    $('interest-sentence').textContent = interestSentence(interests) || '填写关键词后，预览会自动用英文逗号分隔，并以英文句号结束。';
  }

  function addInterest() {
    const value = $('interest-input').value.trim().replace(/[,.;，。；\s]+$/g, '');
    if (!value || !selected()) return;
    if (!Array.isArray(selected().interests)) selected().interests = [];
    if (selected().interests.length >= 100 && !selected().interests.includes(value)) { notify('研究兴趣最多添加 100 个关键词。', 'warning'); return; }
    if (!selected().interests.includes(value)) selected().interests.push(value);
    $('interest-input').value = '';
    renderInterests();
    markChanged();
    $('interest-input').focus();
  }

  function renderPreview() {
    const preview = $('report-preview');
    preview.replaceChildren();
    const event = selected();
    if (!event) return;
    const append = (tag, className, content) => {
      const element = document.createElement(tag);
      element.className = className;
      element.textContent = content;
      preview.append(element);
      return element;
    };
    append('div', 'preview-brand', 'DDES SEMINAR');
    append('h3', 'preview-title', event.title || 'TBA');
    append('p', 'preview-speaker', event.speakerName || '报告人待填写');
    append('p', 'preview-affiliation', event.speakerAffiliation || '');
    append('p', 'preview-time', `${event.date ? `${event.date} (${weekday(event.date)})` : '日期待选择'} · ${event.startTime || '09:00'}–${event.endTime || '09:45'} (UTC+8) · ${event.place || 'Room 114'}`);
    append('h4', 'preview-heading', 'Abstract');
    append('p', 'preview-abstract', event.abstract || 'TBA');
    const experiences = (event.experiences || []).filter(experience => Object.values(experience).some(value => plain(value).trim()));
    if (experiences.length) {
      append('h4', 'preview-heading', 'Biography');
      const list = append('ul', 'preview-experiences', '');
      experiences.forEach(experience => {
        const item = document.createElement('li');
        item.textContent = [experience.period, experience.position, experience.university, experience.country].filter(value => plain(value).trim()).join(' · ');
        list.append(item);
      });
    }
    if ((event.interests || []).length) {
      append('h4', 'preview-heading', 'Research interests');
      append('p', 'preview-interest', interestSentence(event.interests));
    }
  }

  function setTab(tab) {
    const preview = tab === 'preview';
    $('edit-tab').classList.toggle('active', !preview);
    $('preview-tab').classList.toggle('active', preview);
    $('edit-tab').setAttribute('aria-selected', String(!preview));
    $('preview-tab').setAttribute('aria-selected', String(preview));
    $('edit-panel').hidden = preview || !selected();
    $('preview-panel').hidden = !preview || !selected();
    if (preview) renderPreview();
  }

  function validated(event) {
    if (!event || typeof event !== 'object' || Array.isArray(event)) throw new Error('报告数据必须是一条对象记录。');
    const normalized = api().validate(clone(event));
    return { ...event, ...normalized };
  }

  function validateAll() {
    return state.events.map(event => {
      if (!changed(event)) return clone(event);
      const baseline = baselineById(event.id);
      if (baseline && !editable(baseline)) throw new Error('一场已修改的报告已经开始。请先导出草稿保存，再刷新读取最新网站；已开始的报告不能发布修改。');
      return validated(event);
    });
  }

  function exportDraft() {
    writeDraft();
    const draft = { version: 1, revision: state.revision, exportedAt: new Date().toISOString(), events: state.events };
    const url = URL.createObjectURL(new Blob([JSON.stringify(draft, null, 2)], { type: 'application/json;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `DDES-draft-${new Date(Date.now() + 8 * 3600000).toISOString().slice(0, 10)}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function tableRows(text, delimiter) {
    const rows = [];
    let row = [], value = '', quoted = false;
    for (let index = 0; index < text.length; index++) {
      const char = text[index];
      if (char === '"') {
        if (quoted && text[index + 1] === '"') { value += '"'; index++; }
        else if (!value || quoted) quoted = !quoted;
        else value += char;
      } else if (char === delimiter && !quoted) { row.push(value.trim()); value = ''; }
      else if ((char === '\n' || char === '\r') && !quoted) {
        if (char === '\r' && text[index + 1] === '\n') index++;
        row.push(value.trim());
        if (row.some(Boolean)) rows.push(row);
        row = []; value = '';
      } else value += char;
    }
    if (quoted) throw new Error('表格中有未闭合的引号，请检查文件。');
    row.push(value.trim());
    if (row.some(Boolean)) rows.push(row);
    return rows;
  }

  const cleanHeader = value => value.replace(/\*|\s|_|-/g, '').toLowerCase();
  const sameName = (a, b) => plain(a).replace(/\s|[()（）]/g, '').toLocaleLowerCase() === plain(b).replace(/\s|[()（）]/g, '').toLocaleLowerCase();
  function parseTable(text, filename) {
    const markdown = filename.endsWith('.md') || /^\s*\|/m.test(text);
    const rows = markdown
      ? text.split(/\r?\n/).filter(line => /^\s*\|/.test(line)).map(line => line.trim().replace(/^\||\|$/g, '').split(/(?<!\\)\|/).map(cell => cell.trim().replace(/\\([_@])/g, '$1').replace(/&#x20;/gi, ' '))).filter(row => !row.every(cell => /^:?-+:?$/.test(cell)))
      : tableRows(text, filename.endsWith('.tsv') || text.includes('\t') ? '\t' : ',');
    const aliases = { date: ['date', '日期', '报告日期'], speaker: ['speaker', '报告人', '报告人姓名', '姓名'], speakerAffiliation: ['affiliation', 'speakerAffiliation', '单位', '所属单位', '身份与所属单位'], startTime: ['starttime', '开始时间'], endTime: ['endtime', '结束时间'], place: ['place', 'room', '地点'], title: ['title', '标题', '报告标题'], abstract: ['abstract', '摘要'] };
    const headerIndex = rows.findIndex(row => row.some(cell => aliases.date.includes(cleanHeader(cell))) && row.some(cell => aliases.speaker.includes(cleanHeader(cell))));
    if (headerIndex < 0) throw new Error('未找到日期和报告人表头。请使用 Date / Speaker，或“日期 / 报告人”。');
    const headers = rows[headerIndex].map(cleanHeader);
    const column = name => headers.findIndex(header => aliases[name].some(alias => cleanHeader(alias) === header));
    const results = [];
    for (const row of rows.slice(headerIndex + 1)) {
      const date = plain(row[column('date')]);
      const fullName = plain(row[column('speaker')]).trim();
      if (!date && !fullName) continue;
      if (!fullName) continue; // Empty time-plan slots do not create reports.
      if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) throw new Error(`无法识别报告日期“${date}”，请使用 YYYY-MM-DD。`);
      const match = fullName.match(/^(.+?)\s*[（(](.+)[）)]\s*$/);
      const speakerName = match ? match[1].trim() : fullName;
      const existing = state.events.find(event => event.date === date && sameName(event.speakerName, speakerName));
      const event = existing ? clone(existing) : { id: `event-${crypto.randomUUID()}`, date, speakerName, speakerAffiliation: '', startTime: '09:00', endTime: '09:45', place: 'Room 114', title: 'TBA', abstract: 'TBA', experiences: [], interests: [] };
      event.speakerName = speakerName;
      if (match) event.speakerAffiliation = match[2].trim();
      for (const name of ['speakerAffiliation', 'startTime', 'endTime', 'place', 'title', 'abstract']) {
        const index = column(name);
        if (index >= 0 && plain(row[index]).trim()) event[name] = row[index].trim();
      }
      results.push(event);
    }
    if (!results.length) throw new Error('文件中没有填写报告人的日程记录。');
    return results;
  }

  async function importFile(file) {
    if (!file) return;
    try {
      if (file.size > 2 * 1024 * 1024) throw new Error('文件过大，请使用不超过 2 MB 的日程文件。');
      const text = (await file.text()).replace(/^\uFEFF/, '');
      let imported;
      if (file.name.toLowerCase().endsWith('.json')) {
        const data = JSON.parse(text);
        imported = Array.isArray(data) ? data : data.events;
        if (!Array.isArray(imported)) throw new Error('JSON 需要包含 events 数组，或直接使用报告数组。');
        if (!imported.length) throw new Error('JSON 中没有报告记录。');
      } else imported = parseTable(text, file.name.toLowerCase());
      if (imported.length > 500) throw new Error('一次最多导入 500 条记录。');
      const candidates = [];
      let ended = 0;
      const seen = new Set();
      for (const raw of imported) {
        if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('导入记录必须是一条报告对象。');
        const existing = state.events.find(current => current.id === raw.id || (raw.sourceKey && current.sourceKey === raw.sourceKey) || (current.date === raw.date && sameName(current.speakerName, raw.speakerName)));
        const record = { ...(existing || {}), ...raw, id: existing?.id || (typeof raw.id === 'string' && raw.id ? raw.id : `event-${crypto.randomUUID()}`) };
        record.startTime ||= '09:00';
        if (window.DDESManagerCore.validDate(record.date) && window.DDESManagerCore.timeValue(record.startTime) !== null && !editable(record)) { ended++; continue; }
        const event = validated(record);
        if (existing && !editable(existing)) { ended++; continue; }
        const merged = existing ? { ...existing, ...event, id: existing.id, sourceKey: existing.sourceKey } : event;
        if (seen.has(merged.id)) throw new Error('文件中存在重复的报告记录，请去重后导入。');
        seen.add(merged.id);
        if (!existing || fingerprint(merged) !== fingerprint(existing)) candidates.push(merged);
      }
      if (!candidates.length) { notify(ended ? `没有可导入的变更，已跳过 ${ended} 场结束的报告。` : '已与当前日程核对，文件没有新的变更。'); return; }
      const additions = candidates.filter(event => !eventById(event.id)).length;
      const edits = candidates.length - additions;
      const accepted = await confirmAction('导入日程草稿', `将添加 ${additions} 场新报告，更新 ${edits} 场已有报告。${ended ? `\n已跳过 ${ended} 场结束的报告。` : ''}\n导入只修改草稿，核对后再发布到网站。`, '导入草稿');
      if (!accepted) return;
      candidates.forEach(event => {
        const index = state.events.findIndex(current => current.id === event.id);
        if (index < 0) state.events.push(event);
        else state.events[index] = event;
      });
      selectEvent(candidates[0].id);
      markChanged();
      writeDraft();
      notify(`已导入 ${candidates.length} 场报告的草稿，请检查报告人、日期和时间。`, 'success');
    } catch (error) { notify(`导入未完成：${error.message}`, 'error'); }
    finally { $('import-file').value = ''; }
  }

  function restoreDraft() {
    try {
      const text = localStorage.getItem(STORAGE_KEY);
      if (!text) return;
      const draft = JSON.parse(text);
      if (draft.version !== 1 || !Array.isArray(draft.events) || !Array.isArray(draft.baseline)) throw new Error('草稿格式无法识别');
      const validDraftEvent = event => event && typeof event === 'object' && !Array.isArray(event)
        && typeof event.id === 'string' && fields.every(key => event[key] == null || typeof event[key] === 'string')
        && (event.endDate == null || typeof event.endDate === 'string')
        && Array.isArray(event.experiences || []) && (event.experiences || []).every(row => row && typeof row === 'object' && !Array.isArray(row) && ['period', 'position', 'university', 'country'].every(key => row[key] == null || typeof row[key] === 'string'))
        && Array.isArray(event.interests || []) && (event.interests || []).every(value => typeof value === 'string');
      if (draft.events.length > 500 || !draft.events.every(validDraftEvent) || !draft.baseline.every(validDraftEvent)) throw new Error('草稿数据无法识别');
      if (draft.revision === state.revision && fingerprint(draft.baseline) === fingerprint(state.baseline)) {
        // Verify complete saved records; an unfinished new form can still be restored.
        state.events = draft.events;
        state.selectedId = draft.selectedId;
        state.savedAt = new Date(draft.savedAt);
        notify('已恢复这个浏览器中尚未发布的草稿。', 'success');
      } else {
        let restored = 0, conflicts = 0;
        for (const saved of draft.events) {
          if (!saved || typeof saved !== 'object' || typeof saved.id !== 'string') continue;
          const old = draft.baseline.find(event => event.id === saved.id);
          if (old && fingerprint(old) === fingerprint(saved)) continue;
          const current = eventById(saved.id);
          if (!current && !old) { state.events.push(saved); restored++; }
          else if (current && old && fingerprint(current) === fingerprint(old) && editable(current)) {
            state.events[state.events.indexOf(current)] = saved; restored++;
          } else conflicts++;
        }
        notify(`网站已有更新。已恢复 ${restored} 场未冲突的草稿。${conflicts ? `${conflicts} 场存在差异，已保留网站最新内容；请按需重新填写。` : ''}`, conflicts ? 'warning' : 'success');
        state.savedAt = new Date();
      }
    } catch { notify('浏览器中的旧草稿无法读取，已保留网站最新内容。', 'warning'); }
  }

  async function load(options = {}) {
    try {
      if (!api()) throw new Error('页面组件未成功加载，请刷新后重试。');
      const data = await api().load();
      if (!Array.isArray(data.events)) throw new Error('无法读取日程内容。');
      state.events = clone(data.events);
      state.baseline = clone(data.events);
      state.revision = data.revision || '';
      state.local = Boolean(data.status?.local);
      state.ready = true;
      if (options.restore !== false) restoreDraft();
      const reports = sortedEditable();
      if (!reports.some(event => event.id === state.selectedId)) state.selectedId = reports[0]?.id || null;
      $('connection-text').textContent = state.local ? '本地助手已连接' : '网站草稿编辑模式';
      $('connection-indicator').className = `status-dot ${state.local ? 'connected' : 'preview'}`;
      const warnings = Array.isArray(data.warnings) ? data.warnings : [];
      if (state.local && data.status?.xelatex === false) warnings.push('本地暂未找到 PDF 排版工具，生成 PDF 时将提示安装方式。');
      if (state.local && data.status?.github === false) warnings.push('尚未连接 GitHub，发布前请按本地助手提示完成登录。');
      $('load-warning').hidden = !warnings.length;
      $('load-warning').textContent = warnings.join(' ');
      selectEvent(state.selectedId);
      setBusy(false);
    } catch (error) {
      $('connection-text').textContent = '日程读取失败';
      $('connection-indicator').className = 'status-dot preview';
      notify(error.message, 'error');
      state.ready = false;
      setBusy(false);
    }
  }

  async function generatePDF() {
    if (!selected() || state.busy || !state.local) return;
    try {
      const event = validated(selected());
      setBusy(true);
      operation('正在按报告模板生成 PDF…');
      const result = await api().generatePDF(event, status => operation(plain(status) || status?.message || '正在生成 PDF…'));
      operation('PDF 已生成。文件保留在本地；发布前可以先检查。', result);
      if (result.url) {
        const link = $('operation-status').querySelector('a');
        if (link && result.filename) link.click();
      }
    } catch (error) { operation(`PDF 未生成：${error.message}`); }
    finally { setBusy(false); }
  }

  async function publish() {
    if (state.busy || !state.local || !$('public-confirm').checked || !changedCount()) return;
    try {
      const events = validateAll();
      setBusy(true);
      operation('正在核对最新网站并发布日程，请稍候…');
      const result = await api().publish(events);
      if (result.merged || result.status === 'unchanged') {
        state.events = clone(events);
        state.baseline = clone(events);
        clearTimeout(saveTimer);
        localStorage.removeItem(STORAGE_KEY);
        $('public-confirm').checked = false;
        operation(result.status === 'unchanged' ? '已与网站核对，内容没有新的变更。' : '已发布。网站更新需要短暂时间完成。', result);
        await load({ restore: false });
      } else operation('已提交更新，等待合并后会显示在网站。草稿已保留。', result);
    } catch (error) { operation(`发布未完成：${error.message} 草稿已保留。`); }
    finally { setBusy(false); }
  }

  async function archiveEvents() {
    if (state.busy || !state.local || !state.ready) return;
    const hadDraft = changedCount() > 0;
    if (hadDraft) writeDraft();
    const showStatus = (message, result) => operation(message, result, 'archive-status');
    try {
      setBusy(true);
      showStatus('正在检查最新网站上已结束的报告…');
      const preview = await api().previewArchive();
      if (!Array.isArray(preview.candidates) || typeof preview.revision !== 'string' || !preview.revision) throw new Error('检测结果不完整，请重试。');
      const warnings = Array.isArray(preview.warnings) ? preview.warnings.filter(value => typeof value === 'string') : [];
      if (!preview.candidates.length) {
        showStatus(`没有需要归档的报告。${warnings.length ? ` ${warnings.join(' ')}` : ''}`);
        return;
      }
      const reports = preview.candidates.map(event => `${plain(event.date)}${event.endDate && event.endDate !== event.date ? ` 至 ${plain(event.endDate)}` : ''} · ${plain(event.speaker) || '报告人待确认'}`);
      const copy = `已检测到 ${reports.length} 场结束的报告：\n${reports.join('\n')}\n\n确认后将通过 GitHub 更新网站，保留报告全部内容，按日期从早到晚追加到对应学期 Past Events。${hadDraft ? '\n当前未发布的编辑草稿会保留。' : ''}${warnings.length ? `\n\n请核对：${warnings.join('\n')}` : ''}`;
      if (!(await confirmAction('归档已结束的报告', copy, '确认归档'))) { showStatus('已取消归档，网站内容未修改。'); return; }
      showStatus('正在归档并发布到网站，请稍候…');
      const result = await api().archive(preview.revision);
      const count = Number.isInteger(result.count) ? result.count : reports.length;
      if (result.merged || result.status === 'unchanged') {
        showStatus(result.status === 'unchanged' ? '已与最新网站核对，没有需要归档的报告。' : `已将 ${count} 场报告移至 Past Events，网站正在更新。`, result);
        if (hadDraft) {
          notify('归档检查已完成，未发布的草稿已保留。网站已有新版本时，请先导出草稿备份，再刷新核对后发布。', 'warning');
        } else await load({ restore: false });
      } else showStatus('归档更新已提交，等待合并后会显示在网站。编辑草稿已保留。', result);
    } catch (error) { showStatus(`归档未完成：${error.message} 编辑草稿已保留。`); }
    finally { setBusy(false); }
  }

  function bindEvents() {
    $('new-event').addEventListener('click', newEvent);
    $('new-event-empty').addEventListener('click', newEvent);
    $('event-search').addEventListener('input', renderList);
    $('event-form').addEventListener('submit', event => event.preventDefault());
    fields.forEach(name => $('event-form').elements.namedItem(name).addEventListener('input', event => {
      if (!selected() || state.busy) return;
      const previous = selected()[name];
      selected()[name] = event.target.value;
      if (name === 'date') {
        if (!selected().endDate || selected().endDate === previous) selected().endDate = event.target.value;
        updateWeekday();
      }
      if (name === 'speakerName') $('editor-heading').textContent = event.target.value || '新报告';
      markChanged();
    }));
    $('add-experience').addEventListener('click', () => {
      if (!selected()) return;
      if (!Array.isArray(selected().experiences)) selected().experiences = [];
      if (selected().experiences.length >= 50) { notify('个人经历最多添加 50 条。', 'warning'); return; }
      selected().experiences.push({ period: '', position: '', university: '', country: '' });
      renderExperiences(); markChanged();
      $('experience-list').lastElementChild?.querySelector('input')?.focus();
    });
    $('add-interest').addEventListener('click', addInterest);
    $('interest-input').addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); addInterest(); } });
    $('edit-tab').addEventListener('click', () => setTab('edit'));
    $('preview-tab').addEventListener('click', () => setTab('preview'));
    $('save-draft').addEventListener('click', () => writeDraft(true));
    $('export-draft').addEventListener('click', exportDraft);
    $('import-file').addEventListener('change', event => importFile(event.target.files[0]));
    $('discard-draft').addEventListener('click', async () => {
      if (!(await confirmAction('撤销全部草稿', '将恢复到读取网站时的日程，丢弃本次尚未发布的修改与新报告。\n如需保留，请先导出草稿。', '撤销草稿'))) return;
      clearTimeout(saveTimer);
      state.events = clone(state.baseline);
      localStorage.removeItem(STORAGE_KEY);
      state.savedAt = null;
      $('public-confirm').checked = false;
      const reports = sortedEditable();
      selectEvent(reports.some(event => event.id === state.selectedId) ? state.selectedId : reports[0]?.id || null);
      notify('草稿已撤销。', 'success');
    });
    $('public-confirm').addEventListener('change', updateActions);
    $('generate-pdf').addEventListener('click', generatePDF);
    $('publish').addEventListener('click', publish);
    $('archive-events').addEventListener('click', archiveEvents);
    window.addEventListener('pagehide', () => { if (state.ready) writeDraft(); });
    document.addEventListener('visibilitychange', () => { if (document.hidden && state.ready) writeDraft(); });
  }

  $('today-label').textContent = `${timestamp().split(' ')[0]} · 北京时间`;
  $('new-event').disabled = true;
  bindEvents();
  load();
})();
