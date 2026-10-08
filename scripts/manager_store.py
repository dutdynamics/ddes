"""Read and publish seminar edits without modifying the local checkout.

Updated 2026-10-06 (UTC+8). GitHub authentication is delegated to the installed
``gh`` command. All writes go to a new branch and a pull request; credentials
are never passed by the browser or included in this module's results.
"""

import base64
from copy import deepcopy
from datetime import date, datetime, time
from hashlib import sha256
from html import escape
from html.parser import HTMLParser
import json
import re
import subprocess
import unicodedata
from uuid import uuid4

try:
    from .archive_events import DALIAN, Document, archive as archive_html, dates, end_of_report, report_times
except ImportError:
    from archive_events import DALIAN, Document, archive as archive_html, dates, end_of_report, report_times


REPOSITORY = 'dutdynamics/ddes'
ID_PATTERN = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,159}\Z')
SHA_PATTERN = re.compile(r'[0-9a-f]{40}\Z')
KEY_PATTERN = re.compile(r'[0-9a-f]{64}\Z')
HTML_TAG = re.compile(r'</?[A-Za-z][\w:-]*(?:\s[^<>]*|\s*/?)>')
FIELDS = ('date', 'endDate', 'startTime', 'endTime', 'place', 'title', 'abstract',
          'speakerName', 'speakerAffiliation', 'experiences', 'interests')
VISIBLE_FIELDS = ('date', 'endDate', 'startTime', 'endTime', 'place', 'title',
                  'abstract', 'speakerName', 'speakerAffiliation')


class ConflictError(ValueError):
    """The submitted revision or original event no longer matches GitHub."""


class GitHubError(RuntimeError):
    """A GitHub operation failed; the message does not contain credentials."""


def _instant(now=None):
    instant = now or datetime.now(DALIAN)
    if isinstance(instant, str):
        instant = datetime.fromisoformat(instant)
    if not isinstance(instant, datetime) or instant.tzinfo is None:
        raise ValueError('The current time must include a UTC offset.')
    return instant.astimezone(DALIAN)


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        # Source-code line wrapping is whitespace; only actual HTML paragraphs
        # and <br> elements create editable abstract line breaks.
        self.parts.append(re.sub(r'\s+', ' ', data))

    def handle_starttag(self, tag, attrs):
        if tag.lower() in ('br', 'p', 'li'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag.lower() in ('p', 'li'):
            self.parts.append('\n')


class _Identifiers(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.values = set()
        self.feed(source)
        self.close()

    def handle_starttag(self, tag, attrs):
        identity = dict(attrs).get('id')
        if identity:
            self.values.add(identity)


def _plain(raw, multiline=False):
    parser = _Text()
    parser.feed(raw)
    text = ''.join(parser.parts)
    if multiline:
        return '\n'.join(' '.join(line.split()) for line in text.splitlines()
                         if line.strip()).strip()
    return ' '.join(text.split())


def _inside(source, node):
    closing = re.search(r'</' + re.escape(node.tag) + r'\s*>\s*\Z', source[node.start:node.end], re.I)
    if not closing:
        raise ValueError('Unrecognized closing tag; no changes written.')
    return node.opening_end, node.start + closing.start()


def _nodes(doc, card, class_name):
    return [node for node in doc.elements
            if card.start < node.start < card.end and node.has_class(class_name)]


def _value_nodes(doc, card):
    values = {}
    for node in _nodes(doc, card, 'meta-item'):
        terms = [child for child in node.children if child.tag == 'dt']
        descriptions = [child for child in node.children if child.tag == 'dd']
        if terms and descriptions:
            name = doc.text(terms[0]).rstrip(':').strip().lower()
            if name in values:
                raise ValueError(f'Duplicate {name} field; no changes written.')
            values[name] = descriptions[0]
    return values


def _slug(text):
    text = unicodedata.normalize('NFKD', text)
    text = re.sub(r'[\u0300-\u036f]', '', text).lower()
    return re.sub(r'[^a-z0-9]+', '-', text).strip('-')[:54] or 'seminar'


def _cards(doc):
    # Follow the calendar's document order for fallback IDs, including archives.
    # The calendar reserves *all* explicit DOM IDs before generating fallbacks.
    used = _Identifiers(doc.source).values
    seen_reports = set()
    records = []
    for card in doc.elements:
        if card.tag != 'article' or not card.has_class('seminar'):
            continue
        raw = doc.source[card.start:card.end]
        if (card.has_class('notice-seminar') or
                card.attrs.get('data-calendar-ignore') == 'true' or 'badge-cancel' in raw):
            continue
        fields = doc.metadata(card)
        raw_date = card.attrs.get('data-date') or fields.get('date', '')
        try:
            first, last = dates(raw_date)
        except ValueError:
            records.append((card, None, fields, None, None, raw))
            continue
        titles = _nodes(doc, card, 'seminar-title')
        title = doc.text(titles[0]) if titles else 'Seminar by ' + (fields.get('speaker') or 'guest speaker')
        identity = card.attrs.get('id') or card.attrs.get('data-manager-id')
        if not identity:
            stem = f'event-{first.isoformat()}-{_slug(title)}'
            identity, suffix = stem, 2
            while identity in used:
                identity = f'{stem}-{suffix}'
                suffix += 1
        if identity in seen_reports:
            raise ValueError('Duplicate report ID; no changes written.')
        used.add(identity)
        seen_reports.add(identity)
        records.append((card, identity, fields, first, last, raw))
    return records


def parse_events(html, profiles=None, now=None, *, include_started=False):
    """Return editable future reports and warnings; never infer unknown times.

    ``profiles`` is an object keyed by stable report ID. Archived, started,
    malformed and ambiguous reports remain in the original HTML untouched.
    """
    instant = _instant(now)
    if profiles is None:
        profiles = {}
    if not isinstance(profiles, dict):
        raise ValueError('Seminar profiles must be an object.')
    doc = Document(html)
    home = doc.by_id('home')
    events, warnings = [], []
    for card, identity, fields, first, last, raw in _cards(doc):
        if card.parent is not home or not card.has_class('upcoming-seminar'):
            continue
        speaker = fields.get('speaker', 'Unknown speaker')
        if first is None:
            warnings.append(f'{speaker}: the report date could not be recognized; kept unchanged.')
            continue
        first_times = report_times(first, fields.get('time', ''))
        last_times = report_times(last, fields.get('time', ''))
        if first_times is None or last_times is None:
            warnings.append(f'{speaker}: the report time could not be recognized; kept unchanged.')
            continue
        if not include_started and datetime.combine(first, time.min, DALIAN).timestamp() + first_times[0] * 60 <= instant.timestamp():
            continue
        # Multiple sessions cannot be faithfully represented by two time inputs.
        interval_pattern = r'\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s*[-\u2013\u2014]\s*\d{1,2}'
        if len(re.findall(interval_pattern, fields.get('time', ''), flags=re.I)) != 1:
            warnings.append(f'{speaker}: multiple sessions require manual review; kept unchanged.')
            continue
        titles = _nodes(doc, card, 'seminar-title')
        descriptions = _nodes(doc, card, 'description')
        values = _value_nodes(doc, card)
        if len(titles) != 1 or len(descriptions) != 1 or any(name not in values for name in ('speaker', 'date', 'time', 'place')):
            warnings.append(f'{speaker}: missing or ambiguous report fields; kept unchanged.')
            continue
        split = re.fullmatch(r'\s*(.*?)\s*\((.*)\)\s*', speaker)
        name, affiliation = (split[1].strip(), split[2].strip()) if split else (speaker.strip(), '')
        profile = profiles.get(identity, {})
        if not isinstance(profile, dict):
            warnings.append(f'{speaker}: invalid biography data; biography left empty.')
            profile = {}
        event = {
            'id': identity,
            'sourceKey': sha256(raw.encode('utf-8')).hexdigest(),
            'date': first.isoformat(), 'endDate': last.isoformat() if last != first else '',
            'startTime': f'{first_times[0] // 60:02}:{first_times[0] % 60:02}',
            'endTime': f'{last_times[1] // 60:02}:{last_times[1] % 60:02}',
            'place': fields.get('place', ''),
            'title': doc.text(titles[0]),
            'abstract': _plain(html[slice(*_inside(html, descriptions[0]))], multiline=True),
            'speakerName': name, 'speakerAffiliation': affiliation,
            'experiences': deepcopy(profile.get('experiences', [])),
            'interests': deepcopy(profile.get('interests', [])),
        }
        try:
            events.append(validate_event(event, instant, allow_started=include_started))
        except ValueError as error:
            warnings.append(f'{speaker}: {error}; kept unchanged.')
    return {'events': events, 'warnings': warnings}


def _field(value, label, limit, multiline=False, required=False):
    if not isinstance(value, str):
        raise ValueError(f'{label} must be text.')
    if len(value) > limit:
        raise ValueError(f'{label} is too long (maximum {limit} characters).')
    if any(ord(char) < 32 and char not in ('\t', '\n', '\r') for char in value):
        raise ValueError(f'{label} contains an invalid control character.')
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ValueError(f'{label} contains invalid Unicode.')
    if HTML_TAG.search(value):
        raise ValueError(f'{label} must be plain text, not HTML.')
    value = value.replace('\r\n', '\n').replace('\r', '\n').strip()
    if not multiline:
        value = ' '.join(value.split())
    if required and not value:
        raise ValueError(f'{label} is required.')
    return value


def validate_event(data, now=None, *, allow_started=False):
    """Normalize and validate a UI event, including its start in UTC+8."""
    if not isinstance(data, dict):
        raise ValueError('Each report must be an object.')
    event = {}
    event['id'] = _field(data.get('id', ''), 'Report ID', 160, required=True)
    if not ID_PATTERN.fullmatch(event['id']):
        raise ValueError('Invalid report ID.')
    event['sourceKey'] = _field(data.get('sourceKey', ''), 'Source key', 64)
    if event['sourceKey'] and not KEY_PATTERN.fullmatch(event['sourceKey']):
        raise ValueError('Invalid source key.')
    for key in ('date', 'endDate'):
        value = _field(data.get(key, ''), key, 10, required=key == 'date')
        if value:
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
                raise ValueError('Dates must use YYYY-MM-DD.')
            try:
                parsed = date.fromisoformat(value)
            except ValueError:
                raise ValueError('Invalid report date.') from None
            if parsed.year < 1000:
                raise ValueError('Invalid report year.')
        event[key] = value
    first = date.fromisoformat(event['date'])
    last = date.fromisoformat(event['endDate'] or event['date'])
    if last < first:
        raise ValueError('The last date cannot precede the first date.')
    if (first.year, first.month) != (last.year, last.month):
        raise ValueError('Multi-day reports must remain within one calendar month.')
    if last == first:
        event['endDate'] = ''
    for key, default in (('startTime', '09:00'), ('endTime', '09:45')):
        value = _field(data.get(key, default), key, 5, required=True)
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value):
            raise ValueError('Times must use the 24-hour HH:MM format.')
        event[key] = value
    start = datetime.combine(first, time.fromisoformat(event['startTime']), DALIAN)
    end = datetime.combine(last, time.fromisoformat(event['endTime']), DALIAN)
    if end <= start:
        raise ValueError('The end must follow the start.')
    if event['endTime'] <= event['startTime']:
        raise ValueError('Each daily session must end after its start; overnight sessions require manual review.')
    if not allow_started and start <= _instant(now):
        raise ValueError('Only reports that have not started can be edited or added.')
    specs = (
        ('place', 'Room 114', 180, False, True),
        ('title', 'TBA', 800, False, True),
        ('abstract', 'TBA', 20000, True, True),
        ('speakerName', '', 180, False, True),
        ('speakerAffiliation', '', 350, False, False),
    )
    for key, default, limit, multiline, required in specs:
        event[key] = _field(data.get(key, default), key, limit, multiline, required)
    experiences = data.get('experiences', [])
    if not isinstance(experiences, list) or len(experiences) > 50:
        raise ValueError('Experiences must be a list with at most 50 entries.')
    event['experiences'] = []
    for row in experiences:
        if not isinstance(row, dict):
            raise ValueError('Each experience must be an object.')
        normalized = {key: _field(row.get(key, ''), key, maximum)
                      for key, maximum in (('period', 120), ('position', 180),
                                           ('university', 260), ('country', 120))}
        if any(normalized.values()):
            event['experiences'].append(normalized)
    interests = data.get('interests', [])
    if not isinstance(interests, list) or len(interests) > 100:
        raise ValueError('Research interests must be a list with at most 100 entries.')
    event['interests'] = []
    for value in interests:
        # Remove only delimiters at the boundary; commas inside a keyword remain.
        value = _field(value, 'Research interest', 300).strip().rstrip(' ,.;，。；').strip()
        if value:
            event['interests'].append(value)
    return event


def _formatted_date(event):
    first = date.fromisoformat(event['date'])
    end = date.fromisoformat(event['endDate'] or event['date'])
    month = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')[first.month - 1]
    days = str(first.day) if first == end else f'{first.day}-{end.day}'
    return f'{month} {days}, {first.year}'


def _event_start(event):
    return datetime.combine(date.fromisoformat(event['date']),
                            time.fromisoformat(event['startTime']), DALIAN)


def _formatted_time(event):
    def display(raw):
        hour, minute = map(int, raw.split(':'))
        return f'{hour % 12 or 12}:{minute:02}' + ('am' if hour < 12 else 'pm')
    return display(event['startTime']) + ' - ' + display(event['endTime'])


def _speaker(event):
    return event['speakerName'] + (f" ({event['speakerAffiliation']})" if event['speakerAffiliation'] else '')


def _set_attribute(opening, name, value):
    pattern = re.compile(r'(\s)' + re.escape(name) + r'''\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)''', re.I)
    attribute = f' {name}="{escape(value, quote=True)}"'
    if pattern.search(opening):
        return pattern.sub(lambda match: attribute, opening, count=1)
    return opening[:-1] + attribute + '>'


def _new_card(event, newline):
    lines = [f'<article class="seminar upcoming-seminar" id="{event["id"]}" data-manager-id="{event["id"]}">',
             f'    <h2 class="seminar-title">{escape(event["title"])}</h2>', '    <dl class="meta-info">']
    for name, value in (('Speaker', _speaker(event)), ('Date', _formatted_date(event)),
                        ('Time', _formatted_time(event)), ('Place', event['place'])):
        lines.append(f'        <div class="meta-item"><dt>{name}:</dt><dd>{escape(value)}</dd></div>')
    abstract = '<br>'.join(escape(line) for line in event['abstract'].split('\n'))
    lines.extend(['    </dl>', f'    <section class="description"><p>{abstract}</p></section>', '</article>'])
    return newline.join(lines)


def _reject_pdf_uploads(pdf_paths):
    # Keep the old argument so an older client fails explicitly instead of
    # uploading a locally generated poster through a forgotten integration.
    if pdf_paths is not None and (not isinstance(pdf_paths, dict) or pdf_paths):
        raise ValueError('PDF is for offline use only; uploading a PDF is not supported.')


def _replace_card(doc, card, old, event):
    source = doc.source
    edits = []
    opening = source[card.start:card.opening_end]
    opening = _set_attribute(opening, 'id', event['id'])
    opening = _set_attribute(opening, 'data-manager-id', event['id'])
    if 'data-date' in card.attrs and any(old.get(key) != event.get(key) for key in ('date', 'endDate')):
        opening = _set_attribute(opening, 'data-date', _formatted_date(event))
    edits.append((card.start, card.opening_end, opening))
    metadata = _value_nodes(doc, card)
    groups = {
        'speaker': (('speakerName', 'speakerAffiliation'), _speaker(event)),
        'date': (('date', 'endDate'), _formatted_date(event)),
        'time': (('startTime', 'endTime'), _formatted_time(event)),
        'place': (('place',), event['place']),
    }
    for label, (keys, value) in groups.items():
        if any(old.get(key) != event.get(key) for key in keys):
            if label not in metadata:
                raise ValueError(f'Missing {label} field; no changes written.')
            start, end = _inside(source, metadata[label])
            edits.append((start, end, escape(value)))
    if old['title'] != event['title']:
        title = _nodes(doc, card, 'seminar-title')[0]
        start, end = _inside(source, title)
        edits.append((start, end, escape(event['title'])))
    if old['abstract'] != event['abstract']:
        description = _nodes(doc, card, 'description')[0]
        start, end = _inside(source, description)
        edits.append((start, end, '<p>' + '<br>'.join(escape(line) for line in event['abstract'].split('\n')) + '</p>'))
    raw = source[card.start:card.end]
    for start, end, replacement in sorted(edits, reverse=True):
        raw = raw[:start - card.start] + replacement + raw[end - card.start:]
    return raw


def apply_events(html, original_events, updated_events, pdf_paths=None):
    """Patch only editable cards; deletion and edits to archived cards are refused.

    Events must already have been validated for the intended time. Existing
    unedited articles, including every Past article, retain their exact bytes.
    Posters are generated and downloaded separately for offline use.
    """
    _reject_pdf_uploads(pdf_paths)
    if not isinstance(original_events, list) or not isinstance(updated_events, list):
        raise ValueError('Reports must be supplied as lists.')
    original = {event['id']: event for event in original_events}
    updated = {event['id']: event for event in updated_events}
    if len(original) != len(original_events) or len(updated) != len(updated_events):
        raise ValueError('Duplicate report ID.')
    if not original.keys() <= updated.keys():
        raise ValueError('Existing reports cannot be deleted.')
    doc = Document(html)
    home = doc.by_id('home')
    records = _cards(doc)
    known = {identity: (card, raw) for card, identity, _, _, _, raw in records if identity}
    edits = []
    for identity, old in original.items():
        if identity not in known:
            raise ConflictError('An original report is no longer present; refresh the schedule.')
        card, raw = known[identity]
        if card.parent is not home or not card.has_class('upcoming-seminar'):
            raise ValueError('Archived reports cannot be changed.')
        if old.get('sourceKey') != sha256(raw.encode('utf-8')).hexdigest():
            raise ConflictError('An original report changed; refresh the schedule.')
        event = updated[identity]
        if event.get('sourceKey') != old.get('sourceKey'):
            raise ConflictError('The source key changed; refresh the schedule.')
        if any(old.get(key) != event.get(key) for key in FIELDS):
            edits.append((card.start, card.end, _replace_card(doc, card, old, event)))
    new = [event for identity, event in updated.items() if identity not in original]
    reserved = _Identifiers(html).values
    for event in new:
        if event['id'] in known or event.get('sourceKey'):
            raise ValueError('A new report cannot replace an existing report.')
        if event['id'] in reserved:
            raise ValueError('The new report ID is already used elsewhere on the page.')
        if not ID_PATTERN.fullmatch(event['id']):
            raise ValueError('Invalid report ID.')
    # Report IDs alone cannot prevent accidental copies from repeated imports.
    seen = set()
    for event in updated_events:
        key = (event['date'], event['startTime'], unicodedata.normalize('NFKC', event['speakerName']).casefold())
        if key in seen:
            raise ValueError('Duplicate speaker, date and start time.')
        seen.add(key)
    if new:
        newline = '\r\n' if '\r\n' in html else '\n'
        last_cards = [child for child in home.children if child.tag == 'article']
        append_at = last_cards[-1].end if last_cards else home.opening_end
        dated_cards = []
        for card, identity, fields, first, _, _ in records:
            if card.parent is not home or first is None or not card.has_class('upcoming-seminar'):
                continue
            if identity in updated:
                day, start_time = updated[identity]['date'], updated[identity]['startTime']
            else:
                times = report_times(first, fields.get('time', ''))
                day = first.isoformat()
                start_time = f'{times[0] // 60:02}:{times[0] % 60:02}' if times else '23:59'
            dated_cards.append((card, (day, start_time)))
        additions = {}
        for event in sorted(new, key=lambda item: (item['date'], item['startTime'], item['id'])):
            key = (event['date'], event['startTime'])
            insertion = next((card.start for card, existing_key in dated_cards if existing_key > key), append_at)
            raw = _new_card(event, newline)
            additions.setdefault(insertion, []).append(newline + '                ' + raw)
        for insertion, blocks in additions.items():
            edits.append((insertion, insertion, ''.join(blocks)))
    result = html
    for start, end, replacement in sorted(edits, reverse=True):
        result = result[:start] + replacement + result[end:]
    checked = Document(result)
    if sum(node.tag == 'article' for node in checked.elements) != sum(node.tag == 'article' for node in doc.elements) + len(new):
        raise ValueError('Unexpected article count; no changes written.')
    for card in doc.elements:
        if card.tag == 'article' and card.has_class('past-seminar'):
            if html[card.start:card.end] not in result:
                raise ValueError('An archived report changed; no changes written.')
    return result


class Store:
    """Remote-only storage through gh, leaving the local worktree untouched."""
    def __init__(self, repository=REPOSITORY, now=None, gh='gh'):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
            raise ValueError('Invalid repository name.')
        self.repository, self.now, self.gh = repository, now, gh

    def _api(self, endpoint, method='GET', payload=None, missing_ok=False):
        command = [self.gh, 'api', '--method', method, '-H', 'Accept: application/vnd.github+json', endpoint]
        raw = None
        if payload is not None:
            command.extend(['--input', '-'])
            raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        try:
            response = subprocess.run(command, input=raw, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, timeout=120, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise GitHubError('GitHub could not be reached. Check the local GitHub login and connection.') from None
        if response.returncode:
            if missing_ok and re.search(rb'(?:HTTP |status[: ]+)404\b', response.stderr, re.I):
                return None
            # Do not return raw gh diagnostics, which could expose a credential
            # helper's output. The operation and status are sufficient for UI.
            status = re.search(rb'HTTP (\d{3})', response.stderr)
            suffix = f' (HTTP {status[1].decode()})' if status else ''
            raise GitHubError(f'GitHub {method} operation failed{suffix}.')
        if not response.stdout.strip():
            return None
        try:
            return json.loads(response.stdout.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            raise GitHubError('GitHub returned an invalid response.') from None

    def _endpoint(self, suffix):
        return f'repos/{self.repository}/{suffix}'

    def _head(self):
        value = self._api(self._endpoint('git/ref/heads/main'))
        revision = value.get('object', {}).get('sha', '')
        if not SHA_PATTERN.fullmatch(revision):
            raise GitHubError('GitHub returned an invalid main revision.')
        return revision

    def _file(self, path, revision, optional=False):
        result = self._api(self._endpoint(f'contents/{path}?ref={revision}'), missing_ok=optional)
        if result is None and optional:
            return None
        if not isinstance(result, dict) or result.get('encoding') != 'base64' or result.get('size', 0) > 5_000_000:
            raise GitHubError('The remote schedule file could not be read safely.')
        try:
            return base64.b64decode(result['content'], validate=False).decode('utf-8')
        except (KeyError, ValueError, UnicodeDecodeError):
            raise GitHubError('The remote schedule file is invalid.') from None

    def _read(self):
        revision = self._head()
        html = self._file('index.html', revision)
        raw_profiles = self._file('seminar-profiles.json', revision, optional=True)
        try:
            profiles = json.loads(raw_profiles) if raw_profiles is not None else {}
        except ValueError:
            raise ValueError('The remote biography file is invalid; no changes written.') from None
        if not isinstance(profiles, dict):
            raise ValueError('The remote biography file must be an object.')
        return revision, html, profiles

    def snapshot(self):
        revision, html, profiles = self._read()
        result = parse_events(html, profiles, self.now)
        result['revision'] = revision
        return result

    def _archive_plan(self, revision, html, instant):
        """Read raw Upcoming cards, including reports no longer editable."""
        edited_html, moved, warnings = archive_html(html, instant)
        doc = Document(html)
        home = doc.by_id('home')
        candidates, future_ends = [], []
        for card, identity, fields, first, last, _ in _cards(doc):
            if card.parent is not home or not card.has_class('upcoming-seminar') or first is None:
                continue
            end = end_of_report(last, fields.get('time', ''))
            if end > instant:
                future_ends.append(end)
                continue
            titles = _nodes(doc, card, 'seminar-title')
            candidates.append({
                'id': identity, 'speaker': fields.get('speaker', 'Unknown speaker'),
                'title': doc.text(titles[0]) if titles else 'Seminar',
                'date': first.isoformat(), 'endDate': last.isoformat() if last != first else '',
                'endAt': end.isoformat(),
            })
        if len(candidates) != len(moved):
            raise ValueError('Archive candidates differ from the reports to move; no changes written.')
        candidates.sort(key=lambda event: (event['date'], event['endAt'], event['id']))
        return edited_html, {
            'revision': revision, 'checkedAt': instant.isoformat(),
            'count': len(moved), 'candidates': candidates, 'moved': moved,
            'warnings': warnings,
            'nextEndAt': min(future_ends).isoformat() if future_ends else None,
        }

    def archive_preview(self):
        """Preview ended reports from the latest remote main without writing."""
        revision, html, _ = self._read()
        _, preview = self._archive_plan(revision, html, _instant(self.now))
        return preview

    def archive(self, revision):
        """Move fully ended cards through the same protected PR publication route.

        The move preserves the original HTML of every card and never rewrites
        biographies. A revision conflict is refused before any remote write.
        """
        if not isinstance(revision, str) or not SHA_PATTERN.fullmatch(revision):
            raise ValueError('Invalid source revision.')
        latest, html, _ = self._read()
        if latest != revision:
            raise ConflictError('The website changed since the archive preview. Check again before archiving; your draft has been kept.')
        instant = _instant(self.now)
        edited_html, preview = self._archive_plan(revision, html, instant)
        if edited_html == html:
            return dict(preview, status='unchanged', archived=0)
        result = self._publish_contents({'index.html': edited_html.encode('utf-8')},
                                        revision, instant, preview['warnings'], operation='archive')
        # Publication returns the new revision; preserve its value rather than
        # overwriting it with the preview's source revision.
        details = {key: value for key, value in preview.items() if key != 'revision'}
        return dict(details, **result, archived=preview['count'] if result['status'] == 'merged' else 0)

    def publish(self, events, revision, pdf_paths=None):
        _reject_pdf_uploads(pdf_paths)
        if not isinstance(revision, str) or not SHA_PATTERN.fullmatch(revision):
            raise ValueError('Invalid source revision.')
        latest, html, profiles = self._read()
        if latest != revision:
            raise ConflictError('The website changed since you opened it. Refresh before publishing; your draft has been kept.')
        if not isinstance(events, list) or len(events) > 200:
            raise ValueError('Reports must be a list with at most 200 entries.')
        instant = _instant(self.now)
        # A page can stay open while one report begins. Normalize all submitted
        # rows first, then permit started rows only when they exactly match the
        # latest original. They may also be omitted and remain untouched.
        updated = [validate_event(event, instant, allow_started=True) for event in events]
        parsed = parse_events(html, profiles, instant)
        all_original = parse_events(html, profiles, instant, include_started=True)['events']
        original_by_id = {event['id']: event for event in all_original}
        included_started = []
        for event in updated:
            before = original_by_id.get(event['id'])
            if before is not None and _event_start(before) <= instant:
                if event['sourceKey'] != before['sourceKey'] or any(event.get(key) != before.get(key) for key in FIELDS):
                    raise ValueError('A report started while this page was open and cannot be changed. Refresh the schedule.')
                included_started.append(before)
            elif _event_start(event) <= instant:
                raise ValueError('Only reports that have not started can be edited or added.')
        original = parsed['events'] + included_started
        edited_html = apply_events(html, original, updated)
        updated_profiles = deepcopy(profiles)
        for event in updated:
            if _event_start(event) <= instant:
                continue
            previous = updated_profiles.get(event['id'], {})
            if not isinstance(previous, dict):
                previous = {}
            profile = deepcopy(previous)
            profile.update({'experiences': event['experiences'], 'interests': event['interests']})
            # Avoid an implicit write for an unchanged report with no profile.
            if profile['experiences'] or profile['interests'] or event['id'] in updated_profiles:
                updated_profiles[event['id']] = profile
        contents = {}
        if edited_html != html:
            contents['index.html'] = edited_html.encode('utf-8')
        if updated_profiles != profiles:
            contents['seminar-profiles.json'] = (json.dumps(updated_profiles, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        if not contents:
            return {'status': 'unchanged', 'revision': revision, 'warnings': parsed['warnings']}
        return self._publish_contents(contents, revision, instant, parsed['warnings'])

    def _publish_contents(self, contents, revision, instant, warnings, *, operation='update'):
        """Publish an atomic tree through an ordinary branch and protected PR."""
        if operation == 'archive':
            pending = self._pending_archive(warnings)
            if pending is not None:
                return pending
            message = f'Archive ended seminars ({instant.date().isoformat()}, UTC+8)'
            title = f'Archive ended seminars — {instant.date().isoformat()}'
            body = ('Move fully ended seminar cards from Upcoming Events to their Past Events semester. '
                    'Append this batch in date order after existing reports. '
                    'Report content, biographies and offline PDFs are preserved.')
            branch_prefix = 'seminar-archive'
        else:
            message = f'Update seminar schedule ({instant.date().isoformat()}, UTC+8)'
            title = f'Update seminar schedule — {instant.date().isoformat()}'
            body = ('Update upcoming seminar details and speaker biographies from the local seminar manager. '
                    'Existing archived reports and unedited seminar content are preserved. '
                    'Report PDFs are generated and downloaded locally for offline use only.')
            branch_prefix = 'seminar-manager'
        commit = self._api(self._endpoint(f'git/commits/{revision}'))
        tree_base = commit.get('tree', {}).get('sha', '')
        if not SHA_PATTERN.fullmatch(tree_base):
            raise GitHubError('GitHub returned an invalid source tree.')
        entries = []
        for path, content in sorted(contents.items()):
            blob = self._api(self._endpoint('git/blobs'), 'POST', {
                'content': base64.b64encode(content).decode('ascii'), 'encoding': 'base64'})
            entries.append({'path': path, 'mode': '100644', 'type': 'blob', 'sha': blob['sha']})
        tree = self._api(self._endpoint('git/trees'), 'POST', {'base_tree': tree_base, 'tree': entries})
        created = self._api(self._endpoint('git/commits'), 'POST', {
            'message': message,
            'tree': tree['sha'], 'parents': [revision]})
        head = created['sha']
        if not SHA_PATTERN.fullmatch(head):
            raise GitHubError('GitHub returned an invalid new commit.')
        if self._head() != revision:
            raise ConflictError('The website changed while preparing your update. Refresh before publishing; no branch was published.')
        if operation == 'archive':
            # A scheduler and the local editor can inspect the same source.
            # Recheck immediately before publishing an archive branch.
            pending = self._pending_archive(warnings)
            if pending is not None:
                return pending
        branch = f'codex/{branch_prefix}-{instant.strftime("%Y%m%d")}-{uuid4().hex[:12]}'
        self._api(self._endpoint('git/refs'), 'POST', {'ref': f'refs/heads/{branch}', 'sha': head})
        pull = self._api(self._endpoint('pulls'), 'POST', {
            'title': title,
            'head': branch, 'base': 'main',
            'body': body})
        result = {'status': 'pending_review', 'prUrl': pull['html_url'],
                  'branch': branch, 'revision': head, 'warnings': warnings}
        if self._head() != revision:
            result['message'] = 'The main branch changed. The update is available as a pull request for review.'
            return result
        current_pull = self._api(self._endpoint(f'pulls/{pull["number"]}'))
        if current_pull.get('head', {}).get('sha') != head:
            raise ConflictError('The pull request changed before merge; review it on GitHub.')
        if self._head() != revision:
            result['message'] = 'The main branch changed before merging. Review the saved pull request on GitHub.'
            return result
        if current_pull.get('mergeable') is False or current_pull.get('mergeable_state') in ('blocked', 'dirty', 'behind', 'draft', 'unstable'):
            result['message'] = 'GitHub requires review or checks before this update can be merged.'
            return result
        try:
            merged = self._api(self._endpoint(f'pulls/{pull["number"]}/merge'), 'PUT', {
                'sha': head, 'merge_method': 'squash',
                'commit_title': message})
        except GitHubError:
            # A protected branch can reject automatic merging. Leave the PR for
            # its normal approval route rather than bypassing any protection.
            result['message'] = 'The pull request was saved, but its merge could not be confirmed. Open it on GitHub to check its status.'
            return result
        if not merged or not merged.get('merged'):
            result['message'] = 'The pull request was saved and is awaiting merge on GitHub.'
            return result
        result.update({'status': 'merged', 'revision': merged['sha'],
                       'websiteUrl': 'https://dutdynamics.github.io/ddes/'})
        return result

    def _pending_archive(self, warnings):
        """Reuse an open archive PR, including older work awaiting protection.

        Only this repository's archive branches targeting its own main are
        considered. Do not create another archive PR while review, checks or
        merge confirmation for previous archive work is still outstanding.
        """
        page = 1
        while True:
            pulls = self._api(self._endpoint(f'pulls?state=open&base=main&per_page=100&page={page}'))
            if not isinstance(pulls, list):
                raise GitHubError('Open archive pull requests could not be checked safely.')
            for pull in pulls:
                if not isinstance(pull, dict):
                    continue
                head, base = pull.get('head') or {}, pull.get('base') or {}
                head_repo = head.get('repo') or {}
                base_repo = base.get('repo') or {}
                branch = head.get('ref', '')
                if (pull.get('state') != 'open' or base.get('ref') != 'main' or
                        not isinstance(branch, str) or not branch.startswith('codex/seminar-archive-') or
                        str(head_repo.get('full_name', '')).casefold() != self.repository.casefold() or
                        str(base_repo.get('full_name', '')).casefold() != self.repository.casefold()):
                    continue
                revision, url = head.get('sha', ''), pull.get('html_url', '')
                if (not isinstance(revision, str) or not SHA_PATTERN.fullmatch(revision) or
                        not isinstance(url, str) or
                        not url.casefold().startswith(f'https://github.com/{self.repository}/pull/'.casefold())):
                    raise GitHubError('The existing archive pull request could not be read safely.')
                return {'status': 'pending_review', 'prUrl': url, 'branch': branch,
                        'revision': revision, 'warnings': warnings,
                        'message': 'An archive pull request is already open. Review or merge it on GitHub before starting another archive update.'}
            if len(pulls) < 100:
                return None
            page += 1
