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
MONTHS = {name: i for i, name in enumerate(
    ('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'), 1)}


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
    match = re.fullmatch(r'([A-Za-z]+)\s+(\d{1,2})(?:\s*[-–—]\s*(\d{1,2}))?,\s*(\d{4})', raw.strip())
    if not match or match[1][:3].lower() not in MONTHS:
        raise ValueError(f'Unrecognized date: {raw!r}')
    month, year = MONTHS[match[1][:3].lower()], int(match[4])
    first = date(year, month, int(match[2]))
    last = date(year, month, int(match[3] or match[2]))
    if last < first:
        raise ValueError(f'Reversed date range: {raw!r}')
    return first, last


def end_of_report(last, raw_time):
    parts = re.split('[-–—]', raw_time.lower())
    match = re.fullmatch(r'\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*', parts[1]) if len(parts) == 2 else None
    if match:
        hour, minute = int(match[1]), int(match[2] or 0)
        meridiem = match[3]
        if minute < 60 and (1 <= hour <= 12 if meridiem else 0 <= hour <= 23):
            if meridiem:
                hour = hour % 12 + (12 if meridiem == 'pm' else 0)
            return datetime.combine(last, time(hour, minute), DALIAN)
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
        if card.tag != 'article' or not card.has_class('seminar') or card.has_class('notice-seminar'):
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
        opening = re.sub(r'\bupcoming-seminar\b', 'past-seminar', opening)
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
