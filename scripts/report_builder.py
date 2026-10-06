"""Create seminar posters from the supplied XeLaTeX template.

User strings are escaped. Formula delimiters ($...$, \\(...\\), \\[...\\])
permit a finite set of mathematical commands, never file access or TeX macros.
Compilation runs with shell escape disabled in a private temporary directory.
"""

from __future__ import annotations

import argparse
from datetime import date, time
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


TEMPLATE_DIR = Path(__file__).resolve().parents[1] / 'report-template'
WINDOWS_COMPILER = Path('D:/Software/TexLive/texlive/2026/bin/windows/xelatex.exe')
ASSETS = ('DUT_symbol.pdf', 'QR.pdf', 'dlade-favicon.pdf')

# These are ordinary, non-programmable mathematical symbols and constructors.
MATH_COMMANDS = frozenset('''
alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa
lambda mu nu xi pi varpi rho varrho sigma varsigma tau upsilon phi varphi chi
psi omega Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega
frac dfrac tfrac binom dbinom tbinom sqrt overline underline widehat widetilde
hat tilde bar vec dot ddot mathbf mathrm mathit mathsf mathtt mathcal mathbb
boldsymbol text operatorname left right middle big Big bigg Bigg
bigl bigr Bigl Bigr biggl biggr Biggl Biggr
sum prod coprod int iint iiint oint lim limsup liminf inf sup max min
sin cos tan cot sec csc sinh cosh tanh log ln exp det dim ker gcd arg
mod bmod pmod equiv ne neq le leq ge geq ll gg approx sim simeq cong
in notin ni subset subseteq supset supseteq emptyset varnothing
cup cap bigcup bigcap setminus times cdot div pm mp
otimes oplus odot wedge vee land lor neg forall exists
to mapsto rightarrow leftarrow leftrightarrow Rightarrow Leftarrow
Leftrightarrow longrightarrow longleftarrow longleftrightarrow
Longrightarrow Longleftarrow Longleftrightarrow hookrightarrow
uparrow downarrow partial nabla infinity infty ell hbar Re Im
ldots cdots vdots ddots dots colon perp parallel angle
langle rangle lvert rvert lVert rVert vert Vert lbrace rbrace
quad qquad thinspace enspace limits nolimits displaystyle textstyle
scriptstyle scriptscriptstyle substack overset underset underbrace overbrace
phantom vphantom hphantom
'''.split())
MATH_ENVIRONMENTS = frozenset(('aligned', 'gathered', 'matrix', 'pmatrix',
                               'bmatrix', 'Bmatrix', 'vmatrix', 'Vmatrix',
                               'cases', 'smallmatrix', 'split'))
ESCAPES = {'\\': r'\textbackslash{}', '{': r'\{', '}': r'\}',
           '$': r'\$', '&': r'\&', '#': r'\#', '%': r'\%',
           '_': r'\_', '^': r'\textasciicircum{}', '~': r'\textasciitilde{}'}


class ReportError(ValueError):
    """A clear input, template or compilation error, safe to show in the editor."""


def _string(value, field, maximum=1000):
    if not isinstance(value, str):
        raise ReportError(f'{field} must be text.')
    if len(value) > maximum:
        raise ReportError(f'{field} exceeds the {maximum}-character limit.')
    if any(ord(char) < 32 and char not in '\n\r\t' for char in value):
        raise ReportError(f'{field} contains an unsupported control character.')
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ReportError(f'{field} contains invalid Unicode.')
    return value.strip()


def _validate_math(source):
    """Validate TeX tokens without executing TeX; deny every unknown command."""
    if '^^' in source:
        raise ReportError('TeX character-code escapes are not allowed in formulas.')
    depth = 0
    environments = []
    position = 0
    while position < len(source):
        char = source[position]
        if char == '\\':
            match = re.match(r'\\([A-Za-z]+|.)', source[position:], re.S)
            if not match:
                raise ReportError('A formula ends with an incomplete backslash.')
            command = match.group(1)
            position += len(match.group(0))
            if command in ('begin', 'end'):
                environment = re.match(r'\{([A-Za-z]+)\}', source[position:])
                if not environment or environment.group(1) not in MATH_ENVIRONMENTS:
                    raise ReportError('Only supported mathematical environments are allowed.')
                name = environment.group(1)
                if command == 'begin':
                    environments.append(name)
                elif not environments or environments.pop() != name:
                    raise ReportError('The mathematical environment delimiters do not match.')
                position += len(environment.group(0))
            elif command not in MATH_COMMANDS and command not in ('{', '}', '%',
                    '#', '&', '_', '$', ',', ';', ':', '!', ' ', '\\', '|'):
                raise ReportError(f'Unsupported TeX command: \\{command}.')
            continue
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth < 0:
                raise ReportError('A formula has unbalanced braces.')
        elif char in ('%', '#', '$', '\x00'):
            raise ReportError(f'Use an escaped {char!r} inside formulas.')
        elif char == '&' and not environments:
            raise ReportError('Alignment characters need a mathematical environment.')
        position += 1
    if depth or environments:
        raise ReportError('A formula has unclosed braces or an environment.')
    return source


def escape_text(source, *, formulas=True, paragraphs=False):
    """Escape literal text while preserving only validated delimited formulas."""
    source = _string(source, 'Text', 20000).replace('\r\n', '\n').replace('\r', '\n')
    output = []
    position = 0
    while position < len(source):
        char = source[position]
        delimiter = None
        if formulas and source.startswith('$$', position):
            delimiter = ('$$', '$$')
        elif formulas and char == '$':
            delimiter = ('$', '$')
        elif formulas and source.startswith(r'\(', position):
            delimiter = (r'\(', r'\)')
        elif formulas and source.startswith(r'\[', position):
            delimiter = (r'\[', r'\]')
        if delimiter:
            opening, closing = delimiter
            end = position + len(opening)
            while end < len(source):
                if source.startswith(closing, end):
                    # An odd number of immediately preceding backslashes escapes '$'.
                    backslashes = 0
                    before = end - 1
                    while before >= 0 and source[before] == '\\':
                        backslashes += 1
                        before -= 1
                    if closing != '$' and closing != '$$' or backslashes % 2 == 0:
                        break
                end += 1
            else:
                raise ReportError(f'The formula beginning with {opening} is not closed.')
            body = _validate_math(source[position + len(opening):end])
            # Prefer LaTeX display math to the less predictable primitive $$ form.
            if opening == '$$':
                opening, closing = r'\[', r'\]'
            output.extend((opening, body, closing))
            position = end + len(delimiter[1])
            continue
        if char == '\\' and position + 1 < len(source):
            following = source[position + 1]
            if following in '$%#&_{}':
                output.append(ESCAPES[following])
                position += 2
                continue
            # Do not silently turn a requested command into an apparently valid poster.
            match = re.match(r'\\([A-Za-z]+|[\[\]()])', source[position:])
            if match:
                raise ReportError(f'Unsupported TeX outside a formula: {match.group(0)}.')
        if char == '\n':
            if paragraphs and position + 1 < len(source) and source[position + 1] == '\n':
                output.append('\n\n')
                while position + 1 < len(source) and source[position + 1] == '\n':
                    position += 1
            else:
                output.append(' ')
        else:
            output.append(ESCAPES.get(char, char))
        position += 1
    return ''.join(output)


def validate_event(event):
    if not isinstance(event, dict):
        raise ReportError('The report must be a JSON object.')
    result = dict(event)
    raw_date = _string(event.get('date', ''), 'Date', 10)
    try:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', raw_date):
            raise ValueError()
        result['date'] = date.fromisoformat(raw_date)
        if result['date'].year < 1000:
            raise ValueError()
    except ValueError:
        raise ReportError('Choose a valid date in YYYY-MM-DD format.') from None
    raw_end = _string(event.get('endDate', ''), 'End date', 10) or raw_date
    try:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', raw_end):
            raise ValueError()
        result['endDate'] = date.fromisoformat(raw_end)
        if result['endDate'] < result['date']:
            raise ValueError()
    except ValueError:
        raise ReportError('Choose a valid end date that is not before the start date.') from None
    for field, default in (('startTime', '09:00'), ('endTime', '09:45')):
        raw = _string(event.get(field, default), field, 5)
        try:
            if not re.fullmatch(r'\d{2}:\d{2}', raw):
                raise ValueError()
            result[field] = time.fromisoformat(raw)
        except ValueError:
            raise ReportError(f'{field} must be a valid HH:MM time in Beijing time.') from None
    if result['endTime'] <= result['startTime']:
        raise ReportError('The end time must follow the start time on the chosen date.')
    limits = {'speakerName': 180, 'speakerAffiliation': 350, 'place': 180,
              'title': 800, 'abstract': 20000}
    for field, limit in limits.items():
        default = 'Room 114' if field == 'place' else 'TBA' if field in ('title', 'abstract') else ''
        result[field] = _string(event.get(field, default), field, limit) or default
    if not result['speakerName']:
        raise ReportError('Enter the speaker name before generating a report.')
    experiences = event.get('experiences', [])
    if not isinstance(experiences, list) or len(experiences) > 50:
        raise ReportError('Experiences must contain at most 50 rows.')
    result['experiences'] = []
    for number, item in enumerate(experiences, 1):
        if not isinstance(item, dict):
            raise ReportError(f'Experience {number} must be an object.')
        row = {key: _string(item.get(key, ''), f'Experience {number} {key}', maximum)
               for key, maximum in (('period', 120), ('position', 180),
                                     ('university', 260), ('country', 120))}
        if any(row.values()):
            result['experiences'].append(row)
    interests = event.get('interests', [])
    if not isinstance(interests, list) or len(interests) > 100:
        raise ReportError('Research interests must contain at most 100 keywords.')
    result['interests'] = [_string(item, 'Research interest', 300).rstrip(' ,.;，。；')
                           for item in interests]
    result['interests'] = [item for item in result['interests'] if item]
    return result


def _time_label(value):
    return f'{value.hour % 12 or 12}:{value.minute:02d}{"am" if value.hour < 12 else "pm"}'


def _replace_once(pattern, replacement, source, label, flags=0):
    source, count = re.subn(pattern, lambda match: replacement, source, count=0, flags=flags)
    if count != 1:
        raise ReportError(f'The supplied template has an unexpected {label} section.')
    return source


def render_report(event, template_path=None):
    """Return portable TeX using the trusted template and escaped report fields."""
    event = validate_event(event)
    template_path = Path(template_path) if template_path else TEMPLATE_DIR / 'main.tex'
    source = template_path.read_text(encoding='utf-8')
    day = event['date']
    def label(value):
        return f'{value.strftime("%A")}, {value.strftime("%B")} {value.day}, {value.year}'
    date_label = label(day)
    if event['endDate'] != day:
        date_label += ' - ' + label(event['endDate'])
    clock_label = f'{_time_label(event["startTime"])} - {_time_label(event["endTime"])}'
    venue = event['place']
    if re.fullmatch(r'Room\s+.+', venue, flags=re.I):
        venue = 'Seminar ' + venue
    values = {'SeminarTitle': escape_text(event['title']),
              'SpeakerName': escape_text(event['speakerName'], formulas=False),
              'SpeakerAffiliation': escape_text(event['speakerAffiliation'], formulas=False),
              'SeminarVenue': escape_text(venue, formulas=False),
              'SeminarTime': escape_text(f'{clock_label}, {date_label}', formulas=False)}
    for name, value in values.items():
        source = _replace_once(r'\\newcommand\{\\' + name + r'\}\{[^\n]*\}',
                               f'\\newcommand{{\\{name}}}{{{value}}}', source, name)
    if not event['speakerAffiliation']:
        source = source.replace(r' (\SpeakerAffiliation)', '', 1)

    # A fixed-height minipage cannot split across pages and can overwrite the CV.
    fixed_opening = r'\begin{minipage}[t][\dimexpr0.50\textheight+35mm\relax][t]{\textwidth}'
    if source.count(fixed_opening) != 1:
        raise ReportError('The supplied template has an unexpected upper-half layout.')
    source = source.replace(fixed_opening + '\n\\vspace{0pt}', '', 1)
    closing = '\\vfill\n\\end{minipage}\n\\par\n\\nointerlineskip'
    if source.count(closing) != 1:
        raise ReportError('The supplied template has an unexpected biography boundary.')
    source = source.replace(closing, '\\par\n\\vspace{6mm}', 1)

    abstract = ('{\\fontsize{9.7}{11.55}\\selectfont\n'
                '  \\textbf{Abstract.}\n  ' + escape_text(event['abstract'], paragraphs=True)
                + '\n  \\par\n}')
    source = _replace_once(r'\{\\fontsize\{9\.7\}\{11\.55\}\\selectfont.*?\n\}',
                           abstract, source, 'abstract', re.S)

    rows = []
    for row in event['experiences']:
        detail = ', '.join(row[key].rstrip(' ,.;，。；') for key in
                           ('position', 'university', 'country') if row[key]) + '.'
        rows.append('  \\noindent\\begin{tabularx}{\\textwidth}'
                    '{@{}>{\\bfseries}p{25mm}@{\\hspace{2mm}}>'
                    '{\\raggedright\\arraybackslash}X@{}}\n    '
                    + escape_text(row['period'], formulas=False) + ' & '
                    + escape_text(detail, formulas=False)
                    + '\n  \\end{tabularx}\\par\\vspace{0.35mm}')
    biography = '{\\fontsize{9.2}{11}\\selectfont\n' + '\n'.join(rows) + '\n}'
    source = _replace_once(r'\{\\fontsize\{9\.2\}\{11\}\\selectfont.*?\n\}',
                           biography, source, 'biography', re.S)
    keywords = ', '.join(escape_text(item) for item in event['interests']) + '.' if event['interests'] else 'TBA.'
    interests = ('{\\fontsize{9.5}{11.3}\\selectfont\n'
                 '  \\textbf{Research Interests:}\n  ' + keywords + '\n  \\par\n}')
    return _replace_once(r'\{\\fontsize\{9\.5\}\{11\.3\}\\selectfont.*?\n\}',
                         interests, source, 'research interests', re.S)


def export_tex(event, output, template_path=None):
    output = Path(output)
    source = render_report(event, template_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(source, encoding='utf-8')
    return output


def find_compiler(compiler=None):
    """Find the existing XeLaTeX installation without installing dependencies."""
    compiler = compiler or shutil.which('xelatex') or (str(WINDOWS_COMPILER) if WINDOWS_COMPILER.is_file() else None)
    if not compiler:
        raise ReportError('XeLaTeX is unavailable. Export the .tex report instead.')
    return str(compiler)


def build_pdf(event, output, compiler=None, template_dir=None):
    """Compile to PDF; reject failures and content that overflows the page."""
    template_dir = Path(template_dir) if template_dir else TEMPLATE_DIR
    source = render_report(event, template_dir / 'main.tex')
    compiler = find_compiler(compiler)
    output = Path(output)
    if output.suffix.lower() != '.pdf':
        raise ReportError('The PDF output filename must end in .pdf.')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ddes-report-', dir=output.parent) as temporary:
        working = Path(temporary)
        for name in ASSETS:
            asset = template_dir / name
            if not asset.is_file():
                raise ReportError(f'The report template is missing {name}.')
            shutil.copyfile(asset, working / name)
        (working / 'report.tex').write_text(source, encoding='utf-8')
        environment = dict(os.environ)
        environment.update({'openin_any': 'p', 'openout_any': 'p', 'shell_escape': 'f'})
        command = [str(compiler), '-no-shell-escape', '-interaction=nonstopmode',
                   '-halt-on-error', '-file-line-error', 'report.tex']
        try:
            result = subprocess.run(command, cwd=working, env=environment,
                                    stdin=subprocess.DEVNULL, capture_output=True,
                                    timeout=90, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ReportError(f'The PDF compiler could not finish: {error}.') from None
        log = (working / 'report.log').read_text(encoding='utf-8', errors='replace') if (working / 'report.log').exists() else ''
        if result.returncode or not (working / 'report.pdf').is_file():
            lines = (log or result.stdout.decode('utf-8', errors='replace')).splitlines()
            relevant = [line for line in lines if line.startswith('!') or 'report.tex:' in line]
            raise ReportError('PDF compilation failed. ' + ' '.join(relevant[-4:])[:1200])
        if re.search(r'Overfull \\[hv]box', log):
            raise ReportError('Some report content exceeds the page width or height. '
                              'Shorten long words, formulas or experience rows and try again.')
        if 'Missing character:' in log:
            raise ReportError('The template fonts cannot display one or more characters. '
                              'Replace those characters before generating the PDF.')
        shutil.copyfile(working / 'report.pdf', output)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path, help='UTF-8 JSON event file')
    parser.add_argument('--output', type=Path, help='PDF destination')
    parser.add_argument('--tex-output', type=Path, help='Optional TeX destination; works without a compiler')
    parser.add_argument('--compiler', help='XeLaTeX executable path')
    args = parser.parse_args(argv)
    if not args.output and not args.tex_output:
        parser.error('Choose --output and/or --tex-output.')
    try:
        if args.input.stat().st_size > 150000:
            raise ReportError('The input JSON exceeds the 150 KB limit.')
        event = json.loads(args.input.read_text(encoding='utf-8-sig'))
        if args.tex_output:
            export_tex(event, args.tex_output)
            print(f'TeX saved: {args.tex_output}')
        if args.output:
            build_pdf(event, args.output, compiler=args.compiler)
            print(f'PDF saved: {args.output}')
    except (ReportError, OSError, json.JSONDecodeError) as error:
        parser.exit(1, f'Report error: {error}\n')


if __name__ == '__main__':
    main()
