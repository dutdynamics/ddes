"""Run with python -m unittest discover -s scripts -p test_report_builder.py."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from report_builder import ReportError, build_pdf, escape_text, export_tex, find_compiler, render_report, validate_event


EVENT = {'id': 'sample', 'date': '2026-10-08', 'speakerName': 'Jiexin Sun',
         'speakerAffiliation': '孙洁昕, PostDoc@DUT',
         'title': 'Stability of the $N$-body problem',
         'abstract': 'We study $\\frac{x^2}{2} + \\alpha$ & related problems.\n\nA second paragraph.',
         'experiences': [{'period': '2026.06--Present', 'position': 'PostDoc',
                          'university': 'Dalian University of Technology', 'country': 'China'}],
         'interests': ['Dynamical systems,', 'Partial differential equations.']}


class ReportBuilderTests(unittest.TestCase):
    def test_default_time_place_and_real_weekday(self):
        source = render_report(EVENT)
        self.assertIn('9:00am - 9:45am, Thursday, October 8, 2026', source)
        self.assertIn(r'\newcommand{\SeminarVenue}{Seminar Room 114}', source)
        self.assertIn('孙洁昕', source)

    def test_afternoon_and_non_thursday_are_honored(self):
        event = dict(EVENT, date='2026-10-09', startTime='14:00', endTime='14:45', place='Room 111-A')
        self.assertIn('2:00pm - 2:45pm, Friday, October 9, 2026', render_report(event))
        self.assertIn('Seminar Room 111-A', render_report(event))

    def test_multiday_dates_are_complete_and_single_day_is_unchanged(self):
        self.assertEqual(render_report(EVENT), render_report(dict(EVENT, endDate=EVENT['date'])))
        ranged = render_report(dict(EVENT, endDate='2026-10-09'))
        self.assertIn('Thursday, October 8, 2026 - Friday, October 9, 2026', ranged)
        self.assertIn('9:00am - 9:45am', ranged)
        across_months = render_report(dict(EVENT, endDate='2026-11-01'))
        self.assertIn('Sunday, November 1, 2026', across_months)

    def test_literal_tex_special_characters(self):
        self.assertEqual(escape_text('A&B_50% #1 {x} ~ ^', formulas=False),
                         r'A\&B\_50\% \#1 \{x\} \textasciitilde{} \textasciicircum{}')
        self.assertEqual(escape_text(r'Cost: \$5'), r'Cost: \$5')

    def test_allowed_formula_and_matrix(self):
        formula = r'$\begin{pmatrix}1 & \alpha \\ 0 & \sqrt{x}\end{pmatrix}$'
        self.assertEqual(escape_text(formula), formula)
        self.assertEqual(escape_text(r'$$\int_0^1 f(x)\,dx$$'), r'\[\int_0^1 f(x)\,dx\]')
        self.assertEqual(escape_text(r'\(x+y\)'), r'\(x+y\)')

    def test_formula_injections_are_rejected(self):
        for command in ('input', 'include', 'write', 'immediate', 'catcode',
                        'csname', 'def', 'newcommand', 'usepackage', 'openout',
                        'special', 'href', 'url', 'scantokens'):
            with self.subTest(command=command), self.assertRaises(ReportError):
                escape_text('$\\' + command + '{anything}$')
        for formula in (r'$\begin{document}x\end{document}$', r'$x% hidden$',
                        r'$^^5cinput{secret}$', r'$^^^^005cinput{secret}$',
                        r'$\text{\input{file}}$', r'$x} $', r'$x & y$'):
            with self.subTest(formula=formula), self.assertRaises(ReportError):
                escape_text(formula)

    def test_outside_math_commands_are_rejected(self):
        for text in (r'\input{secret}', r'\end{document}', r'\write18{command}'):
            with self.subTest(text=text), self.assertRaises(ReportError):
                escape_text(text)

    def test_unclosed_math_rejected(self):
        for text in ('$x', r'\[x', r'$\frac{x}{y$', r'$\begin{cases}x$'):
            with self.subTest(text=text), self.assertRaises(ReportError):
                escape_text(text)

    def test_interest_punctuation_and_empty_rows(self):
        event = deepcopy(EVENT)
        event['experiences'].append({'period': '', 'position': '', 'university': '', 'country': ''})
        source = render_report(event)
        self.assertIn('Dynamical systems, Partial differential equations.', source)
        self.assertNotIn('equations.,', source)
        self.assertEqual(len(validate_event(event)['experiences']), 1)
        self.assertIn('PostDoc, Dalian University of Technology, China.', source)

    def test_custom_position_and_asset_identity(self):
        event = deepcopy(EVENT)
        event['experiences'][0]['position'] = 'Research Fellow & Lecturer'
        source = render_report(event)
        self.assertIn(r'Research Fellow \& Lecturer', source)
        for asset in ('DUT_symbol.pdf', 'QR.pdf', 'dlade-favicon.pdf'):
            self.assertIn(asset, source)
        self.assertIn('FandolSong-Regular', source)
        self.assertIn('DLADEGold', source)
        self.assertNotIn(r'(\SpeakerAffiliation)', render_report(dict(EVENT, speakerAffiliation='')))

    def test_long_abstract_and_cv_can_flow(self):
        event = deepcopy(EVENT)
        event['abstract'] = 'Long abstract. ' * 800
        event['experiences'] *= 30
        source = render_report(event)
        self.assertNotIn(r'\dimexpr0.50\textheight', source)
        self.assertEqual(source.count(r'\begin{tabularx}{\textwidth}{@{}>{\bfseries}'), 30)
        self.assertIn('Long abstract. ' * 10, source)

    def test_bad_date_times_and_missing_speaker(self):
        for change in ({'date': '2026-02-30'}, {'date': '2026-2-3'},
                       {'startTime': '24:00'}, {'endTime': '09:00'},
                       {'speakerName': ''}, {'interests': 'not a list'},
                       {'experiences': [{}] * 51}, {'endDate': '2026-10-07'},
                       {'endDate': '2026-02-30'}, {'date': '0001-10-08'},
                       {'title': '\ud800'}):
            with self.subTest(change=change), self.assertRaises(ReportError):
                validate_event(dict(EVENT, **change))

    def test_existing_compiler_fallback_and_missing_installation(self):
        fallback = SimpleNamespace(is_file=lambda: True, __str__=lambda: 'fallback-xelatex')
        with patch('report_builder.shutil.which', return_value=None), patch('report_builder.WINDOWS_COMPILER', fallback):
            self.assertTrue(find_compiler())
        with patch('report_builder.shutil.which', return_value=None), patch('report_builder.WINDOWS_COMPILER', Path('nonexistent-test-xelatex')):
            with self.assertRaises(ReportError):
                find_compiler()
        self.assertEqual(find_compiler('custom-xelatex'), 'custom-xelatex')

    def test_tex_export(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temporary:
            output = Path(temporary) / 'report.tex'
            self.assertEqual(export_tex(EVENT, output), output)
            self.assertEqual(output.read_text(encoding='utf-8'), render_report(EVENT))

    def test_template_font_changes_preserve_report_content(self):
        template = Path(__file__).resolve().parents[1] / 'report-template' / 'main.tex'
        source = template.read_text(encoding='utf-8')
        source = source.replace(r'\fontsize{10.4}{12.4}', r'\fontsize{12.6}{15}')
        source = source.replace(r'\fontsize{9.9}{11.8}', r'\fontsize{12.2}{14.6}')
        source = source.replace(r'\fontsize{10.2}{12.1}', r'\fontsize{12.3}{14.8}')
        source = source.replace('p{28mm}', 'p{31mm}')
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temporary:
            path = Path(temporary) / 'custom.tex'
            path.write_text(source, encoding='utf-8')
            rendered = render_report(EVENT, template_path=path)
        for command in (r'\fontsize{12.6}{15}', r'\fontsize{12.2}{14.6}',
                        r'\fontsize{12.3}{14.8}', 'p{31mm}'):
            self.assertIn(command, rendered)
        self.assertIn(r'We study $\frac{x^2}{2} + \alpha$ \& related problems.', rendered)
        self.assertIn('PostDoc, Dalian University of Technology, China.', rendered)
        self.assertIn('Dynamical systems, Partial differential equations.', rendered)

    def test_invalid_input_never_invokes_compiler(self):
        with patch('report_builder.subprocess.run') as compiler:
            with self.assertRaises(ReportError):
                build_pdf(dict(EVENT, abstract=r'$\input{secret}$'), Path('ignored.pdf'))
            compiler.assert_not_called()

    def test_compilation_uses_restricted_flags_and_cleans_working_directory(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temporary:
            output = Path(temporary) / 'report.pdf'
            working_directories = []

            def successful_compile(command, **arguments):
                self.assertIn('-no-shell-escape', command)
                self.assertNotIn('-shell-escape', command)
                self.assertEqual(arguments['env']['openin_any'], 'p')
                self.assertEqual(arguments['env']['openout_any'], 'p')
                self.assertEqual(arguments['timeout'], 90)
                working = arguments['cwd']
                working_directories.append(working)
                self.assertTrue((working / 'QR.pdf').exists())
                (working / 'report.pdf').write_bytes(b'%PDF-1.7 test')
                (working / 'report.log').write_text('Compilation succeeded.', encoding='utf-8')
                return SimpleNamespace(returncode=0, stdout=b'')

            with patch('report_builder.subprocess.run', side_effect=successful_compile):
                self.assertEqual(build_pdf(EVENT, output, compiler='xelatex'), output)
            self.assertEqual(output.read_bytes(), b'%PDF-1.7 test')
            self.assertFalse(working_directories[0].exists())

    def test_overflow_missing_glyph_and_compiler_error_do_not_replace_old_pdf(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temporary:
            output = Path(temporary) / 'report.pdf'
            output.write_bytes(b'Previous PDF')
            for warning, code in ((r'Overfull \hbox (12.0pt too wide)', 0),
                                  (r'Overfull \vbox (42.0pt too high)', 0),
                                  ('Missing character: There is no character in font!', 0),
                                  ('! Undefined control sequence.', 1)):
                def unsuccessful_compile(command, **arguments):
                    (arguments['cwd'] / 'report.pdf').write_bytes(b'Bad PDF')
                    (arguments['cwd'] / 'report.log').write_text(warning, encoding='utf-8')
                    return SimpleNamespace(returncode=code, stdout=b'')
                with self.subTest(warning=warning), patch('report_builder.subprocess.run', side_effect=unsuccessful_compile):
                    with self.assertRaises(ReportError):
                        build_pdf(EVENT, output, compiler='xelatex')
                    self.assertEqual(output.read_bytes(), b'Previous PDF')


if __name__ == '__main__':
    unittest.main()
