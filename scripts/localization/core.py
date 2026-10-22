"""Configuration, provenance-preserving readers and scan results."""
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import tomllib

from .text import check_entry

VERSION = '1.1.0'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def project_directory(root):
    name = re.sub(r'[^A-Za-z0-9._-]+', '-', root.name).strip('.-') or 'project'
    key = hashlib.sha256(str(root).encode()).hexdigest()[:16]
    return Path.home() / '.local/share/game-code-review/localization' / f'{name}-{key}'


def column_name(index):
    result = ''
    while index:
        index, rem = divmod(index - 1, 26)
        result = chr(65 + rem) + result
    return result


def safe_output(root, output):
    output = output.expanduser().resolve()
    if output == root or root in output.parents:
        raise ValueError('报告和配置必须位于被检项目之外')
    return output


def load_config(path, root):
    payload = path.read_bytes()
    config = tomllib.loads(payload.decode('utf-8'))
    allowed = {'schema_version', 'project_id', 'root', 'base_language', 'required_languages',
               'sources', 'text', 'fonts', 'references', 'exceptions'}
    if set(config) - allowed:
        raise ValueError('未知配置字段：' + ', '.join(sorted(set(config) - allowed)))
    for name in ('text', 'fonts', 'references'):
        if name in config and not isinstance(config[name], dict):
            raise ValueError(f'{name} 必须是配置表，不是数组或字符串')
    if not isinstance(config.get('exceptions', []), list):
        raise ValueError('exceptions 必须是配置表数组')
    if config.get('schema_version') != 1:
        raise ValueError('schema_version 必须为 1')
    if 'root' in config and Path(config['root']).expanduser().resolve() != root:
        raise ValueError('配置所属项目根与 --root 不一致')
    languages = config.get('required_languages')
    if not isinstance(languages, list) or not languages or any(not isinstance(x, str) or not x for x in languages):
        raise ValueError('required_languages 必须为非空语言列表')
    if len(set(languages)) != len(languages) or config.get('base_language') not in languages:
        raise ValueError('必需语言不能重复，且必须包含基准语言')
    if not isinstance(config.get('sources'), list) or not config['sources']:
        raise ValueError('至少配置一个 sources')
    for source in config['sources']:
        if not isinstance(source, dict):
            raise ValueError('sources 的每一项必须是配置表')
        permitted = {'path', 'sheet', 'namespace', 'header_row', 'data_start_row', 'key_column',
                     'language_columns', 'skip_key_prefixes', 'encoding', 'delimiter'}
        if set(source) - permitted:
            raise ValueError('sources 存在未知字段')
        if not isinstance(source.get('path'), str) or not isinstance(source.get('language_columns'), dict):
            raise ValueError('sources 需要 path 和 language_columns')
        if source.get('header_row', 1) < 1 or source.get('data_start_row', 2) <= source.get('header_row', 1):
            raise ValueError('表头行或数据起始行无效')
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in source['language_columns'].items()):
            raise ValueError('language_columns 必须是语言到列名的映射')
    options = config.get('text', {})
    if not isinstance(options.get('placeholder_styles', []), list):
        raise ValueError('placeholder_styles 必须是列表')
    if 'literal_backslash_n_is_newline' in options and not isinstance(options['literal_backslash_n_is_newline'], bool):
        raise ValueError('literal_backslash_n_is_newline 必须为布尔值')
    if set(options) - {'placeholder_styles', 'rich_text_profile', 'literal_backslash_n_is_newline'}:
        raise ValueError('text 存在未知字段')
    if set(options.get('placeholder_styles', ['percent_named'])) - {'percent_named', 'dotnet'}:
        raise ValueError('未支持的占位符语法')
    if options.get('rich_text_profile', 'unity_tmp_3') not in {'plain', 'unity_tmp_3'}:
        raise ValueError('未支持的富文本语法')
    for exception in config.get('exceptions', []):
        if not isinstance(exception, dict):
            raise ValueError('exceptions 的每一项必须是配置表')
        if not all(isinstance(exception.get(k), str) and exception[k] for k in
                   ['rule', 'namespace', 'key', 'language', 'reason']):
            raise ValueError('例外需要精确 rule/namespace/key/language 和 reason')
        if set(exception) - {'rule', 'namespace', 'key', 'language', 'reason', 'value', 'codepoint'}:
            raise ValueError('exceptions 存在未知字段')
    refs = config.get('references', {})
    for field in ('source_roots', 'asset_roots', 'lookup_functions', 'component_names', 'key_fields'):
        if field in refs and (not isinstance(refs[field], list) or any(not isinstance(x, str) or not x for x in refs[field])):
            raise ValueError(f'references.{field} 必须是非空字符串组成的列表')
    if 'key_trim_chars' in refs and not isinstance(refs['key_trim_chars'], str):
        raise ValueError('key_trim_chars 必须为字符串')
    for settings in config.get('fonts', {}).values():
        if not isinstance(settings, dict):
            raise ValueError('每种语言的字体配置必须是配置表')
        if not isinstance(settings.get('require_static_coverage', False), bool):
            raise ValueError('require_static_coverage 必须为布尔值')
        if not isinstance(settings.get('extra_characters', ''), str):
            raise ValueError('extra_characters 必须是字符串')
    return config, hashlib.sha256(payload).hexdigest()


class Scan:
    def __init__(self, root, config, checks):
        self.root, self.config, self.checks = root, config, checks
        self.entries = []
        self.analyses = {}
        self.data = {'schema_version': 1, 'tool_version': VERSION, 'root': str(root),
                     'started_at': datetime.now(timezone.utc).isoformat(), 'inputs': {},
                     'findings': [], 'blocked': [], 'coverage': {
                         check: 'pending' if check in checks else 'not_requested'
                         for check in ('text', 'fonts', 'refs')}, 'references': []}
        self.incomplete = False

    def input(self, name):
        path = (self.root / name).resolve()
        if path != self.root and self.root not in path.parents:
            raise ValueError(f'输入路径越出项目根：{name}')
        if not path.is_file():
            raise FileNotFoundError(str(path))
        if str(path) not in self.data['inputs']:
            self.data['inputs'][str(path)] = digest(path)
        return path

    def add(self, rule, severity, message, entry=None, language='', details=None, location=None, technical=False):
        if technical:
            self.incomplete = True
        entry = entry or {}
        finding = {'rule': rule, 'severity': severity, 'message': message,
                   'evidence_kind': 'execution' if technical else 'static_data',
                   'namespace': entry.get('namespace', ''), 'key': entry.get('key', ''),
                   'language': language, 'location': location or entry.get('locations', {}).get(language, entry.get('key_location', {})),
                   'base_location': entry.get('locations', {}).get(self.config.get('base_language'), {}),
                   'base_text': entry.get('values', {}).get(self.config.get('base_language')),
                   'text': entry.get('values', {}).get(language), 'details': details or {}, 'suppressed': False}
        identity = {k: v for k, v in finding.items() if k not in {'message', 'suppressed'}}
        finding['fingerprint'] = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]
        self.data['findings'].append(finding)

    def block(self, check, reason, entry=None, language='', technical=False, **details):
        if technical:
            self.incomplete = True
        self.data['blocked'].append({'check': check, 'reason': reason,
                                     'key': (entry or {}).get('key', ''), 'language': language,
                                     'namespace': (entry or {}).get('namespace', ''),
                                     'location': (entry or {}).get('key_location', {}), **details})

    def read_sources(self):
        for source in self.config['sources']:
            try:
                path = self.input(source['path'])
                if path.suffix.lower() == '.csv':
                    with path.open(encoding=source.get('encoding', 'utf-8-sig'), newline='') as stream:
                        reader = csv.reader(stream, delimiter=source.get('delimiter', ','))
                        self.read_rows(path, '', ((i, [(v, '') for v in row]) for i, row in enumerate(reader, 1)), source)
                elif path.suffix.lower() == '.xlsx':
                    import openpyxl
                    book = openpyxl.load_workbook(path, read_only=True, data_only=False, keep_links=False)
                    try:
                        sheet = book[source['sheet']] if source.get('sheet') else book.worksheets[0]
                        # reset_dimensions avoids truncation when producer dimensions are wrong.
                        sheet.reset_dimensions()
                        rows = ((i, [(c.value, c.data_type) for c in row]) for i, row in enumerate(sheet.iter_rows(), 1))
                        self.read_rows(path, sheet.title, rows, source)
                    finally:
                        book.close()
                else:
                    raise ValueError('首版仅支持 .xlsx/.csv')
            except Exception as exc:
                self.add('input.read', 'error', f'翻译文件未完成读取：{exc}',
                         location={'file': str(self.root / source.get('path', ''))}, technical=True)

    def read_rows(self, path, sheet, rows, source):
        header_row, start = source.get('header_row', 1), source.get('data_start_row', 2)
        columns, found_header, any_row = {}, False, False
        def loc(row, index):
            return {'file': str(path), 'sheet': sheet, 'row': row, 'column': index + 1,
                    'cell': column_name(index + 1) + str(row)}
        for row_number, cells in rows:
            if row_number == header_row:
                found_header = True
                header = [v for v, _ in cells]
                relevant = [source.get('key_column', 'id'), *source['language_columns'].values()]
                for name in relevant:
                    matches = [i for i, value in enumerate(header) if value == name]
                    if len(matches) > 1:
                        raise ValueError(f'列名重复：{name}')
                    if matches:
                        columns[name] = matches[0]
                key_column = source.get('key_column', 'id')
                if key_column not in columns:
                    raise ValueError('缺少 Key 列：' + key_column)
                for lang in sorted(set(self.config['required_languages']) | set(source['language_columns'])):
                    name = source['language_columns'].get(lang)
                    if name not in columns:
                        self.add('input.language_column', 'error', '缺少配置的语言列', language=lang,
                                 location={'file': str(path), 'sheet': sheet, 'row': header_row}, details={'column': name})
                        self.block('text', '语言列缺失，未逐格检查该语言', language=lang, file=str(path))
                continue
            if row_number < start or not found_header:
                continue
            def cell(index):
                return cells[index] if index < len(cells) else (None, '')
            ki = columns[source.get('key_column', 'id')]
            key, dtype = cell(ki)
            mapped = {lang: columns[name] for lang, name in source['language_columns'].items() if name in columns}
            if key is None and all(cell(i)[0] in (None, '') for i in mapped.values()):
                continue
            if isinstance(key, str) and any(key.startswith(p) for p in source.get('skip_key_prefixes', ['#'])):
                continue
            any_row = True
            if not isinstance(key, str) or not key.strip() or dtype in {'f', 'e'}:
                self.add('input.key', 'error', 'Key 为空、非文本或为公式/错误值', location=loc(row_number, ki), technical=True)
                continue
            entry = {'key': key, 'namespace': source.get('namespace', 'main'),
                     'key_location': loc(row_number, ki), 'locations': {}, 'values': {}}
            for lang, index in mapped.items():
                value, dtype = cell(index)
                entry['locations'][lang] = loc(row_number, index)
                if dtype in {'f', 'e'} or (value is not None and not isinstance(value, str)):
                    entry['values'][lang] = None
                    self.add('input.cell', 'error', '文案为公式、错误值或非文本，无法可靠检查', entry, lang,
                             {'value': str(value)}, technical=True)
                    self.block('text', '单元格不可解析', entry, lang)
                else:
                    entry['values'][lang] = value if value is not None else ''
            self.entries.append(entry)
        if not found_header or not any_row:
            raise ValueError('未找到有效表头或数据记录')

    def check_text(self):
        groups, trimmed = defaultdict(list), defaultdict(list)
        for entry in self.entries:
            key, namespace = entry['key'], entry['namespace']
            groups[(namespace, key)].append(entry)
            trimmed[(namespace, key.strip())].append(entry)
            if key != key.strip() or any(ord(c) < 32 or c in '\ufeff\u200b' for c in key):
                self.add('key.whitespace', 'warning', 'Key 包含首尾空白或不可见字符', entry,
                         details={'raw_key': key})
            self.analyses[id(entry)] = check_entry(entry, self.config['base_language'], self.config.get('text', {}), self.add, self.block)
        for entries in groups.values():
            if len(entries) > 1:
                self.add('key.duplicate', 'error', '同一命名空间中的 Key 重复', entries[0],
                         details={'locations': [e['key_location'] for e in entries]})
        for entries in trimmed.values():
            if len({e['key'] for e in entries}) > 1:
                self.add('key.trim_collision', 'warning', '移除首尾空白后多个 Key 相同，请核对查找时的处理', entries[0],
                         details={'keys': [e['key'] for e in entries]})

    def finish(self):
        snapshot = self.data.get('config')
        if snapshot:
            try:
                unchanged = digest(Path(snapshot['path'])) == snapshot['sha256']
            except OSError:
                unchanged = False
            if not unchanged:
                self.add('input.config_changed', 'error', '配置在扫描中变化，本轮结果不是一致快照',
                         location={'file': snapshot['path']}, technical=True)
        for path, before in self.data['inputs'].copy().items():
            try:
                unchanged = digest(Path(path)) == before
            except OSError:
                unchanged = False
            if not unchanged:
                self.add('input.changed', 'error', '输入在扫描中发生变化，本轮不能视为完整快照', location={'file': path}, technical=True)
        # Completion and coverage are different: rule errors do not imply failed
        # execution, while failed inputs and unsupported portions reduce coverage.
        affected = {b['check'] for b in self.data['blocked']}
        for finding in self.data['findings']:
            if finding['evidence_kind'] == 'execution':
                prefix = finding['rule'].split('.')[0]
                affected.update({'refs'} if prefix == 'refs' else
                                {'fonts'} if prefix == 'font' else self.checks)
        for check in self.checks:
            state = self.data['coverage'][check]
            if state == 'pending' or (check in affected and state != 'not_configured'):
                self.data['coverage'][check] = 'partial'
        self.data['entries'] = self.entries
        for finding in self.data['findings']:
            if finding['evidence_kind'] == 'execution':
                continue
            if finding['rule'] == 'font.coverage':
                # An exception for one Key must not hide other affected Keys in a
                # grouped character finding. Keep every occurrence and its decision.
                for occurrence in finding['details']['affected']:
                    for exception in self.config.get('exceptions', []):
                        expected = {'rule': finding['rule'], 'language': finding['language'],
                                    'namespace': occurrence['namespace'], 'key': occurrence['key']}
                        if not all(exception[k] == v for k, v in expected.items()):
                            continue
                        if 'value' in exception and exception['value'] != occurrence['text']:
                            continue
                        if 'codepoint' in exception and exception['codepoint'] != finding['details']['codepoint']:
                            continue
                        occurrence.update(suppressed=True, suppression_reason=exception['reason'])
                        break
                finding['suppressed'] = all(a.get('suppressed', False) for a in finding['details']['affected'])
                if finding['suppressed']:
                    finding['suppression_reason'] = '全部关联文案均有精确例外，详见 affected'
                continue
            for exception in self.config.get('exceptions', []):
                if all(finding.get(k) == exception[k] for k in ['rule', 'namespace', 'key', 'language']):
                    if 'value' in exception and finding['text'] != exception['value']:
                        continue
                    if 'codepoint' in exception and finding['details'].get('codepoint') != exception['codepoint']:
                        continue
                    finding.update(suppressed=True, suppression_reason=exception['reason'])
                    break
        counts = Counter(f['severity'] for f in self.data['findings'] if not f['suppressed'])
        self.data['summary'] = {'records': len(self.entries), 'languages': sorted({l for e in self.entries for l in e['values']}),
                                'errors': counts['error'], 'warnings': counts['warning'],
                                'suppressed': sum(f['suppressed'] for f in self.data['findings']),
                                'complete': not self.incomplete, 'blocked': len(self.data['blocked']),
                                'by_rule': dict(Counter(f['rule'] for f in self.data['findings'] if not f['suppressed']))}
        self.data['exit_code'] = 2 if self.incomplete else (1 if counts['error'] else 0)
        return self.data
