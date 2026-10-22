"""Literal/parameter/TMP analysis shared by text and glyph checks."""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import re
import unicodedata

PERCENT = re.compile(r'%[A-Za-z_][A-Za-z_0-9]*%')
TAG = re.compile(r'<(/?)(#[0-9a-fA-F]{3,8}|[A-Za-z][A-Za-z0-9-]*)([^<>]*)>')
PAIRED = set('b i u s color size mark sub sup link align font style nobr lowercase uppercase smallcaps allcaps cspace mspace indent line-indent margin margin-left margin-right width voffset rotate gradient strikethrough'.split())
SINGLE = {'sprite', 'br', 'space', 'pos', 'page', 'quad', 'line-height', 'alpha'}


@dataclass
class Analysis:
    visible: str = ''
    parameters: Counter = field(default_factory=Counter)
    formats: Counter = field(default_factory=Counter)
    identities: Counter = field(default_factory=Counter)
    issues: list = field(default_factory=list)
    font_switch: bool = False
    unsupported: bool = False


def rich_text(content, profile):
    result = Analysis()
    if profile == 'plain':
        result.visible = content
        return result
    counts = Counter()
    chunks, offset = [], 0
    while offset < len(content):
        match = TAG.search(content, offset)
        if not match:
            chunks.append(content[offset:])
            break
        chunks.append(content[offset:match.start()])
        closing, tag, args = match.groups()
        tag = tag.lower()
        offset = match.end()
        if tag == 'noparse' and not closing:
            end = re.search(r'</noparse\s*>', content[offset:], re.I)
            if not end:
                chunks.append(content[offset:])
                result.issues.append(('text.richtext', 'noparse 标签未闭合', {'offset': match.start()}))
                break
            chunks.append(content[offset:offset + end.start()])
            offset += end.end()
            continue
        if tag.startswith('#'):
            tag = 'color'
        if tag not in PAIRED | SINGLE:
            chunks.append(match.group())
            result.unsupported = True
            result.issues.append(('text.richtext_unknown', '存在未支持的富文本写法，需复核', {'tag': match.group(), 'offset': match.start()}))
            continue
        if tag in SINGLE:
            if closing:
                result.issues.append(('text.richtext', '独立标签存在多余关闭标签', {'tag': tag, 'offset': match.start()}))
            if tag == 'br':
                chunks.append('\n')
        elif closing:
            if counts[tag] <= 0:
                result.issues.append(('text.richtext', '标签关闭时没有对应的开启标签', {'tag': tag, 'offset': match.start()}))
            else:
                counts[tag] -= 1
        else:
            counts[tag] += 1
        if not closing and tag in {'link', 'font', 'style', 'sprite'}:
            if tag == 'sprite':
                identifiers = re.findall(r'(?:index|name)\s*=\s*(?:"[^"]*"|\x27[^\x27]*\x27|[^\s/>]+)', args)
                asset = re.match(r'\s*=\s*("[^"]*"|\x27[^\x27]*\x27|[^\s/>]+)', args)
                identity = (asset.group(1) if asset else '') + ' ' + ' '.join(identifiers)
            else:
                value = re.match(r'\s*=\s*(?:"([^"]*)"|\x27([^\x27]*)\x27|([^\s/>]+))', args)
                identity = next((v for v in value.groups() if v is not None), '') if value else args.strip()
            result.identities[f'{tag}:{identity.strip()}'] += 1
            if tag in {'font', 'style'}:
                result.font_switch = True
    for tag, count in sorted(counts.items()):
        if count:
            result.issues.append(('text.richtext', '样式未显式闭合，可能刻意作用到文案结尾，需复核',
                                  {'tag': tag, 'count': count, 'style_to_end': True}))
    result.visible = ''.join(chunks)
    return result


def analyze(content, options):
    result = rich_text(content, options.get('rich_text_profile', 'unity_tmp_3'))
    styles = options.get('placeholder_styles', ['percent_named'])
    # Parameter substitution happens before TMP rendering, so include attributes/noparse.
    if 'percent_named' in styles:
        result.parameters.update(PERCENT.findall(content))
        result.visible = PERCENT.sub('', result.visible)
    if 'dotnet' in styles:
        def parse(value, collect=False):
            output, i = [], 0
            while i < len(value):
                if value[i:i + 2] in {'{{', '}}'}:
                    output.append(value[i]); i += 2; continue
                if value[i] == '{':
                    end = value.find('}', i + 1)
                    token = value[i + 1:end] if end >= 0 else ''
                    m = re.fullmatch(r'(\d+)(?:,\s*-?\d+)?(?::([^{}]*))?', token)
                    if m:
                        if collect:
                            result.parameters['{' + m.group(1) + '}'] += 1
                            result.formats[(m.group(1), m.group(2) or '')] += 1
                        i = end + 1; continue
                    if collect:
                        result.issues.append(('text.parameter_syntax', '存在无法解析的花括号参数写法', {'offset': i}))
                elif value[i] == '}' and collect:
                    result.issues.append(('text.parameter_syntax', '存在未转义的多余右花括号', {'offset': i}))
                output.append(value[i]); i += 1
            return ''.join(output)
        parse(content, collect=True)
        result.visible = parse(result.visible)
    if options.get('literal_backslash_n_is_newline', False):
        result.visible = result.visible.replace('\\n', '\n')
    return result


def check_entry(entry, base, options, add, block):
    values = entry['values']
    analyses = {}
    for language, content in values.items():
        if content is None:
            continue
        if not content.strip():
            add('text.empty', 'error', '翻译内容为空', entry, language)
            continue
        result = analyze(content, options)
        analyses[language] = result
        for rule, message, details in result.issues:
            add(rule, 'error' if (rule == 'text.richtext' and not details.get('style_to_end')) or rule == 'text.parameter_syntax' else 'warning',
                message, entry, language, details)
        controls, suspicious = defaultdict(list), defaultdict(list)
        for offset, char in enumerate(content):
            if unicodedata.category(char) == 'Cc' and char not in '\n\r\t':
                controls[char].append(offset)
            elif char in '\ufeff\u200b\u00a0':
                suspicious[char].append(offset)
        for chars, severity, rule in [(controls, 'error', 'text.control'), (suspicious, 'warning', 'text.invisible')]:
            for char, positions in chars.items():
                add(rule, severity, '存在控制字符' if severity == 'error' else '存在需复核的不可见字符',
                    entry, language, {'codepoint': f'U+{ord(char):04X}', 'positions': positions,
                                      'context': content[max(0, positions[0]-12):positions[0]+13]})
        if re.search(r'\\{2,}[nr]|\\[nrt]\\[nrt]', content):
            add('text.escape', 'warning', '存在双重或连续转义，请核对实际换行处理', entry, language)
        if not result.visible.strip() and not result.parameters and not result.identities:
            add('text.invisible_only', 'warning', '文案可能没有可显示内容', entry, language)
    reference = analyses.get(base)
    if not reference:
        block('text.comparison', '基准文案缺失或不可读取，未比较目标语言', entry)
        return analyses
    for language, target in analyses.items():
        if language == base:
            continue
        missing = reference.parameters - target.parameters
        extra = target.parameters - reference.parameters
        if missing or extra:
            add('text.parameters', 'error', '翻译中的文字参数与基准语言不一致', entry, language,
                {'missing': dict(missing), 'extra': dict(extra)})
        elif reference.formats != target.formats:
            add('text.parameter_format', 'warning', '参数格式说明不同，请核对数字等展示格式', entry, language)
        if reference.identities != target.identities:
            add('text.richtext_identity', 'error', '链接、图片或字体等关键标签标识与基准语言不同', entry, language,
                {'missing': dict(reference.identities - target.identities),
                 'extra': dict(target.identities - reference.identities)})
        if values[base] == values[language] and any(c.isalpha() for c in target.visible):
            add('text.same_as_base', 'warning', '与基准语言完全相同，需确认是否为合法同词或品牌名', entry, language)
    return analyses
