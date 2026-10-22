"""CLI regressions for truthful coverage and self-contained Key evidence."""
import json
import unittest

from test_localization import LocalizationCLI


class EvidenceCoverage(LocalizationCLI):
    def references(self):
        (self.root / 'Scripts').mkdir(exist_ok=True)
        (self.root / 'Assets').mkdir(exist_ok=True)
        self.config('''[references]
source_roots = ["Scripts"]
asset_roots = ["Assets"]
lookup_functions = ["I18N.T"]
component_names = ["I18NTextMeshPro"]
key_fields = ["i18nCode"]
''')

    def inspect(self, *args):
        proc = self.cli('inspect', '--report', self.output / 'scan.json', *args)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def test_unreadable_table_invalidates_all_dependent_checks(self):
        self.references()
        data, _ = self.scan('text,refs', expected=2)
        self.assertFalse(data['summary']['complete'])
        self.assertEqual(data['coverage'], {'text': 'partial', 'fonts': 'not_requested', 'refs': 'partial'})

    def test_ref_parse_failure_does_not_invalidate_completed_text(self):
        self.table([('A', 'Play', '遊ぶ')])
        self.references()
        (self.root / 'Scripts/Broken.cs').write_text('I18N.T("unfinished')
        data, _ = self.scan('text,refs', expected=2)
        self.assertEqual(data['coverage']['refs'], 'partial')
        self.assertEqual(data['coverage']['text'], 'completed')

    def test_missing_reference_root_is_partial(self):
        self.table([('A', 'Play', '遊ぶ')])
        self.references()
        (self.root / 'Scripts').rmdir()
        data, _ = self.scan('refs', expected=2)
        self.assertEqual(data['coverage']['refs'], 'partial')

    def test_invalid_config_has_explicit_coverage(self):
        self.profile.write_text('schema_version = 999')
        data, _ = self.scan('refs', expected=2)
        self.assertEqual(data['coverage'], {'text': 'not_requested', 'fonts': 'not_requested', 'refs': 'partial'})

    def test_rule_errors_do_not_mean_execution_failed(self):
        self.table([('A', 'Play', '')])
        self.config()
        data, _ = self.scan(expected=1)
        self.assertTrue(data['summary']['complete'])
        self.assertEqual(data['coverage']['text'], 'completed')

    def test_missing_language_column_is_partial_without_technical_failure(self):
        self.table([('A', 'Play')], header=('id', 'en'))
        self.config()
        data, _ = self.scan(expected=1)
        self.assertTrue(data['summary']['complete'])
        self.assertEqual(data['coverage']['text'], 'partial')

    def test_unconfigured_checks_remain_distinct_from_partial(self):
        self.table([('A', 'Play', '遊ぶ')])
        self.config()
        data, _ = self.scan('text,fonts,refs', expected=0)
        self.assertEqual(data['coverage'], {'text': 'completed', 'fonts': 'not_configured', 'refs': 'not_configured'})

    def test_key_inspect_returns_entries_and_source_context_even_without_findings(self):
        self.table([('A', 'Play', '遊ぶ')])
        self.references()
        (self.root / 'Scripts/View.cs').write_text('class View {\n void Show() {\n I18N.T("A");\n }\n}\n')
        self.scan('text,refs', expected=0)
        result = self.inspect('--key', 'A')
        self.assertEqual(result['total'], 0)
        evidence = result.get('evidence', {})
        self.assertEqual(evidence.get('totals', {}).get('entries'), 1)
        self.assertEqual(evidence['entries'][0]['locations']['ja']['cell'], 'C2')
        ref = evidence['references'][0]
        self.assertEqual(ref['location']['line'], 3)
        self.assertIn('void Show()', ref['context']['text'])

    def test_reference_pages_keep_totals_and_language_filter_keeps_shared_refs(self):
        self.table([('A', 'Play', '遊ぶ'), ('B', 'Exit', '終了')])
        self.references()
        (self.root / 'Scripts/View.cs').write_text('\n'.join(['I18N.T("A");'] * 3 + ['I18N.T("B");']))
        self.scan('text,refs', expected=0)
        result = self.inspect('--key', 'A', '--language', 'ja', '--rule', 'text.empty', '--offset', 1, '--limit', 1)
        evidence = result.get('evidence', {})
        self.assertEqual(evidence.get('totals', {}).get('references'), 3)
        self.assertEqual(len(evidence['references']), 1)
        self.assertEqual(evidence['references'][0]['location']['line'], 2)

    def test_unresolved_dynamic_reference_is_global_blocker_not_key_evidence(self):
        self.table([('A', 'Play', '遊ぶ')])
        self.references()
        (self.root / 'Scripts/View.cs').write_text('I18N.T(prefix + index);')
        self.scan('refs', expected=0)
        result = self.inspect('--key', 'A')
        evidence = result.get('evidence', {})
        self.assertEqual(evidence.get('totals', {}).get('references'), 0)
        self.assertEqual(evidence['totals']['blocked'], 0)
        self.assertEqual(evidence['totals']['global_blocked'], 1)

    def test_prefab_evidence_has_hierarchy_flags_script_and_font(self):
        self.table([('A', 'Play', '遊ぶ')])
        self.references()
        (self.root / 'Scripts/I18NTextMeshPro.cs').write_text('class I18NTextMeshPro {}')
        (self.root / 'Scripts/I18NTextMeshPro.cs.meta').write_text('guid: ' + 'a' * 32)
        (self.root / 'Assets/View.prefab').write_text('''%YAML 1.1
--- !u!1 &10
GameObject:
  m_Name: Panel
  m_IsActive: 0
--- !u!224 &11
RectTransform:
  m_GameObject: {fileID: 10}
  m_Father: {fileID: 0}
--- !u!1 &20
GameObject:
  m_Name: Title
  m_IsActive: 1
--- !u!224 &21
RectTransform:
  m_GameObject: {fileID: 20}
  m_Father: {fileID: 11}
--- !u!114 &30
MonoBehaviour:
  m_GameObject: {fileID: 20}
  m_Enabled: 1
  m_Script: {fileID: 11500000, guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa, type: 3}
  m_fontAsset: {fileID: 11400000, guid: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb, type: 2}
  i18nCode: A
''')
        self.scan('refs', expected=0)
        result = self.inspect('--key', 'A')
        refs = result.get('evidence', {}).get('references', [])
        self.assertEqual(len(refs), 1)
        ref = refs[0]
        self.assertEqual(ref['object_path'], 'Panel/Title')
        self.assertEqual([o['active_self'] for o in ref['hierarchy']], [0, 1])
        self.assertEqual(ref['component_enabled'], 1)
        self.assertEqual(ref['script_guid'], 'a' * 32)
        self.assertEqual(ref['font']['guid'], 'b' * 32)

    def test_legacy_report_and_namespace_filter(self):
        self.output.mkdir()
        (self.output / 'scan.json').write_text(json.dumps({'findings': [
            {'rule': 'refs.missing', 'key': 'A', 'namespace': 'main'},
            {'rule': 'refs.missing', 'key': 'A', 'namespace': 'other'}]}))
        result = self.inspect('--key', 'A', '--namespace', 'main')
        self.assertEqual(result['total'], 1)
        self.assertFalse(result['evidence']['entries_available'])

    def test_yaml_boolean_object_names_keep_spelling_and_missing_parents_are_unknown(self):
        self.table([('A', 'Play', '遊ぶ')])
        self.references()
        (self.root / 'Scripts/I18NTextMeshPro.cs').write_text('class I18NTextMeshPro {}')
        (self.root / 'Scripts/I18NTextMeshPro.cs.meta').write_text('guid: ' + 'a' * 32)
        path = self.root / 'Assets/View.prefab'
        fixture = '''%YAML 1.1
--- !u!1 &10
GameObject:
  m_Name: No
  m_IsActive: 0
--- !u!224 &11
RectTransform:
  m_GameObject: {fileID: 10}
  m_Father: {fileID: PARENT}
--- !u!114 &30
MonoBehaviour:
  m_GameObject: {fileID: 10}
  m_Script: {fileID: 11500000, guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa, type: 3}
  i18nCode: A
'''
        for parent, complete in [('0', True), ('99', False), ('11', False)]:
            with self.subTest(parent=parent):
                path.write_text(fixture.replace('PARENT', parent))
                self.scan('refs', expected=0)
                ref = self.inspect('--key', 'A')['evidence']['references'][0]
                self.assertEqual(ref['object_path'], 'No')
                self.assertEqual(ref['hierarchy_complete'], complete)

    def test_normalized_reference_key_joins_to_table_without_changing_raw_key(self):
        self.table([('A', 'Play', '遊ぶ')])
        self.references()
        (self.root / 'Scripts/View.cs').write_text('I18N.T(" A ");')
        self.scan('refs', expected=0)
        e = self.inspect('--key', 'A', '--namespace', 'main')['evidence']
        self.assertEqual(e['totals']['references'], 1)
        self.assertEqual(e['references'][0]['key'], ' A ')
        self.assertEqual(e['totals']['entries'], 1)
        other = self.inspect('--key', 'A', '--namespace', 'other')['evidence']
        self.assertEqual(other['totals']['references'], 0)
        self.assertEqual(other['totals']['entries'], 0)

    def test_font_on_sibling_component_is_a_candidate_only_on_same_game_object(self):
        self.table([('A', 'Play', '遊ぶ')])
        self.references()
        (self.root / 'Scripts/I18NTextMeshPro.cs').write_text('class I18NTextMeshPro {}')
        (self.root / 'Scripts/I18NTextMeshPro.cs.meta').write_text('guid: ' + 'a' * 32)
        (self.root / 'Assets/View.prefab').write_text('''%YAML 1.1
--- !u!1 &10
GameObject:
  m_Name: Title
--- !u!114 &20
MonoBehaviour:
  m_GameObject: {fileID: 10}
  m_Script: {fileID: 11500000, guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa, type: 3}
  i18nCode: A
--- !u!114 &30
MonoBehaviour:
  m_GameObject: {fileID: 10}
  m_fontAsset: {fileID: 11400000, guid: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb, type: 2}
--- !u!114 &40
MonoBehaviour:
  m_GameObject: {fileID: 99}
  m_fontAsset: {fileID: 11400000, guid: cccccccccccccccccccccccccccccccc, type: 2}
''')
        self.scan('refs', expected=0)
        ref = self.inspect('--key', 'A')['evidence']['references'][0]
        self.assertIsNone(ref['font'])
        self.assertEqual(ref.get('font_candidates'), [{'local_file_id': 30,
            'font': {'fileID': 11400000, 'guid': 'b' * 32, 'type': 2}}])


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(EvidenceCoverage(name) for name in EvidenceCoverage.__dict__
                              if name.startswith('test_'))
