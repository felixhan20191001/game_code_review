import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parent))
import test_localization as support


class FontChecks(support.LocalizationCLI):
    # Do not re-run inherited text tests in this class.
    def font(self, name='ja.asset', chars=(('日', 1),), glyphs=(1,), mode=0, fallback=None, bad_atlas=False):
        import yaml
        data = {'MonoBehaviour': {'m_Version': '1.1.0', 'm_AtlasPopulationMode': mode,
                'm_CharacterTable': [{'m_Unicode': ord(c), 'm_GlyphIndex': g} for c, g in chars],
                'm_GlyphTable': [{'m_Index': g, 'm_AtlasIndex': 0} for g in glyphs],
                'm_AtlasTextures': [{'fileID': 999 if bad_atlas else 42}],
                'm_FallbackFontAssetTable': fallback or []}}
        p = self.root / name
        p.write_text('%YAML 1.1\n%TAG !u! tag:unity3d.com,2011:\n--- !u!114 &11400000\n' +
                     yaml.safe_dump(data, allow_unicode=True) + '\n--- !u!28 &42\nTexture2D: {}\n')
        return p

    def font_config(self, extra=''):
        self.config('''[fonts.ja]
adapter = "unity_tmp_static"
assets = ["ja.asset"]
''' + extra)

    def test_font_missing_character_reports_all_affected_keys(self):
        self.table([('A', 'One', '日本'), ('B', 'Two', '本')])
        self.font()
        self.font_config()
        data, _ = self.scan('fonts', expected=0)
        missing = [f for f in data['findings'] if f['rule'] == 'font.coverage']
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]['details']['codepoint'], 'U+672C')
        self.assertEqual([v['key'] for v in missing[0]['details']['affected']], ['A', 'B'])

    def test_broken_glyph_and_atlas_are_not_counted_as_coverage(self):
        self.table([('A', 'One', '日')])
        self.font(chars=(('日', 7),), glyphs=(1,))
        self.font_config()
        data, _ = self.scan('fonts', expected=1)
        self.assertIn('font.invalid_glyph', self.rules(data))
        self.font(bad_atlas=True)
        data, _ = self.scan('fonts', expected=1)
        self.assertIn('font.invalid_atlas', self.rules(data))

    def test_dynamic_font_is_uncovered_not_all_characters_missing(self):
        self.table([('A', 'One', '日本')])
        self.font(mode=1)
        self.font_config()
        data, _ = self.scan('fonts', expected=0)
        self.assertNotIn('font.coverage', self.rules(data))
        self.assertTrue(any(x['check'] == 'fonts' for x in data['blocked']))
        self.assertEqual(data['coverage']['fonts'], 'partial')

    def test_static_fallback_resolves_and_cycle_is_reported(self):
        self.table([('A', 'One', '日本')])
        self.font(fallback=[{'fileID': 11400000, 'guid': 'b' * 32}])
        self.font('fallback.asset', chars=(('本', 2),), glyphs=(2,),
                  fallback=[{'fileID': 11400000, 'guid': 'a' * 32}])
        (self.root / 'ja.asset.meta').write_text('guid: ' + 'a' * 32)
        (self.root / 'fallback.asset.meta').write_text('guid: ' + 'b' * 32)
        self.font_config()
        data, _ = self.scan('fonts', expected=0)
        self.assertNotIn('font.coverage', self.rules(data))
        self.assertIn('font.fallback_cycle', self.rules(data))

    def test_unknown_font_format_is_incomplete_and_font_switch_is_uncovered(self):
        self.table([('A', 'One', '<font="Other">日</font>')])
        self.font()
        self.font_config()
        data, _ = self.scan('fonts', expected=0)
        self.assertNotIn('font.coverage', self.rules(data))
        self.assertTrue(any('字体' in x['reason'] for x in data['blocked']))
        (self.root / 'ja.asset').write_bytes(b'\x00binary')
        data, _ = self.scan('fonts', expected=2)
        self.assertNotIn('font.coverage', self.rules(data))

    def test_missing_fallback_is_an_explicit_incomplete_scan(self):
        self.table([('A', 'One', '日')])
        self.font(fallback=[{'fileID': 11400000, 'guid': 'f' * 32}])
        self.font_config()
        data, _ = self.scan('fonts', expected=2)
        self.assertIn('font.read', self.rules(data))

    def test_font_exception_only_suppresses_the_named_affected_key(self):
        self.table([('A', 'One', '本'), ('B', 'Two', '本')])
        self.font()
        self.font_config('''[[exceptions]]
rule = "font.coverage"
namespace = "main"
key = "A"
language = "ja"
codepoint = "U+672C"
value = "本"
reason = "A 使用单独的运行时字体，已经确认"
''')
        data, _ = self.scan('fonts', expected=0)
        issue = next(f for f in data['findings'] if f['rule'] == 'font.coverage')
        self.assertFalse(issue['suppressed'])
        self.assertEqual([a['key'] for a in issue['details']['affected'] if not a.get('suppressed')], ['B'])

    def test_each_language_reports_only_fonts_in_its_own_chain(self):
        self.table([('A', 'One', '本', '글')], header=('id', 'en', 'ja', 'ko'))
        self.font()
        self.font('ko.asset', chars=(('한', 1),))
        self.config('''[fonts.ja]
adapter = "unity_tmp_static"
assets = ["ja.asset"]
[fonts.ko]
adapter = "unity_tmp_static"
assets = ["ko.asset"]
''', mapping='en="en", ja="ja", ko="ko"')
        data, _ = self.scan('fonts', expected=0)
        ko = next(f for f in data['findings'] if f['rule'] == 'font.coverage' and f['language'] == 'ko')
        self.assertEqual(ko['details']['font_paths'], [str(self.root.resolve() / 'ko.asset')])

    def test_atlas_anchor_must_be_a_texture_not_a_font_component(self):
        self.table([('A', 'One', '日')])
        path = self.font()
        path.write_text(path.read_text().replace('fileID: 42', 'fileID: 11400000'))
        self.font_config()
        data, _ = self.scan('fonts', expected=1)
        self.assertIn('font.invalid_atlas', self.rules(data))

    def test_inspect_key_finds_aggregated_font_evidence(self):
        self.table([('A', 'One', '本'), ('B', 'Two', '本')])
        self.font()
        self.font_config()
        self.scan('fonts', expected=0)
        proc = self.cli('inspect', '--report', self.output / 'scan.json', '--key', 'A')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        evidence = json.loads(proc.stdout)
        self.assertEqual(evidence['total'], 1)
        self.assertEqual(evidence['findings'][0]['details']['codepoint'], 'U+672C')


class ReferenceChecks(support.LocalizationCLI):
    def refs_config(self):
        self.config('''[references]
source_roots = ["Scripts"]
asset_roots = ["Assets"]
lookup_functions = ["I18N.T"]
component_names = ["I18NTextMeshPro"]
key_fields = ["i18nCode"]
''')

    def test_comments_plain_strings_dynamic_and_conditional_refs_are_distinct(self):
        self.table([('PRESENT', 'Play', '遊ぶ')])
        (self.root / 'Scripts').mkdir()
        (self.root / 'Assets').mkdir()
        (self.root / 'Scripts' / 'View.cs').write_text('''// I18N.T("COMMENT")
/* I18N.T("COMMENT2"); */
var description = "I18N.T(\\"STRING\\")";
var a = I18N.T("MISSING");
var b = I18N.T(@"PRESENT");
var c = I18N.T("PREFIX" + n);
#if DEBUG
var d = I18N.T("DEBUG_ONLY");
#endif
''')
        self.refs_config()
        data, _ = self.scan('refs', expected=0)
        missing = [f['key'] for f in data['findings'] if f['rule'] == 'refs.missing']
        self.assertEqual(missing, ['MISSING', 'DEBUG_ONLY'])
        self.assertTrue(any(r.get('dynamic') for r in data['references']))
        debug = next(r for r in data['references'] if r.get('key') == 'DEBUG_ONLY')
        self.assertTrue(debug['conditional'])

    def test_prefab_field_must_belong_to_localization_component(self):
        self.table([('PRESENT', 'Play', '遊ぶ')])
        scripts = self.root / 'Scripts'; scripts.mkdir()
        assets = self.root / 'Assets'; assets.mkdir()
        (scripts / 'I18NTextMeshPro.cs').write_text('class I18NTextMeshPro {}')
        (scripts / 'I18NTextMeshPro.cs.meta').write_text('guid: ' + 'a' * 32)
        (assets / 'view.prefab').write_text('''%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!114 &1
MonoBehaviour:
  m_Script: {fileID: 11500000, guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa, type: 3}
  i18nCode: PREFAB_MISSING
--- !u!114 &2
MonoBehaviour:
  m_Script: {fileID: 11500000, guid: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb, type: 3}
  i18nCode: OTHER_FIELD
''')
        self.refs_config()
        data, _ = self.scan('refs', expected=0)
        missing = [f for f in data['findings'] if f['rule'] == 'refs.missing']
        self.assertEqual([f['key'] for f in missing], ['PREFAB_MISSING'])
        self.assertGreater(missing[0]['location']['line'], 1)

    def test_csharp_hex_escaped_literal_resolves_to_actual_key(self):
        self.table([('A', 'Play', '遊ぶ')])
        (self.root / 'Scripts').mkdir()
        (self.root / 'Assets').mkdir()
        (self.root / 'Scripts' / 'View.cs').write_text(r'var a = I18N.T("\x41");')
        self.refs_config()
        data, _ = self.scan('refs', expected=0)
        self.assertNotIn('refs.missing', self.rules(data))
        self.assertEqual(data['references'][0]['key'], 'A')

    def test_interpolation_containing_lookup_is_explicitly_partial(self):
        self.table([('A', 'Play', '遊ぶ')])
        (self.root / 'Scripts').mkdir()
        (self.root / 'Assets').mkdir()
        (self.root / 'Scripts' / 'View.cs').write_text('var x = $"{I18N.T("MISSING")}";')
        self.refs_config()
        data, _ = self.scan('refs', expected=0)
        self.assertEqual(data['coverage']['refs'], 'partial')
        self.assertTrue(any(b['check'] == 'refs' for b in data['blocked']))

    def test_csharp_variable_length_hex_and_control_escapes_keep_values(self):
        self.table([('A', 'One', '一'), ('Л', 'Two', '二'), ('AB', 'Three', '三'),
                    ('\a\b\f\v', 'Four', '四')])
        (self.root / 'Scripts').mkdir()
        (self.root / 'Assets').mkdir()
        (self.root / 'Scripts' / 'View.cs').write_text(
            r'I18N.T("\x41"); I18N.T("\x41b"); I18N.T("\x0041B"); I18N.T("\a\b\f\v");')
        self.refs_config()
        data, _ = self.scan('refs', expected=0)
        self.assertNotIn('refs.missing', self.rules(data))
        self.assertEqual([r['key'] for r in data['references']], ['A', 'Л', 'AB', '\a\b\f\v'])


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(cls(name) for cls in (FontChecks, ReferenceChecks)
                              for name in cls.__dict__ if name.startswith('test_'))


if __name__ == '__main__':
    unittest.main()
