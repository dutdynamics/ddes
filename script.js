(() => {
  'use strict';

  const monthNames = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  const weekdayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const monthIndex = new Map([
    ['jan', 0], ['feb', 1], ['mar', 2], ['apr', 3], ['may', 4], ['jun', 5],
    ['jul', 6], ['aug', 7], ['sep', 8], ['oct', 9], ['nov', 10], ['dec', 11]
  ]);

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  function closeMenu() {
    const toggle = document.querySelector('.menu-toggle');
    const nav = document.querySelector('.primary-nav');
    if (!toggle || !nav) return;
    toggle.setAttribute('aria-expanded', 'false');
    nav.classList.remove('open');
    document.body.classList.remove('menu-open');
  }

  function setPage(pageId, shouldScroll = false) {
    const destination = document.getElementById(pageId);
    if (!destination || !destination.classList.contains('page-content')) return;

    document.querySelectorAll('.page-content').forEach(page => {
      page.hidden = page.id !== pageId;
    });
    document.body.classList.toggle('viewing-past', pageId === 'past');

    document.querySelectorAll('.primary-nav .nav-link[data-target]').forEach(button => {
      const active = button.dataset.target === pageId;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });

    closeMenu();
    if (shouldScroll) {
      window.requestAnimationFrame(() => {
        const scrollTarget = pageId === 'home' ? document.querySelector('#home .view-switcher') : destination;
        (scrollTarget || destination).scrollIntoView({ behavior: reduceMotion.matches ? 'auto' : 'smooth', block: 'start' });
      });
    }
  }

  function setSubPage(subPageId) {
    const destination = document.getElementById(subPageId);
    if (!destination || !destination.classList.contains('sub-page-content')) return;

    document.querySelectorAll('.sub-page-content').forEach(page => {
      page.hidden = page.id !== subPageId;
    });
    document.querySelectorAll('.sub-nav-bar button[data-target]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.target === subPageId));
    });
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
    if (parentPage) setPage(parentPage.id, false);

    const semester = card.closest('.sub-page-content');
    if (semester) setSubPage(semester.id);

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

  function createCalendar(mount, events, mode) {
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

    const now = new Date();
    let anchor = new Date(now.getFullYear(), now.getMonth(), 1, 12);
    if (allDates.length) {
      const ordered = [...allDates].sort((a, b) => a - b);
      const preferred = mode === 'past' ? ordered[ordered.length - 1] : ordered[0];
      anchor = new Date(preferred.getFullYear(), preferred.getMonth(), 1, 12);
    }

    mount.innerHTML = `
      <div class="calendar-panel">
        <div class="calendar-toolbar">
          <div class="calendar-title-wrap">
            <span class="calendar-kicker">${mode === 'past' ? 'Event archive' : 'Seminar calendar'}</span>
            <h3 class="calendar-title" aria-live="polite"></h3>
          </div>
          <div class="calendar-controls">
            <button class="calendar-control" type="button" data-calendar-action="previous" aria-label="Previous month">←</button>
            <button class="calendar-control" type="button" data-calendar-action="next" aria-label="Next month">→</button>
          </div>
        </div>
        <div class="calendar-weekdays" aria-hidden="true">${weekdayNames.map(day => `<span>${day}</span>`).join('')}</div>
        <div class="calendar-grid" role="grid"></div>
        <div class="calendar-legend"><span class="event-key"><i></i>Event date</span><span><i></i>No event</span></div>
        <div class="calendar-agenda" aria-live="polite"></div>
      </div>`;

    const panel = mount.querySelector('.calendar-panel');
    const title = mount.querySelector('.calendar-title');
    const grid = mount.querySelector('.calendar-grid');
    const agenda = mount.querySelector('.calendar-agenda');

    function renderAgenda(dayEvents = [], date = null) {
      agenda.replaceChildren();
      const label = document.createElement('span');
      label.className = 'calendar-agenda-label';
      label.textContent = date ? new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric' }).format(date) : 'Selected date';
      agenda.append(label);

      if (!dayEvents.length) {
        const empty = document.createElement('p');
        empty.className = 'calendar-agenda-empty';
        empty.textContent = `Gray dates have no ${mode === 'past' ? 'archived' : 'upcoming'} event. Use the arrows to browse other months.`;
        agenda.append(empty);
        return;
      }

      const links = document.createElement('div');
      links.className = 'calendar-agenda-events';
      dayEvents.forEach(event => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'calendar-agenda-link';
        button.textContent = event.title;
        button.addEventListener('click', () => focusEvent(event));
        links.append(button);
      });
      agenda.append(links);
    }

    function render() {
      title.textContent = `${monthNames[anchor.getMonth()]} ${anchor.getFullYear()}`;
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
        const isToday = key === dateKey(now);
        cell.className = `calendar-day${inMonth ? '' : ' outside-month'}${isToday ? ' today' : ''}${dayEvents.length ? ' has-events' : ''}`;
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
          button.append(number, status);
          button.addEventListener('click', () => {
            grid.querySelectorAll('.calendar-day.is-selected').forEach(item => item.classList.remove('is-selected'));
            cell.classList.add('is-selected');
            renderAgenda(dayEvents, date);
            if (dayEvents.length === 1) focusEvent(dayEvents[0]);
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

      renderAgenda();
    }

    panel.querySelector('[data-calendar-action="previous"]').addEventListener('click', () => {
      anchor = new Date(anchor.getFullYear(), anchor.getMonth() - 1, 1, 12);
      render();
    });
    panel.querySelector('[data-calendar-action="next"]').addEventListener('click', () => {
      anchor = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 1, 12);
      render();
    });

    render();
  }

  function initCalendars() {
    const usedIds = new Set([...document.querySelectorAll('[id]')].map(node => node.id));
    const upcomingEvents = collectEvents(document.getElementById('home'), usedIds);
    const pastEvents = collectEvents(document.getElementById('past'), usedIds);

    document.querySelectorAll('[data-calendar]').forEach(mount => {
      const mode = mount.dataset.calendar;
      createCalendar(mount, mode === 'past' ? pastEvents : upcomingEvents, mode);
    });

    return [...upcomingEvents, ...pastEvents];
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

    document.querySelectorAll('.primary-nav [data-target], .past-return[data-target], .footer-links [data-target]').forEach(control => {
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
