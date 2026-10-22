"""Behavioral tests for the read-only localization CLI; all inputs are disposable."""
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'check_localization.py'


class LocalizationCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.root = self.home / 'game'
        self.root.mkdir()
        self.output = self.home / 'results'
        self.profile = self.home / 'profile.toml'

    def table(self, rows, header=('id', 'en', 'ja'), name='i18n.csv'):
        path = self.root / name
        with path.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(header)
            writer.writerows(rows)
        return path

    def config(self, extra='', source='i18n.csv', mapping='en="en", ja="ja"', text=''):
        self.profile.write_text(f'''schema_version = 1
base_language = "en"
required_languages = ["en", "ja"]
[[sources]]
path = {json.dumps(source)}
namespace = "main"
header_row = 1
data_start_row = 2
key_column = "id"
language_columns = {{ {mapping} }}
[text]
placeholder_styles = ["percent_named", "dotnet"]
rich_text_profile = "unity_tmp_3"
literal_backslash_n_is_newline = true
{text}
{extra}
''', encoding='utf-8')

    def cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                              text=True, capture_output=True)

    def scan(self, checks='text', expected=None):
        proc = self.cli('scan', '--root', self.root, '--config', self.profile,
                        '--out', self.output, '--checks', checks)
        if expected is not None:
            self.assertEqual(proc.returncode, expected, proc.stdout + proc.stderr)
        report = self.output / 'scan.json'
        self.assertTrue(report.is_file(), proc.stdout + proc.stderr)
        return json.loads(report.read_text()), proc

    def rules(self, report):
        return [x['rule'] for x in report['findings'] if not x.get('suppressed')]

    def test_empty_translation_and_parameter_count_have_exact_locations(self):
        self.table([('EMPTY', 'Play', ''), ('COUNT', '%n% %n%', '%n%')])
        self.config()
        report, _ = self.scan(expected=1)
        empty = next(x for x in report['findings'] if x['rule'] == 'text.empty')
        self.assertEqual((empty['key'], empty['language'], empty['location']['cell']),
                         ('EMPTY', 'ja', 'C2'))
        diff = next(x for x in report['findings'] if x['rule'] == 'text.parameters')
        self.assertEqual(diff['details']['missing'], {'%n%': 1})

    def test_parameter_reordering_and_escaped_dotnet_braces_are_accepted(self):
        self.table([('ORDER', '%first% %second%', '%second% %first%'),
                    ('BRACE', '{{name}} {0:N0}', '{0:N0} {{名前}}')])
        self.config()
        report, _ = self.scan(expected=0)
        self.assertNotIn('text.parameters', self.rules(report))

    def test_missing_required_column_is_reported_without_empty_cell_flood(self):
        self.table([('ONE', 'Play')], header=('id', 'en'))
        self.config()
        report, _ = self.scan(expected=1)
        self.assertEqual(self.rules(report).count('input.language_column'), 1)
        self.assertNotIn('text.empty', self.rules(report))

    def test_duplicate_key_keeps_all_locations_and_trim_collision_is_separate(self):
        self.table([('K', 'One', '一'), ('K', 'Two', '二'), (' K ', 'Three', '三')])
        self.config()
        report, _ = self.scan(expected=1)
        dup = next(x for x in report['findings'] if x['rule'] == 'key.duplicate')
        self.assertEqual([x['cell'] for x in dup['details']['locations']], ['A2', 'A3'])
        self.assertIn('key.whitespace', self.rules(report))
        self.assertIn('key.trim_collision', self.rules(report))

    def test_tmp_independent_tags_noparse_and_legal_overlap_not_xml_errors(self):
        self.table([('RICH', '<b><i>Win</b></i><br><sprite index=0>',
                     '<b><i>勝利</b></i><br><sprite index=0>'),
                    ('RAW', '<noparse><color=red></noparse>',
                     '<noparse><color=blue></noparse>')])
        self.config()
        report, _ = self.scan(expected=0)
        self.assertFalse(any(x in self.rules(report) for x in
                             ['text.richtext', 'text.richtext_identity']))

    def test_unclosed_tags_and_changed_link_target_are_distinguished(self):
        self.table([('UNCLOSED', '<b>Play</b>', '<b>遊ぶ'),
                    ('LINK', '<link="terms">Terms</link>', '<link="privacy">規約</link>')])
        self.config()
        report, _ = self.scan(expected=1)
        self.assertIn('text.richtext', self.rules(report))
        self.assertIn('text.richtext_identity', self.rules(report))

    def test_literal_angles_not_mistaken_for_tags(self):
        self.table([('MATH', 'Score < 5', '得点 < 5')])
        self.config()
        report, _ = self.scan(expected=0)
        self.assertNotIn('text.richtext', self.rules(report))

    def test_controls_are_errors_but_joiners_are_not_blanket_errors(self):
        self.table([('BAD', 'A', '日\x00本'), ('JOIN', 'B', 'क्\u200dष')])
        self.config()
        report, _ = self.scan(expected=1)
        controls = [x for x in report['findings'] if x['rule'] == 'text.control']
        self.assertEqual(len(controls), 1)
        self.assertEqual(controls[0]['details']['codepoint'], 'U+0000')

    def test_double_escaped_newline_is_a_candidate_not_a_translation_error(self):
        self.table([('NL', 'A\\nB', '日\\\\n本')])
        self.config()
        report, _ = self.scan(expected=0)
        self.assertIn('text.escape', self.rules(report))

    def test_same_text_is_candidate_and_numeric_values_are_excluded(self):
        self.table([('SAME', 'Shop', 'Shop'), ('NUM', '123', '123'), ('PARAM', '%n%', '%n%')])
        self.config()
        report, _ = self.scan(expected=0)
        candidates = [x['key'] for x in report['findings'] if x['rule'] == 'text.same_as_base']
        self.assertEqual(candidates, ['SAME'])

    def test_exception_is_exact_and_expires_when_text_changes(self):
        self.table([('BRAND', 'Brand', 'Brand'), ('OTHER', 'Shop', 'Shop')])
        self.config('''[[exceptions]]
rule = "text.same_as_base"
namespace = "main"
key = "BRAND"
language = "ja"
value = "Brand"
reason = "确认的品牌名"
''')
        report, _ = self.scan(expected=0)
        self.assertEqual(report['summary']['suppressed'], 1)
        self.table([('BRAND', 'New Brand', 'New Brand')])
        report, _ = self.scan(expected=0)
        self.assertEqual(report['summary']['suppressed'], 0)

    def test_empty_baseline_does_not_make_target_parameters_extra(self):
        self.table([('BASE', '', '%n% 件')])
        self.config()
        report, _ = self.scan(expected=1)
        self.assertNotIn('text.parameters', self.rules(report))
        self.assertTrue(report['blocked'])

    def test_missing_file_returns_incomplete_report(self):
        self.config()
        report, _ = self.scan(expected=2)
        self.assertFalse(report['summary']['complete'])

    def test_source_hashes_are_preserved_and_repeated_findings_stable(self):
        source = self.table([('K', '%n%', '日本')])
        self.config()
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        first, _ = self.scan(expected=1)
        second, _ = self.scan(expected=1)
        self.assertEqual(first['findings'], second['findings'])
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)

    def test_report_output_inside_project_is_refused(self):
        self.table([('K', 'Play', '遊ぶ')])
        self.config()
        self.output = self.root / 'reports'
        proc = self.cli('scan', '--root', self.root, '--config', self.profile,
                        '--out', self.output)
        self.assertEqual(proc.returncode, 2)
        self.assertFalse(self.output.exists())

    def test_inspect_filters_and_paginates_without_dropping_total(self):
        self.table([(f'K{i}', 'Shop', 'Shop') for i in range(5)])
        self.config()
        self.scan(expected=0)
        proc = self.cli('inspect', '--report', self.output / 'scan.json',
                        '--rule', 'text.same_as_base', '--language', 'ja',
                        '--limit', '2', '--offset', '2')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result['total'], 5)
        self.assertEqual([x['key'] for x in result['findings']], ['K2', 'K3'])

    def test_xlsx_formula_is_incomplete_and_trailing_format_columns_ignored(self):
        import openpyxl
        book = openpyxl.Workbook()
        sheet = book.active
        sheet.append(['id', 'en', 'ja'])
        sheet.append(['FORMULA', 'Play', '=A1'])
        sheet.cell(1, 1000).number_format = '0.00'
        book.save(self.root / 'i18n.xlsx')
        book.close()
        self.config(source='i18n.xlsx')
        report, _ = self.scan(expected=2)
        self.assertIn('input.cell', self.rules(report))
        self.assertNotIn('input.language_column', self.rules(report))

    def test_discover_does_not_write_and_only_returns_nonempty_headers(self):
        self.table([('K', 'Play', '遊ぶ')], name='i18n.csv')
        proc = self.cli('discover', '--root', self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data['tables'][0]['headers'], ['id', 'en', 'ja'])
        self.assertEqual(sorted(x.name for x in self.root.iterdir()), ['i18n.csv'])

    def test_corrupt_workbook_has_structured_incomplete_report(self):
        (self.root / 'i18n.xlsx').write_bytes(b'not a zip workbook')
        self.config(source='i18n.xlsx')
        report, _ = self.scan(expected=2)
        self.assertIn('input.read', self.rules(report))

    def test_existing_report_symlink_cannot_overwrite_project_input(self):
        source = self.table([('K', 'Play', '遊ぶ')])
        self.config()
        self.output.mkdir()
        (self.output / 'scan.json').symlink_to(source)
        before = source.read_bytes()
        proc = self.cli('scan', '--root', self.root, '--config', self.profile,
                        '--out', self.output, '--checks', 'text')
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertEqual(source.read_bytes(), before)

    def test_tmp_style_to_end_of_string_is_review_warning_not_error(self):
        self.table([('END', '<color=red>MORE', '<color=red>追加')])
        self.config()
        report, _ = self.scan(expected=0)
        self.assertTrue(any(f['rule'] == 'text.richtext' and f['severity'] == 'warning'
                            for f in report['findings']))

    def test_dotnet_unmatched_closing_brace_is_not_a_clean_result(self):
        self.table([('COUNT', 'Count {0}', '件数 {0}}')])
        self.config()
        report, _ = self.scan(expected=1)
        self.assertIn('text.parameter_syntax', self.rules(report))

    def test_concurrent_config_edit_invalidates_scan_snapshot(self):
        import contextlib
        import io
        from unittest.mock import patch
        sys.path.insert(0, str(SCRIPT.parent))
        from localization import cli, core
        self.table([('K', 'Play', '遊ぶ')])
        self.config()
        real = core.Scan.read_sources
        def concurrent_editor(scan):
            real(scan)
            self.profile.write_text(self.profile.read_text() + '\n# concurrent edit\n')
        with patch.object(core.Scan, 'read_sources', concurrent_editor):
            with contextlib.redirect_stdout(io.StringIO()):
                code = cli.main(['scan', '--root', str(self.root), '--config', str(self.profile),
                                 '--out', str(self.output), '--checks', 'text'])
        self.assertEqual(code, 2)
        report = json.loads((self.output / 'scan.json').read_text())
        self.assertFalse(report['summary']['complete'])
        self.assertIn('input.config_changed', self.rules(report))

    def test_wrong_configuration_container_yields_incomplete_json(self):
        self.table([('K', 'Play', '遊ぶ')])
        self.config()
        self.profile.write_text(self.profile.read_text().replace('schema_version = 1',
                                                               'schema_version = 1\nfonts = ["ja"]'))
        report, _ = self.scan(expected=2)
        self.assertIn('input.config', self.rules(report))


if __name__ == '__main__':
    unittest.main()
