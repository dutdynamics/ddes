/* Shared, dependency-free validation for the seminar editor. */
(() => {
  'use strict';
  const dates = typeof module !== 'undefined' && module.exports ? require('./script.js') : window.DDESDateUtils;
  const limits = { title: 800, abstract: 20000, speakerName: 180, speakerAffiliation: 350, place: 180 };
  const experienceLimits = { period: 120, position: 180, university: 260, country: 120 };
  function text(value, label, limit = 500) {
    if (value == null) return '';
    if (typeof value !== 'string') throw new Error(`${label}必须是文字。`);
    const result = value.trim();
    if (result.length > limit || /[\u0000-\u0008\u000b\u000c\u000e-\u001f]|[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/.test(result)) throw new Error(`${label}过长或含有无效字符。`);
    if (/<\/?[A-Za-z][\w:-]*(?:\s[^<>]*|\s*\/?)>/.test(result)) throw new Error(`${label}请填写文字或数学公式，不要填写 HTML 标签。`);
    return result;
  }
  function validDate(value) {
    return /^\d{4}-\d{2}-\d{2}$/.test(value || '') && Number(value.slice(0, 4)) >= 1000 && dates.parseEventDates(value).length === 1;
  }
  function timeValue(value) {
    if (!/^\d{2}:\d{2}$/.test(value || '')) return null;
    const [hour, minute] = value.split(':').map(Number);
    return hour < 24 && minute < 60 ? hour * 60 + minute : null;
  }
  function isEditable(event, now = Date.now()) {
    return validDate(event.date) && timeValue(event.startTime) !== null && Date.parse(`${event.date}T${event.startTime}:00+08:00`) > now;
  }
  function cleanInterests(values) {
    if (!Array.isArray(values) || values.length > 100) throw new Error('研究兴趣需要按关键词逐条填写，最多 100 条。');
    return values.map(value => text(value, '研究兴趣', 300).replace(/[\s,.;，。；]+$/, '')).filter(Boolean);
  }
  function interestSentence(values) {
    const items = cleanInterests(values || []);
    return items.length ? `${items.join(', ')}.` : '';
  }
  function validate(input, now = Date.now()) {
    if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('报告数据格式不正确。');
    const event = { ...input };
    event.id = text(input.id, '报告编号', 160);
    if (!/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,159}$/.test(event.id)) throw new Error('报告编号无效。');
    if (input.sourceKey != null && input.sourceKey !== '' && !/^[a-f0-9]{64}$/.test(input.sourceKey)) throw new Error('原报告校验值无效，请重新读取网站。');
    event.date = text(input.date, '日期', 10);
    if (!validDate(event.date)) throw new Error('请选择有效的报告日期。');
    event.endDate = text(input.endDate || event.date, '结束日期', 10);
    if (!validDate(event.endDate) || event.endDate < event.date) throw new Error('结束日期必须不早于开始日期。');
    if (event.endDate.slice(0, 7) !== event.date.slice(0, 7)) throw new Error('跨月多日报告需要人工核对，请拆分日程。');
    event.startTime = text(input.startTime || '09:00', '开始时间', 5);
    event.endTime = text(input.endTime || '09:45', '结束时间', 5);
    const start = timeValue(event.startTime), end = timeValue(event.endTime);
    if (start === null || end === null || end <= start) throw new Error('请填写有效时段，每天的结束时间须晚于开始时间。');
    for (const [key, max] of Object.entries(limits)) event[key] = text(input[key], key, max);
    if (!event.speakerName) throw new Error('请填写报告人姓名。');
    event.title ||= 'TBA'; event.abstract ||= 'TBA'; event.place ||= 'Room 114';
    if (event.place === '114') event.place = 'Room 114';
    if (!isEditable(event, now)) throw new Error('只可编辑尚未开始的报告，请检查北京时间。');
    if (!Array.isArray(input.experiences || []) || (input.experiences || []).length > 50) throw new Error('个人经历最多 50 条。');
    event.experiences = (input.experiences || []).map(row => {
      if (!row || typeof row !== 'object' || Array.isArray(row)) throw new Error('经历格式不正确。');
      return Object.fromEntries(Object.entries(experienceLimits).map(([key, max]) => [key, text(row[key], '个人经历', max)]));
    }).filter(row => Object.values(row).some(Boolean));
    event.interests = cleanInterests(input.interests || []);
    return event;
  }
  function slug(value) {
    return value.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 54) || 'seminar';
  }
  function metadata(card, name) {
    const item = [...card.querySelectorAll('.meta-item')].find(node => node.querySelector('dt')?.textContent.trim().replace(/:$/, '').toLowerCase() === name);
    return item?.querySelector('dd')?.textContent.replace(/\s+/g, ' ').trim() || '';
  }
  async function sha256(value) {
    const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
    return [...new Uint8Array(hash)].map(byte => byte.toString(16).padStart(2, '0')).join('');
  }
  async function parseWebsite(html, profiles = {}, now = Date.now()) {
    const document = new DOMParser().parseFromString(html, 'text/html');
    const cards = [...document.querySelectorAll('article')];
    const raw = [...html.matchAll(/<article\b[^>]*>[\s\S]*?<\/article\s*>/gi)];
    if (raw.length !== cards.length) throw new Error('网站结构无法安全识别，请用本地助手读取最新版本。');
    const ids = new Set([...document.querySelectorAll('[id]')].map(node => node.id));
    const events = [], warnings = [];
    for (let index = 0; index < cards.length; index++) {
      const card = cards[index];
      if (!card.matches('article.seminar') || card.matches('.notice-seminar') || card.querySelector('.badge-cancel')) continue;
      const parsed = dates.parseEventDates(card.dataset.date || metadata(card, 'date'));
      if (!parsed.length) { if (card.parentElement?.id === 'home') warnings.push('一条日期无法识别的报告保留原位。'); continue; }
      const title = card.querySelector('.seminar-title')?.textContent.replace(/\s+/g, ' ').trim() || 'TBA';
      let id = card.id;
      if (!id) {
        const base = `event-${dates.dateKey(parsed[0])}-${slug(title)}`;
        id = base; let suffix = 2;
        while (ids.has(id)) id = `${base}-${suffix++}`;
      }
      ids.add(id);
      if (card.parentElement?.id !== 'home' || !card.classList.contains('upcoming-seminar')) continue;
      const day = dates.dateKey(parsed[0]);
      const times = dates.reportTimes(metadata(card, 'time'), day);
      if (!times) { warnings.push(`${metadata(card, 'speaker')}：时间无法确认，保留原位。`); continue; }
      const clock = minutes => `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
      const speaker = metadata(card, 'speaker');
      const match = speaker.match(/^(.*?)\s*\((.*)\)\s*$/s);
      const abstract = card.querySelector('.description')?.cloneNode(true);
      abstract?.querySelectorAll('br').forEach(node => node.replaceWith('\n'));
      const profile = profiles[card.dataset.managerId || id] || {};
      const event = {
        id: card.dataset.managerId || id, sourceKey: await sha256(raw[index][0]),
        date: day, endDate: dates.dateKey(parsed.at(-1)), startTime: clock(times[0]), endTime: clock(times[1]),
        place: metadata(card, 'place'), title, abstract: (abstract?.textContent || 'TBA').replace(/[ \t]+/g, ' ').replace(/\s*\n\s*/g, '\n\n').trim(),
        speakerName: match ? match[1].trim() : speaker, speakerAffiliation: match ? match[2].trim() : '',
        experiences: profile.experiences || [], interests: profile.interests || []
      };
      if (isEditable(event, now)) events.push(event);
    }
    return { events, warnings };
  }
  const api = { validate, isEditable, cleanInterests, interestSentence, parseWebsite, validDate, timeValue };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else window.DDESManagerCore = api;
})();
