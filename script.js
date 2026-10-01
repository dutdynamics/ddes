(() => {
  'use strict';

  const monthNames = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  const weekdayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  // The seminar's regular weekly slot is Thursday. Highlight only that slot.
  const publicHolidayOn = key => new Date(`${key}T12:00:00Z`).getUTCDay() === 4
    ? (window.DDES_HOLIDAYS || []).find(holiday => holiday.start <= key && key <= holiday.end)
    : undefined;
  const monthIndex = new Map(monthNames.flatMap((name, index) => [[name.toLowerCase(), index], [name.slice(0, 3).toLowerCase(), index]]));
  monthIndex.set('sept', 8);

  // Calendar dates are civil dates; report timestamps always use UTC+8.
  function dateKey(date) {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  }

  function dalianDateKey(now = new Date()) {
    return new Date(now.getTime() + 8 * 60 * 60 * 1000).toISOString().slice(0, 10);
  }

  function parseEventDates(rawValue) {
    const value = (rawValue || '').replace(/[\u2013\u2014]/g, '-').replace(/\s+/g, ' ').trim();
    const iso = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    const match = value.match(/^([A-Za-z]+)\s+(\d{1,2})(?:\s*-\s*(\d{1,2}))?,\s*(\d{4})$/);
    if (!iso && !match) return [];
    const year = Number(iso ? iso[1] : match[4]);
    const month = iso ? Number(iso[2]) - 1 : monthIndex.get(match[1].toLowerCase());
    const first = Number(iso ? iso[3] : match[2]);
    const last = Number(iso ? iso[3] : match[3] || match[2]);
    if (year < 1000 || month === undefined || month < 0 || month > 11 || first < 1 || last < first) return [];
    const limit = new Date(year, month + 1, 0, 12).getDate();
    if (last > limit) return []; // Reject the whole range, including invalid endpoints.
    return Array.from({ length: last - first + 1 }, (_, index) => new Date(year, month, first + index, 12));
  }

  function clockMinutes(value, inheritedMeridiem = '') {
    const match = value.trim().match(/^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$/);
    if (!match) return null;
    let hour = Number(match[1]);
    const minute = Number(match[2] || 0);
    const meridiem = match[3] || inheritedMeridiem;
    if (minute > 59 || (meridiem ? hour < 1 || hour > 12 : hour > 23)) return null;
    if (meridiem) hour = hour % 12 + (meridiem === 'pm' ? 12 : 0);
    return hour * 60 + minute;
  }

  function reportTimes(rawTime, day) {
    const text = (rawTime || '').toLowerCase().replace(/[\u2013\u2014]/g, '-').replace(/\s+/g, ' ').trim();
    const clock = '(\\d{1,2}(?::\\d{2})?\\s*(?:am|pm)?)';
    const pattern = new RegExp(`(?:([a-z]+)\\s+(\\d{1,2}),?\\s+)?${clock}\\s*-\\s*${clock}`, 'g');
    const matches = [...text.matchAll(pattern)];
    if (!matches.length) return null;
    const dated = matches.some(match => match[1]);
    const selectedMonth = Number(day.slice(5, 7)) - 1;
    const selectedDay = Number(day.slice(8, 10));
    let position = 0;
    let label = null;
    const intervals = [];
    for (const match of matches) {
      const gap = text.slice(position, match.index).trim();
      if (position === 0 ? gap !== '' : !/^(?:and|[,;/])?$/.test(gap)) return null;
      position = match.index + match[0].length;
      if (match[1]) {
        const month = monthIndex.get(match[1]);
        const date = Number(match[2]);
        const year = Number(day.slice(0, 4));
        if (month === undefined || date < 1 || date > new Date(year, month + 1, 0, 12).getDate()) return null;
        label = [month, date];
      }
      if (dated && !label) return null;
      const meridiem = match[4].match(/(am|pm)$/)?.[1] || '';
      const start = clockMinutes(match[3], meridiem);
      const end = clockMinutes(match[4]);
      if (start === null || end === null || end < start) return null;
      if (!label || (label[0] === selectedMonth && label[1] === selectedDay)) intervals.push([start, end]);
    }
    if (text.slice(position).trim() || !intervals.length) return null;
    return [Math.min(...intervals.map(item => item[0])), Math.max(...intervals.map(item => item[1]))];
  }

  function reportBoundary(rawTime, day, useEnd = false) {
    const times = reportTimes(rawTime, day);
    const minutes = times ? times[useEnd ? 1 : 0] : useEnd ? 24 * 60 : 0;
    return Date.parse(`${day}T00:00:00+08:00`) + minutes * 60 * 1000;
  }

  // The same pure functions are available to Node's dependency-free regression tests.
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { dateKey, dalianDateKey, parseEventDates, reportTimes, reportBoundary };
    return;
  }

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let sharedPastCalendar = null;
  let sharedPastCalendarController = null;
  let upcomingStartMonth = '';

  function closeMenu() {
    const toggle = document.querySelector('.menu-toggle');
    const nav = document.querySelector('.primary-nav');
    if (!toggle || !nav) return;
    toggle.setAttribute('aria-expanded', 'false');
    nav.classList.remove('open');
    document.body.classList.remove('menu-open');
  }

  function setPage(pageId, shouldScroll = false, syncCalendarMonth = true) {
    const destination = document.getElementById(pageId);
    if (!destination || !destination.classList.contains('page-content')) return;

    document.querySelectorAll('.page-content').forEach(page => {
      page.hidden = page.id !== pageId;
    });
    document.querySelectorAll('.primary-nav .nav-link[data-target]').forEach(button => {
      const active = button.dataset.target === pageId;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    document.getElementById('events-heading').textContent = pageId === 'past' ? 'Past Events' : 'Upcoming Events';
    document.getElementById('semester-navigation').hidden = pageId !== 'past';
    if (syncCalendarMonth) {
      if (pageId === 'home') sharedPastCalendarController?.showMonth(upcomingStartMonth);
      else {
        const semester = document.querySelector('#past .semester-section:not([hidden])');
        if (semester) setSharedPastCalendarMonth(semester.id);
      }
    }

    closeMenu();
    if (shouldScroll) {
      window.requestAnimationFrame(() => {
        const scrollTarget = document.querySelector('.view-switcher');
        (scrollTarget || destination).scrollIntoView({ behavior: reduceMotion.matches ? 'auto' : 'smooth', block: 'start' });
      });
    }
  }

  function setSubPage(subPageId, syncCalendarMonth = true) {
    const destination = document.getElementById(subPageId);
    if (!destination || !destination.classList.contains('sub-page-content')) return;

    document.querySelectorAll('.sub-page-content').forEach(page => {
      page.hidden = page.id !== subPageId;
    });
    document.querySelectorAll('.sub-nav-bar button[data-target]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.target === subPageId));
    });
    if (syncCalendarMonth) setSharedPastCalendarMonth(subPageId);
  }

  // Keep the original inline navigation hooks working while adding the new header controls.
  window.showPage = pageId => setPage(pageId, false);
  window.showSubPage = subPageId => setSubPage(subPageId);

  function slugify(value) {
    const slug = value
      .normalize('NFKD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 54);
    return slug || 'seminar';
  }

  function eventDateText(card) {
    if (card.dataset.date) return card.dataset.date;
    const dateItem = [...card.querySelectorAll('.meta-item')].find(item => {
      const term = item.querySelector('dt');
      return term && term.textContent.trim().toLowerCase().replace(/:$/, '') === 'date';
    });
    return dateItem?.querySelector('dd')?.textContent.trim() || '';
  }

  function collectEvents(section, usedIds) {
    if (!section) return [];
    const events = [];

    section.querySelectorAll('article.seminar').forEach(card => {
      if (card.classList.contains('notice-seminar') || card.dataset.calendarIgnore === 'true' || card.querySelector('.badge-cancel')) return;

      const rawDate = eventDateText(card);
      const dates = parseEventDates(rawDate);
      if (!dates.length) return;

      const titleNode = card.querySelector('.seminar-title');
      const speakerItem = [...card.querySelectorAll('.meta-item')].find(item => item.querySelector('dt')?.textContent.trim().toLowerCase().startsWith('speaker'));
      const speaker = speakerItem?.querySelector('dd')?.textContent.replace(/\s+/g, ' ').trim() || '';
      const title = titleNode?.textContent.replace(/\s+/g, ' ').trim() || `Seminar by ${speaker || 'guest speaker'}`;

      if (!card.id) {
        const baseId = `event-${dateKey(dates[0])}-${slugify(title)}`;
        let candidate = baseId;
        let suffix = 2;
        while (usedIds.has(candidate)) {
          candidate = `${baseId}-${suffix}`;
          suffix += 1;
        }
        card.id = candidate;
      }
      usedIds.add(card.id);
      card.dataset.calendarDates = dates.map(dateKey).join(',');
      card.classList.add('calendar-event-card');
      events.push({ card, dates, rawDate, title, speaker });
    });

    return events;
  }

  function focusEvent(event, updateHash = true) {
    if (!event?.card) return;
    const card = event.card;
    const parentPage = card.closest('.page-content');
    if (parentPage) setPage(parentPage.id, false, false);

    const semester = card.closest('.sub-page-content');
    if (semester) setSubPage(semester.id, false);

    document.querySelectorAll('.seminar.event-highlight').forEach(item => item.classList.remove('event-highlight'));
    card.classList.add('event-highlight');
    window.setTimeout(() => card.classList.remove('event-highlight'), 3200);

    if (updateHash && window.history?.replaceState) {
      window.history.replaceState(null, '', `#${card.id}`);
    }
    window.requestAnimationFrame(() => {
      card.scrollIntoView({ behavior: reduceMotion.matches ? 'auto' : 'smooth', block: 'start' });
    });
  }

  // Interpret event times in Dalian's timezone, independently of the visitor's timezone.
  function eventTime(event, date, useEnd = false) {
    const item = [...event.card.querySelectorAll('.meta-item')].find(node => node.querySelector('dt')?.textContent.trim().toLowerCase().startsWith('time'));
    return reportBoundary(item?.querySelector('dd')?.textContent || '', dateKey(date), useEnd);
  }

  function eventStatus(event, date, now = Date.now()) {
    if (eventTime(event, date, true) <= now) return 'past';
    if (eventTime(event, date) <= now + 7 * 24 * 60 * 60 * 1000) return 'soon';
    return 'future';
  }

  function createCalendar(mount, events) {
    const eventMap = new Map();
    const allDates = [];
    events.forEach(event => {
      event.dates.forEach(date => {
        const key = dateKey(date);
        allDates.push(date);
        if (!eventMap.has(key)) eventMap.set(key, []);
        eventMap.get(key).push(event);
      });
    });
    eventMap.forEach((dayEvents, key) => {
      const date = new Date(`${key}T12:00:00`);
      dayEvents.sort((a, b) => eventTime(a, date) - eventTime(b, date));
    });

    let now = new Date();
    let selectedKey = null;
    const configuredStart = mount.dataset.calendarStart?.match(/^(\d{4})-(\d{2})$/);
    const initialMonth = configuredStart
      ? new Date(Number(configuredStart[1]), Number(configuredStart[2]) - 1, 1, 12)
      : null;
    const configuredMinimum = mount.dataset.calendarMin?.match(/^(\d{4})-(\d{2})$/);
    const minimumMonth = configuredMinimum
      ? new Date(Number(configuredMinimum[1]), Number(configuredMinimum[2]) - 1, 1, 12)
      : null;
    let anchor = initialMonth || new Date(now.getFullYear(), now.getMonth(), 1, 12);
    if (!initialMonth && allDates.length) {
      const ordered = [...allDates].sort((a, b) => a - b);
      const preferred = ordered[0];
      anchor = new Date(preferred.getFullYear(), preferred.getMonth(), 1, 12);
    }

    mount.innerHTML = `
      <div class="calendar-panel">
        <div class="calendar-toolbar">
          <div class="calendar-title-wrap">
            <span class="calendar-kicker">All seminars · Dalian time (UTC+8)</span>
            <h3 class="calendar-title" aria-live="polite"></h3>
          </div>
          <div class="calendar-controls">
            <button class="calendar-control" type="button" data-calendar-action="previous" aria-label="Previous month">←</button>
            <button class="calendar-control" type="button" data-calendar-action="next" aria-label="Next month">→</button>
          </div>
        </div>
        <div class="calendar-weekdays" aria-hidden="true">${weekdayNames.map(day => `<span>${day}</span>`).join('')}</div>
        <div class="calendar-grid" role="grid"></div>
        <div class="calendar-legend"><span class="key-past"><i></i>Past</span><span class="key-soon"><i></i>Upcoming</span><span class="key-future"><i></i>Scheduled</span><span class="key-holiday"><i></i>Public holiday</span><span><i></i>No event</span></div>
        <div class="calendar-agenda" aria-live="polite"></div>
      </div>`;

    const panel = mount.querySelector('.calendar-panel');
    const title = mount.querySelector('.calendar-title');
    const grid = mount.querySelector('.calendar-grid');
    const agenda = mount.querySelector('.calendar-agenda');
    const previousButton = panel.querySelector('[data-calendar-action="previous"]');

    function renderAgenda(dayEvents = [], date = null) {
      agenda.replaceChildren();
      const label = document.createElement('span');
      label.className = 'calendar-agenda-label';
      label.textContent = date ? new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric' }).format(date) : 'Selected date';
      agenda.append(label);

      const holiday = date && publicHolidayOn(dateKey(date));
      if (holiday) {
        const notice = document.createElement('p');
        notice.className = 'calendar-holiday-notice';
        notice.textContent = 'Public holiday';
        agenda.append(notice);
        if (!dayEvents.length) return;
      }

      if (!dayEvents.length) {
        const empty = document.createElement('p');
        empty.className = 'calendar-agenda-empty';
        empty.textContent = 'Select an event date to jump to its first report.';
        agenda.append(empty);
        return;
      }

      const links = document.createElement('div');
      links.className = 'calendar-agenda-events';
      dayEvents.forEach(event => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'calendar-agenda-link';
        const state = eventStatus(event, date || event.dates[0]);
        button.dataset.eventStatus = state;
        button.textContent = `${{ past: 'Past', soon: 'Upcoming', future: 'Scheduled' }[state]} · ${event.title}`;
        button.addEventListener('click', () => focusEvent(event));
        links.append(button);
      });
      agenda.append(links);
    }

    function render() {
      const focusedDate = document.activeElement?.dataset.calendarDate;
      now = new Date();
      const todayKey = dalianDateKey(now);
      title.textContent = `${monthNames[anchor.getMonth()]} ${anchor.getFullYear()}`;
      previousButton.disabled = Boolean(minimumMonth && anchor <= minimumMonth);
      grid.replaceChildren();
      const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1, 12);
      const mondayOffset = (first.getDay() + 6) % 7;
      const start = new Date(first);
      start.setDate(first.getDate() - mondayOffset);

      for (let index = 0; index < 42; index += 1) {
        const date = new Date(start);
        date.setDate(start.getDate() + index);
        const key = dateKey(date);
        const dayEvents = eventMap.get(key) || [];
        const holiday = publicHolidayOn(key);
        const cell = document.createElement('div');
        const inMonth = date.getMonth() === anchor.getMonth();
        const isToday = key === todayKey;
        const states = [...new Set(dayEvents.map(event => eventStatus(event, date, now.getTime())))];
        const dominant = states.includes('soon') ? 'soon' : states.includes('future') ? 'future' : 'past';
        cell.className = `calendar-day${inMonth ? '' : ' outside-month'}${isToday ? ' today' : ''}${dayEvents.length ? ` has-events event-${dominant}` : ''}${holiday ? ' public-holiday' : ''}${key === selectedKey ? ' is-selected' : ''}`;
        cell.setAttribute('role', 'gridcell');
        cell.dataset.date = key;

        if (dayEvents.length || holiday) {
          const button = document.createElement('button');
          button.type = 'button';
          button.dataset.calendarDate = key;
          button.setAttribute('aria-label', `${monthNames[date.getMonth()]} ${date.getDate()}, ${date.getFullYear()}: ${dayEvents.length} ${dayEvents.length === 1 ? 'event' : 'events'}`);
          const number = document.createElement('span');
          number.className = 'calendar-day-number';
          number.textContent = date.getDate();
          const status = document.createElement('span');
          status.className = 'calendar-day-status';
          status.textContent = dayEvents.length ? (dayEvents.length === 1 ? '1 event' : `${dayEvents.length} events`) : '';
          const stateLabel = document.createElement('span');
          stateLabel.className = 'calendar-state-label';
          stateLabel.textContent = holiday ? 'Public holiday' : states.map(state => ({past: 'Past', soon: 'Upcoming', future: 'Scheduled'}[state])).join(' / ');
          button.setAttribute('aria-label', `${button.getAttribute('aria-label')}; ${stateLabel.textContent}`);
          button.append(number, status, stateLabel);
          button.addEventListener('click', () => {
            grid.querySelectorAll('.calendar-day.is-selected').forEach(item => item.classList.remove('is-selected'));
            cell.classList.add('is-selected');
            selectedKey = key;
            renderAgenda(dayEvents, date);
            if (!holiday) focusEvent(dayEvents[0]);
          });
          cell.append(button);
        } else {
          const number = document.createElement('span');
          number.className = 'calendar-day-number';
          number.textContent = date.getDate();
          const status = document.createElement('span');
          status.className = 'calendar-day-status';
          status.textContent = 'No event';
          cell.append(number, status);
          cell.setAttribute('aria-label', `${monthNames[date.getMonth()]} ${date.getDate()}, ${date.getFullYear()}: no event`);
        }
        grid.append(cell);
      }

      const selectedDate = selectedKey ? new Date(`${selectedKey}T12:00:00`) : null;
      renderAgenda(eventMap.get(selectedKey) || [], selectedDate);
      if (focusedDate) grid.querySelector(`[data-calendar-date="${focusedDate}"]`)?.focus({ preventScroll: true });
    }

    previousButton.addEventListener('click', () => {
      if (minimumMonth && anchor <= minimumMonth) return;
      anchor = new Date(anchor.getFullYear(), anchor.getMonth() - 1, 1, 12);
      render();
    });
    panel.querySelector('[data-calendar-action="next"]').addEventListener('click', () => {
      anchor = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 1, 12);
      render();
    });

    render();
    window.setInterval(render, 60000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) render(); });
    return {
      showMonth(value) {
        const requestedMonth = value?.match(/^(\d{4})-(\d{2})$/);
        if (!requestedMonth) return;
        anchor = new Date(Number(requestedMonth[1]), Number(requestedMonth[2]) - 1, 1, 12);
        selectedKey = null;
        render();
      }
    };
  }

  function setSharedPastCalendarMonth(scopeId) {
    const scope = document.getElementById(scopeId);
    if (!scope || !scope.classList.contains('semester-section')) return;
    sharedPastCalendarController?.showMonth(scope.dataset.calendarStart);
    if (sharedPastCalendar) sharedPastCalendar.dataset.calendarScope = scopeId;
  }

  function initCalendars() {
    const usedIds = new Set([...document.querySelectorAll('[id]')].map(node => node.id));
    const allEvents = collectEvents(document.getElementById('main-content'), usedIds);
    const upcomingDates = allEvents.flatMap(event => event.dates.filter(date => eventStatus(event, date) !== 'past')).sort((a, b) => a - b);
    upcomingStartMonth = (upcomingDates[0] ? dateKey(upcomingDates[0]) : dalianDateKey()).slice(0, 7);
    sharedPastCalendar = document.querySelector('[data-calendar="all"]');
    if (sharedPastCalendar) {
      sharedPastCalendar.dataset.calendarStart = upcomingStartMonth;
      sharedPastCalendarController = createCalendar(sharedPastCalendar, allEvents);
    }

    return allEvents;
  }

  function initReveal() {
    const items = document.querySelectorAll('.reveal');
    items.forEach(item => {
      const delay = Number(item.dataset.delay || 0);
      item.style.setProperty('--delay', `${delay}ms`);
    });

    if (reduceMotion.matches || !('IntersectionObserver' in window)) {
      items.forEach(item => item.classList.add('visible'));
      return;
    }
    const observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('visible');
        observer.unobserve(entry.target);
      });
    }, { threshold: 0.12 });
    items.forEach(item => observer.observe(item));
  }

  function initHeader() {
    const header = document.querySelector('[data-site-header]');
    const toggle = document.querySelector('.menu-toggle');
    const nav = document.querySelector('.primary-nav');

    const updateHeader = () => header?.classList.toggle('scrolled', window.scrollY > 24);
    updateHeader();
    window.addEventListener('scroll', updateHeader, { passive: true });

    toggle?.addEventListener('click', () => {
      const open = toggle.getAttribute('aria-expanded') !== 'true';
      toggle.setAttribute('aria-expanded', String(open));
      nav?.classList.toggle('open', open);
      document.body.classList.toggle('menu-open', open);
    });

    document.addEventListener('keydown', event => {
      if (event.key === 'Escape') closeMenu();
    });
  }

  function initBackToTop() {
    const button = document.querySelector('.back-to-top');
    if (!button) return;
    let ticking = false;
    const update = () => {
      const visible = window.scrollY > 120;
      button.classList.toggle('is-visible', visible);
      button.setAttribute('aria-hidden', String(!visible));
      button.tabIndex = visible ? 0 : -1;
      ticking = false;
    };
    const schedule = () => {
      if (!ticking) {
        ticking = true;
        window.requestAnimationFrame(update);
      }
    };
    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', schedule, { passive: true });
    update();
  }

  document.addEventListener('DOMContentLoaded', () => {
    initHeader();
    initReveal();
    initBackToTop();

    document.querySelectorAll('.primary-nav [data-target], .footer-links [data-target]').forEach(control => {
      control.addEventListener('click', () => setPage(control.dataset.target, true));
    });

    document.querySelectorAll('[data-back-to-top], .back-to-top').forEach(control => {
      control.addEventListener('click', () => window.scrollTo({ top: 0, behavior: reduceMotion.matches ? 'auto' : 'smooth' }));
    });
    document.querySelectorAll('.sub-nav-bar [data-target]').forEach(control => {
      control.addEventListener('click', () => setSubPage(control.dataset.target));
    });

    const events = initCalendars();
    const firstSemester = document.querySelector('#semester-navigation [data-target]')?.dataset.target;
    if (firstSemester) setSubPage(firstSemester, false);
    setPage('home', false);
    function followHash() {
      let deepLinkId = window.location.hash.slice(1);
      try { deepLinkId = decodeURIComponent(deepLinkId); } catch { /* Keep malformed links harmless. */ }
      const linkedEvent = events.find(event => event.card.id === deepLinkId);
      if (linkedEvent) {
        sharedPastCalendarController?.showMonth(dateKey(linkedEvent.dates[0]).slice(0, 7));
        window.setTimeout(() => focusEvent(linkedEvent, false), 120);
      } else if (deepLinkId === 'past' || deepLinkId === 'home') {
        setPage(deepLinkId, false);
      }
    }
    window.addEventListener('hashchange', followHash);
    followHash();
  });
})();
