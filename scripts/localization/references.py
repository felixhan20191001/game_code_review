"""Conservative lexical references, not a C# compiler or reachability analyser."""
from pathlib import Path
import re

from .unity import blocks, read_guid, safe_data, walk

RAW = re.compile(r'\$*("{3,})')
STRING_START = re.compile(r'(?:\$@|@\$|@|\$)?"')
WORD = re.compile(r'[A-Za-z_][A-Za-z_0-9]*')


def tokens(text):
    """Skip comments/char literals and keep conditional context on string tokens."""
    i, line, conditions = 0, 1, []
    while i < len(text):
        c = text[i]
        if c == '\n':
            line += 1; i += 1; continue
        if text.startswith('//', i):
            end = text.find('\n', i)
            i = len(text) if end < 0 else end
            continue
        if text.startswith('/*', i):
            end = text.find('*/', i + 2)
            if end < 0:
                raise ValueError('未闭合 C# 块注释')
            line += text.count('\n', i, end + 2); i = end + 2; continue
        if c == '#' and not text[text.rfind('\n', 0, i) + 1:i].strip():
            end = text.find('\n', i)
            end = len(text) if end < 0 else end
            directive = text[i:end].strip()
            if re.match(r'#if\b', directive):
                conditions.append(directive)
            elif re.match(r'#(?:else|elif)\b', directive) and conditions:
                conditions[-1] = directive
            elif directive.startswith('#endif') and conditions:
                conditions.pop()
            i = end; continue
        # Raw C# strings are opaque unsupported tokens, never scanned as code.
        raw = RAW.match(text, i)
        if raw:
            end = text.find(raw[1], i + len(raw[0]))
            if end < 0:
                raise ValueError('未闭合 C# raw string')
            yield ('dynamic' if '$' in raw[0] else 'opaque', text[i + len(raw[0]):end], line, tuple(conditions))
            end += len(raw[1]); line += text.count('\n', i, end); i = end; continue
        start = STRING_START.match(text, i)
        if start:
            prefix, start_line = start[0], line
            verbatim, interpolated = '@' in prefix, '$' in prefix
            j, value = i + len(prefix), []
            closed = False
            while j < len(text):
                if text[j] == '"':
                    if verbatim and text[j:j+2] == '""':
                        value.append('"'); j += 2; continue
                    j += 1; closed = True; break
                if text[j] == '\\' and not verbatim:
                    if j + 1 >= len(text):
                        break
                    esc = text[j + 1]
                    if esc in {'u', 'U'}:
                        size = 4 if esc == 'u' else 8
                        digits = text[j+2:j+2+size]
                        if not re.fullmatch(r'[0-9a-fA-F]{' + str(size) + '}', digits):
                            raise ValueError('无效 C# Unicode 转义')
                        value.append(chr(int(digits, 16))); j += size + 2; continue
                    if esc == 'x':
                        digits = re.match(r'[0-9a-fA-F]{1,4}', text[j+2:])
                        if not digits:
                            raise ValueError('无效 C# 十六进制转义')
                        value.append(chr(int(digits[0], 16))); j += len(digits[0]) + 2; continue
                    escapes = {'n': '\n', 'r': '\r', 't': '\t', '0': '\0', 'a': '\a',
                               'b': '\b', 'f': '\f', 'v': '\v', '"': '"', "'": "'", '\\': '\\'}
                    if esc not in escapes:
                        raise ValueError('未支持的 C# 转义：' + esc)
                    value.append(escapes[esc]); j += 2; continue
                value.append(text[j]); j += 1
            if not closed:
                raise ValueError('未闭合 C# string')
            yield ('dynamic' if interpolated else 'string', ''.join(value), start_line, tuple(conditions))
            line += text.count('\n', i, j); i = j; continue
        if c == "'":
            j = i + 1
            while j < len(text):
                if text[j] == '\\':
                    j += 2; continue
                if text[j] == "'":
                    j += 1; break
                j += 1
            line += text.count('\n', i, j); i = j; continue
        word = WORD.match(text, i)
        if word:
            yield ('identifier', word[0], line, tuple(conditions)); i += len(word[0]); continue
        if not c.isspace():
            yield ('symbol', c, line, tuple(conditions))
        i += 1


def check_references(runner):
    settings = runner.config.get('references')
    if not settings:
        runner.data['coverage']['refs'] = 'not_configured'
        runner.block('refs', '未配置引用搜索范围，未执行 Key 引用检查')
        return
    allowed = {'source_roots', 'asset_roots', 'lookup_functions', 'component_names', 'key_fields', 'namespace', 'key_trim_chars'}
    if set(settings) - allowed:
        runner.add('refs.config', 'error', '引用配置存在未知字段', technical=True)
        return
    namespace = settings.get('namespace', 'main')
    keys = {e['key'] for e in runner.entries if e['namespace'] == namespace}
    trim = settings.get('key_trim_chars', '\n\r ')
    source_files, assets = set(), set()
    for kind, suffixes, found in [('source_roots', {'.cs'}, source_files), ('asset_roots', {'.prefab', '.unity'}, assets)]:
        for name in settings.get(kind, []):
            base = (runner.root / name).resolve()
            if not base.is_dir() or (base != runner.root and runner.root not in base.parents):
                runner.add('refs.root', 'error', '引用搜索目录不存在或越出项目根', details={'path': str(base)}, technical=True)
                continue
            found.update(walk(base, suffixes))
    functions = settings.get('lookup_functions', ['I18N.T'])
    patterns = [[part for part in re.split(r'(\.)', value) if part] for value in functions]
    guids = set()
    components = set(settings.get('component_names', ['I18NText', 'I18NTextMeshPro']))

    def record(key, location, dynamic=False, conditional=(), extra=None):
        item = {'key': key, 'location': location, 'dynamic': dynamic,
                'conditional': list(conditional), 'namespace': namespace, **(extra or {})}
        runner.data['references'].append(item)
        if dynamic:
            runner.block('refs', '动态或复合 Key 未展开，须结合实际赋值复核', location=location)
        elif key.strip(trim) not in keys:
            runner.add('refs.missing', 'warning', '明确引用的 Key 未在本次翻译表中找到，实际生效需复核',
                       entry={'key': key, 'namespace': namespace}, location=location,
                       details={'conditional': list(conditional), 'lookup_key': key.strip(trim)})

    for source in sorted(source_files):
        try:
            path = runner.input(str(source))
            text = path.read_text(encoding='utf-8-sig')
            if not any(marker in text for marker in [*components, *(f.split('.')[0] for f in functions)]):
                continue
            ts = list(tokens(text))
            # Only real class declarations, not filenames or comments, identify components.
            class_names = {ts[i+1][1] for i, token in enumerate(ts[:-1]) if token[:2] == ('identifier', 'class')}
            if class_names & components:
                meta = path.with_name(path.name + '.meta')
                if meta.is_file():
                    runner.input(str(meta))
                    guid = read_guid(meta)
                    if guid:
                        guids.add(guid)
            for i, token in enumerate(ts):
                if token[0] == 'dynamic' and any(function in token[1] for function in functions):
                    record('', {'file': str(path), 'line': token[2]}, dynamic=True,
                           conditional=token[3], extra={'context': '插值或 raw 字符串中的调用尚未展开'})
                for pattern in patterns:
                    n = len(pattern)
                    if [t[1] for t in ts[i:i+n]] != pattern or i+n >= len(ts) or ts[i+n][1] != '(':
                        continue
                    arg = ts[i+n+1] if i+n+1 < len(ts) else None
                    following = ts[i+n+2] if i+n+2 < len(ts) else None
                    simple = bool(arg and arg[0] == 'string' and following and following[1] in {',', ')'})
                    record(arg[1] if simple else '', {'file': str(path), 'line': token[2]},
                           dynamic=not simple, conditional=token[3])
        except Exception as exc:
            runner.add('refs.read', 'error', f'源码引用读取未完成：{exc}', location={'file': str(source)}, technical=True)
    for asset in sorted(assets):
        try:
            path = runner.input(str(asset))
            text = path.read_text(encoding='utf-8')
            for kind, identity, body, line in blocks(text):
                if kind != 114 or not any(guid in body for guid in guids):
                    continue
                data = safe_data(body).get('MonoBehaviour', {})
                if data.get('m_Script', {}).get('guid') not in guids:
                    continue
                for field in settings.get('key_fields', ['i18nCode']):
                    key = data.get(field)
                    if isinstance(key, str) and key:
                        match = re.search(r'^\s*' + re.escape(field) + r':', body, re.M)
                        lineno = line + body.count('\n', 0, match.start()) if match else line
                        record(key, {'file': str(path), 'line': lineno, 'local_file_id': identity},
                               extra={'component_field': field})
        except Exception as exc:
            runner.add('refs.read', 'error', f'序列化引用读取未完成：{exc}', location={'file': str(asset)}, technical=True)
    if assets and not guids:
        runner.block('refs', '未定位到本地化组件脚本 GUID，资源字段引用未覆盖')
    runner.data['reference_counts'] = {'source_files': len(source_files), 'assets': len(assets),
                                       'literal': sum(not r['dynamic'] for r in runner.data['references']),
                                       'dynamic': sum(r['dynamic'] for r in runner.data['references'])}
    if any(b['check'] == 'refs' for b in runner.data['blocked']):
        runner.data['coverage']['refs'] = 'partial'
