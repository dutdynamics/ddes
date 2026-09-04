(() => {
  'use strict';

  const monthNames = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  const weekdayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const monthIndex = new Map([
    ['jan', 0], ['feb', 1], ['mar', 2], ['apr', 3], ['may', 4], ['jun', 5],
    ['jul', 6], ['aug', 7], ['sep', 8], ['oct', 9], ['nov', 10], ['dec', 11]
  ]);

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

  function dateKey(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  function parseEventDates(rawValue) {
    if (!rawValue) return [];
    const normalized = rawValue
      .replace(/\u00a0/g, ' ')
      .replace(/[–—]/g, '-')
      .replace(/\s+/g, ' ')
      .trim();
    const match = normalized.match(/^([A-Za-z]+)\s+(\d{1,2})(?:\s*-\s*(\d{1,2}))?,\s*(\d{4})$/);
    if (!match) return [];

    const month = monthIndex.get(match[1].slice(0, 3).toLowerCase());
    const startDay = Number(match[2]);
    const endDay = Number(match[3] || match[2]);
    const year = Number(match[4]);
    if (month === undefined || startDay < 1 || endDay < startDay) return [];

    const dates = [];
    for (let day = startDay; day <= endDay; day += 1) {
      const date = new Date(year, month, day, 12);
      if (date.getFullYear() === year && date.getMonth() === month && date.getDate() === day) dates.push(date);
    }
    return dates;
  }

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
    const text = item?.querySelector('dd')?.textContent.toLowerCase() || '';
    const parts = text.replace(/[–—]/g, '-').split('-');
    const value = useEnd ? (parts[1] || '') : parts[0];
    const match = value.trim().match(/^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$/);
    let hour = useEnd ? 23 : 0;
    let minute = useEnd ? 59 : 0;
    if (match) {
      hour = Number(match[1]);
      minute = Number(match[2] || 0);
      const meridiem = match[3] || text.match(/(am|pm)\s*$/)?.[1];
      if (meridiem) hour = hour % 12 + (meridiem === 'pm' ? 12 : 0);
      if (hour > 23 || minute > 59) { hour = useEnd ? 23 : 0; minute = useEnd ? 59 : 0; }
    }
    return Date.parse(`${dateKey(date)}T${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}:00+08:00`);
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
        <div class="calendar-legend"><span class="key-past"><i></i>Ended</span><span class="key-soon"><i></i>Within 7 days</span><span class="key-future"><i></i>Future</span><span><i></i>No event</span></div>
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
        button.textContent = `${{ past: 'Ended', soon: 'Within 7 days', future: 'Future' }[state]} · ${event.title}`;
        button.addEventListener('click', () => focusEvent(event));
        links.append(button);
      });
      agenda.append(links);
    }

    function render() {
      const focusedDate = document.activeElement?.dataset.calendarDate;
      now = new Date();
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
        const cell = document.createElement('div');
        const inMonth = date.getMonth() === anchor.getMonth();
        const isToday = key === new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(now);
        const states = [...new Set(dayEvents.map(event => eventStatus(event, date, now.getTime())))];
        const dominant = states.includes('soon') ? 'soon' : states.includes('future') ? 'future' : 'past';
        cell.className = `calendar-day${inMonth ? '' : ' outside-month'}${isToday ? ' today' : ''}${dayEvents.length ? ` has-events event-${dominant}` : ''}${key === selectedKey ? ' is-selected' : ''}`;
        cell.setAttribute('role', 'gridcell');

        if (dayEvents.length) {
          const button = document.createElement('button');
          button.type = 'button';
          button.dataset.calendarDate = key;
          button.setAttribute('aria-label', `${monthNames[date.getMonth()]} ${date.getDate()}, ${date.getFullYear()}: ${dayEvents.length} ${dayEvents.length === 1 ? 'event' : 'events'}`);
          const number = document.createElement('span');
          number.className = 'calendar-day-number';
          number.textContent = date.getDate();
          const status = document.createElement('span');
          status.className = 'calendar-day-status';
          status.textContent = dayEvents.length === 1 ? '1 event' : `${dayEvents.length} events`;
          const stateLabel = document.createElement('span');
          stateLabel.className = 'calendar-state-label';
          stateLabel.textContent = states.map(state => ({past: 'Ended', soon: 'Soon', future: 'Future'}[state])).join(' / ');
          button.setAttribute('aria-label', `${button.getAttribute('aria-label')}; ${stateLabel.textContent}`);
          button.append(number, status, stateLabel);
          button.addEventListener('click', () => {
            grid.querySelectorAll('.calendar-day.is-selected').forEach(item => item.classList.remove('is-selected'));
            cell.classList.add('is-selected');
            selectedKey = key;
            renderAgenda(dayEvents, date);
            focusEvent(dayEvents[0]);
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
    upcomingStartMonth = dateKey(upcomingDates[0] || new Date()).slice(0, 7);
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

  document.addEventListener('DOMContentLoaded', () => {
    initHeader();
    initReveal();

    document.querySelectorAll('.primary-nav [data-target], .footer-links [data-target]').forEach(control => {
      control.addEventListener('click', () => setPage(control.dataset.target, true));
    });

    document.querySelector('[data-back-to-top]')?.addEventListener('click', () => {
      window.scrollTo({ top: 0, behavior: reduceMotion.matches ? 'auto' : 'smooth' });
    });

    const events = initCalendars();
    const deepLinkId = decodeURIComponent(window.location.hash.slice(1));
    const linkedEvent = events.find(event => event.card.id === deepLinkId);
    if (linkedEvent) {
      window.setTimeout(() => focusEvent(linkedEvent, false), 120);
    } else if (deepLinkId === 'past' || deepLinkId === 'home') {
      setPage(deepLinkId, false);
    }
  });
})();
