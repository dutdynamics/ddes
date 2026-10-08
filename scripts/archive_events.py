"""Move ended seminar cards to Past Events, preserving their original HTML.

Default: dry run. Use --write to update index.html. All times use UTC+8.
"""

import argparse
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
import re

DALIAN = timezone(timedelta(hours=8))
MONTH_NAMES = ('january', 'february', 'march', 'april', 'may', 'june',
               'july', 'august', 'september', 'october', 'november', 'december')
MONTHS = {key: index for index, name in enumerate(MONTH_NAMES, 1)
          for key in (name, name[:3])}
MONTHS['sept'] = 9


@dataclass
class Element:
    tag: str
    attrs: dict
    start: int
    opening_end: int
    parent: object = None
    end: int = 0
    children: list = field(default_factory=list)

    def has_class(self, name):
        return name in self.attrs.get('class', '').split()


class Document(HTMLParser):
    # Track structural elements only, avoiding HTML's optional paragraph endings.
    tracked = {'main', 'section', 'article', 'div', 'h2', 'dt', 'dd', 'button'}

    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.offsets = [0]
        self.offsets.extend(m.end() for m in re.finditer('\n', source))
        self.stack = []
        self.elements = []
        self.feed(source)
        self.close()
        if self.stack:
            raise ValueError('Unclosed structural HTML; no changes written.')

    def position(self):
        line, column = self.getpos()
        return self.offsets[line - 1] + column

    def handle_starttag(self, tag, attrs):
        if tag not in self.tracked:
            return
        parent = self.stack[-1] if self.stack else None
        start = self.position()
        node = Element(tag, dict(attrs), start, start + len(self.get_starttag_text()), parent)
        if parent:
            parent.children.append(node)
        self.elements.append(node)
        self.stack.append(node)

    def handle_endtag(self, tag):
        if tag not in self.tracked:
            return
        if not self.stack or self.stack[-1].tag != tag:
            raise ValueError(f'Unbalanced {tag} element; no changes written.')
        self.stack.pop().end = self.source.index('>', self.position()) + 1

    def by_id(self, identity):
        matches = [node for node in self.elements if node.attrs.get('id') == identity]
        if len(matches) != 1:
            raise ValueError(f'Expected exactly one #{identity}; found {len(matches)}.')
        return matches[0]

    def text(self, node):
        return ' '.join(unescape(re.sub(r'<[^>]*>', '', self.source[node.opening_end:node.end])).split())

    def metadata(self, card):
        fields = {}
        for node in self.elements:
            if card.start < node.start < card.end and node.has_class('meta-item'):
                terms = [child for child in node.children if child.tag == 'dt']
                values = [child for child in node.children if child.tag == 'dd']
                if terms and values:
                    fields[self.text(terms[0]).rstrip(':').lower()] = self.text(values[0])
        return fields


def dates(raw):
    value = ' '.join(raw.replace('\u2013', '-').replace('\u2014', '-').split())
    iso = re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})', value)
    match = re.fullmatch(r'([A-Za-z]+)\s+(\d{1,2})(?:\s*-\s*(\d{1,2}))?,\s*(\d{4})', value)
    if iso:
        year, month, start, end = int(iso[1]), int(iso[2]), int(iso[3]), int(iso[3])
    elif match and match[1].lower() in MONTHS:
        month, year = MONTHS[match[1].lower()], int(match[4])
        start, end = int(match[2]), int(match[3] or match[2])
    else:
        raise ValueError(f'Unrecognized date: {raw!r}')
    if year < 1000:
        raise ValueError(f'Invalid date: {raw!r}')
    first, last = date(year, month, start), date(year, month, end)
    if last < first:
        raise ValueError(f'Reversed date range: {raw!r}')
    return first, last


def clock_minutes(value, inherited_meridiem=''):
    match = re.fullmatch(r'\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*', value)
    if not match:
        return None
    hour, minute = int(match[1]), int(match[2] or 0)
    meridiem = match[3] or inherited_meridiem
    if minute > 59 or not (1 <= hour <= 12 if meridiem else 0 <= hour <= 23):
        return None
    if meridiem:
        hour = hour % 12 + (12 if meridiem == 'pm' else 0)
    return hour * 60 + minute


def report_times(day, raw_time):
    text = ' '.join(raw_time.lower().replace('\u2013', '-').replace('\u2014', '-').split())
    clock = r'(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)'
    pattern = re.compile(r'(?:([a-z]+)\s+(\d{1,2}),?\s+)?' + clock + r'\s*-\s*' + clock)
    matches = list(pattern.finditer(text))
    if not matches:
        return None
    dated = any(match[1] for match in matches)
    position, label, intervals = 0, None, []
    for match in matches:
        gap = text[position:match.start()].strip()
        if (gap != '' if position == 0 else not re.fullmatch(r'(?:and|[,;/])?', gap)):
            return None
        position = match.end()
        if match[1]:
            month = MONTHS.get(match[1])
            if month is None:
                return None
            try:
                date(day.year, month, int(match[2]))
            except ValueError:
                return None
            label = month, int(match[2])
        if dated and label is None:
            return None
        meridiem = re.search(r'(am|pm)$', match[4])
        start = clock_minutes(match[3], meridiem[1] if meridiem else '')
        end = clock_minutes(match[4])
        if start is None or end is None or end < start:
            return None
        if label is None or label == (day.month, day.day):
            intervals.append((start, end))
    if text[position:].strip() or not intervals:
        return None
    return min(item[0] for item in intervals), max(item[1] for item in intervals)


def end_of_report(last, raw_time):
    times = report_times(last, raw_time)
    if times is not None:
        return datetime.combine(last, time.min, DALIAN) + timedelta(minutes=times[1])
    # Unknown/invalid time: wait until the entire final date has passed.
    return datetime.combine(last + timedelta(days=1), time.min, DALIAN)


def semester(day):
    # Fall includes January; spring covers February through August.
    year = day.year - (day.month == 1)
    if day.month >= 9 or day.month == 1:
        return f'past-fall{year}', f'Fall Semester {year}-{year + 1}', f'{year}-09'
    return f'past-spring{day.year}', f'Spring Semester {day.year}', f'{day.year}-02'


def archive(source, now):
    if now.tzinfo is None:
        raise ValueError('The check time must include a UTC offset.')
    doc = Document(source)
    home, past = doc.by_id('home'), doc.by_id('past')
    groups, edits, moved, skipped = defaultdict(list), [], [], []
    for card in home.children:
        if (card.tag != 'article' or not card.has_class('seminar') or card.has_class('notice-seminar')
                or card.attrs.get('data-calendar-ignore') == 'true'
                or 'badge-cancel' in source[card.start:card.end]):
            continue
        fields = doc.metadata(card)
        raw_date = card.attrs.get('data-date') or fields.get('date', '')
        try:
            first, last = dates(raw_date)
        except ValueError as error:
            skipped.append(f"{fields.get('speaker', 'Unknown speaker')}: {error}")
            continue
        if end_of_report(last, fields.get('time', '')) > now:
            continue
        html = source[card.start:card.end]
        # Change the class token only in the article's opening tag.
        opening = source[card.start:card.opening_end]
        def replace_class(match):
            if match[1].lower() != 'class':
                return match[0]
            value = match[3]
            quote = value[0] if value[0] in "\"'" else ''
            tokens = value[1:-1] if quote else value
            tokens = re.sub(r'(?<!\S)upcoming-seminar(?!\S)', 'past-seminar', tokens)
            return match[1] + match[2] + quote + tokens + quote
        opening = re.sub(r"([^\s=/>]+)(\s*=\s*)(\"[^\"]*\"|'[^']*'|[^\s>]+)", replace_class, opening)
        if not card.has_class('upcoming-seminar'):
            raise ValueError('An ended card lacks upcoming-seminar; no changes written.')
        html = opening + source[card.opening_end:card.end]
        groups[semester(first)].append((first, html))
        start, end = card.start, card.end
        line_start = source.rfind('\n', 0, start) + 1
        line_end = source.find('\n', end)
        if not source[line_start:start].strip() and line_end != -1 and not source[end:line_end].strip():
            start, end = line_start, line_end + 1
        edits.append((start, end, ''))
        moved.append(f"{raw_date}: {fields.get('speaker', 'Unknown speaker')}")

    if not moved:
        return source, moved, skipped
    newline = '\r\n' if '\r\n' in source else '\n'
    new_sections, new_buttons = [], []
    for (identity, label, month), cards in sorted(groups.items(), reverse=True):
        cards.sort(key=lambda item: item[0])
        block = ''.join(newline + '                    ' + html for _, html in cards)
        targets = [node for node in past.children if node.attrs.get('id') == identity]
        if targets:
            if len(targets) != 1:
                raise ValueError(f'Duplicate archive section: {identity}')
            # Keep existing reports above the newly archived batch.
            existing = [node for node in targets[0].children if node.tag == 'article']
            insertion = existing[-1].end if existing else targets[0].opening_end
            edits.append((insertion, insertion, block))
        else:
            new_sections.append(
                f'{newline}                <section id="{identity}" class="sub-page-content semester-section" '
                f'data-calendar-start="{month}" hidden>{block}{newline}                </section>')
            new_buttons.append(
                f'{newline}                    <button type="button" data-target="{identity}" '
                f'aria-controls="{identity}" aria-pressed="false">{label}</button>')
    if new_sections:
        navigation = doc.by_id('semester-navigation')
        edits.append((past.opening_end, past.opening_end, ''.join(new_sections)))
        edits.append((navigation.opening_end, navigation.opening_end, ''.join(new_buttons)))
    result = source
    for start, end, replacement in sorted(edits, reverse=True):
        result = result[:start] + replacement + result[end:]
    # Validate structure and conservation before returning anything to the writer.
    updated = Document(result)
    before = sum(node.tag == 'article' for node in doc.elements)
    after = sum(node.tag == 'article' for node in updated.elements)
    if before != after:
        raise ValueError('Article count changed; no changes written.')
    return result, moved, skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', type=Path, default=Path(__file__).resolve().parents[1] / 'index.html')
    parser.add_argument('--now', help='ISO timestamp with timezone, for reproducible checks')
    parser.add_argument('--write', action='store_true', help='Apply changes (default is dry run)')
    args = parser.parse_args()
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(DALIAN)
    source = args.file.read_bytes().decode('utf-8')
    result, moved, skipped = archive(source, now)
    print(f'Checked: {now.astimezone(DALIAN).isoformat()}')
    for item in moved:
        print(f'Archive: {item}')
    for item in skipped:
        print(f'Needs review (kept in Upcoming): {item}')
    if args.write and result != source:
        args.file.write_bytes(result.encode('utf-8'))
    print(f'{len(moved)} report(s) {"archived" if args.write else "ready to archive (dry run)"}.')


if __name__ == '__main__':
    main()
