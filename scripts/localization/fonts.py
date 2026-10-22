"""Static TMP coverage, deliberately separate from runtime-rendering assertions."""
from collections import defaultdict
from pathlib import Path
import unicodedata

from .text import analyze
from .unity import blocks, read_guid, safe_data, walk


class FontReader:
    def __init__(self, runner):
        self.runner = runner
        self.cache = {}
        self.guid_index = None

    def resolve(self, guid):
        if self.guid_index is None:
            self.guid_index = {}
            base = self.runner.root / 'Client/Assets'
            if not base.is_dir():
                base = self.runner.root
            for meta in walk(base, {'.meta'}):
                if meta.is_symlink():
                    continue
                identifier = read_guid(meta)
                if identifier:
                    self.guid_index.setdefault(identifier, []).append(meta)
        candidates = self.guid_index.get(guid.lower(), [])
        if len(candidates) != 1:
            raise ValueError(f'字体引用 GUID 未找到或重复：{guid}')
        meta = self.runner.input(str(candidates[0]))
        return self.runner.input(str(meta)[:-5])

    def read(self, name, file_id=None, stack=()):
        path = self.runner.input(name)
        used_paths = {str(path)}
        token = (str(path), file_id)
        if token in stack:
            self.runner.add('font.fallback_cycle', 'warning', '静态回退字体存在循环，已停止重复遍历',
                            location={'file': str(path)})
            return set(), False, used_paths
        if token in self.cache:
            return self.cache[token]
        text = path.read_text(encoding='utf-8')
        docs = list(blocks(text))
        anchors = {identity: kind for kind, identity, _, _ in docs}
        candidates = []
        for kind, identity, body, line in docs:
            if kind == 114 and (file_id is None or identity == file_id):
                data = safe_data(body).get('MonoBehaviour', {})
                if 'm_CharacterTable' in data:
                    candidates.append((identity, data, line))
        if len(candidates) != 1:
            raise ValueError(f'字体文档未找到或不唯一：{path} fileID={file_id}')
        identity, data, line = candidates[0]
        if data.get('m_Version') != '1.1.0':
            raise ValueError(f'未支持的 TMP 字体结构版本：{data.get("m_Version")}')
        if data.get('m_AtlasPopulationMode') == 1:
            self.runner.block('fonts', '动态字体未做运行时补字验证', file=str(path))
            self.cache[token] = (set(), True, used_paths)
            return self.cache[token]
        if data.get('m_AtlasPopulationMode') != 0:
            raise ValueError('未知字体填充模式')
        glyphs = {g['m_Index']: g for g in data['m_GlyphTable']}
        atlases = data['m_AtlasTextures']
        characters = set()
        unknown = False
        for character in data['m_CharacterTable']:
            point, gi = character['m_Unicode'], character['m_GlyphIndex']
            if not isinstance(point, int) or point < 0 or point > 0x10FFFF or 0xD800 <= point <= 0xDFFF:
                raise ValueError('字符表包含无效 Unicode 码点')
            if gi not in glyphs:
                self.runner.add('font.invalid_glyph', 'error', '字体字符引用了不存在的字形',
                                details={'codepoint': f'U+{point:04X}', 'glyph_index': gi},
                                location={'file': str(path), 'line': line})
                continue
            index = glyphs[gi].get('m_AtlasIndex', 0)
            valid = isinstance(index, int) and 0 <= index < len(atlases)
            if valid:
                reference = atlases[index]
                valid = bool(reference.get('fileID'))
                if valid and reference.get('guid'):
                    # External texture exists; no pixel/raster validation is implied.
                    texture = self.resolve(reference['guid'])
                    if texture.suffix.lower() == '.asset':
                        types = {fid: kind for kind, fid, _, _ in blocks(texture.read_text(encoding='utf-8'))}
                        valid = types.get(reference['fileID']) == 28
                    elif texture.suffix.lower() in {'.png', '.jpg', '.jpeg', '.tga', '.psd', '.exr', '.tif', '.tiff', '.bmp', '.dds', '.webp'}:
                        valid = reference['fileID'] == 2800000
                    else:
                        raise ValueError(f'图集资源类型无法验证：{texture.suffix}')
                elif valid:
                    valid = anchors.get(reference['fileID']) == 28
            if not valid:
                self.runner.add('font.invalid_atlas', 'error', '字体字形对应的图集索引或引用无效',
                                details={'codepoint': f'U+{point:04X}', 'glyph_index': gi, 'atlas_index': index},
                                location={'file': str(path), 'line': line})
                continue
            characters.add(point)
        stack = (*stack, token)
        for reference in data.get('m_FallbackFontAssetTable') or []:
            if not reference.get('fileID'):
                continue
            target = self.resolve(reference['guid']) if reference.get('guid') else path
            points, dynamic, dependencies = self.read(str(target), reference['fileID'], stack)
            characters.update(points)
            unknown |= dynamic
            used_paths.update(dependencies)
        self.cache[token] = characters, unknown, used_paths
        return self.cache[token]


def check_fonts(runner):
    fonts = runner.config.get('fonts', {})
    if not fonts:
        runner.data['coverage']['fonts'] = 'not_configured'
        runner.block('fonts', '未配置字体资源，未执行缺字检查')
        return
    reader = FontReader(runner)
    for language, settings in fonts.items():
        try:
            if set(settings) - {'adapter', 'assets', 'require_static_coverage', 'extra_characters'}:
                raise ValueError('fonts 存在未知配置字段')
            if settings.get('adapter') != 'unity_tmp_static' or not isinstance(settings.get('assets'), list) or not settings['assets']:
                raise ValueError('字体需要 unity_tmp_static 适配器和非空 assets 列表')
            coverage, dynamic, checked_paths = set(), False, set()
            for name in settings['assets']:
                points, unknown, dependencies = reader.read(name)
                coverage.update(points)
                dynamic |= unknown
                checked_paths.update(dependencies)
            affected = defaultdict(list)
            found_language = False
            for entry in runner.entries:
                content = entry['values'].get(language)
                if not content:
                    continue
                found_language = True
                result = runner.analyses.get(id(entry), {}).get(language) or analyze(content, runner.config.get('text', {}))
                if result.font_switch or result.unsupported:
                    runner.block('fonts', '文案包含未解析的字体/样式切换或富文本，未判断其字符覆盖', entry, language)
                    continue
                for point in sorted({ord(c) for c in result.visible + settings.get('extra_characters', '')
                                     if not c.isspace() and unicodedata.category(c) not in {'Cc', 'Cf'}} - coverage):
                    if dynamic:
                        continue
                    affected[point].append({'key': entry['key'], 'namespace': entry['namespace'],
                                            'location': entry['locations'][language], 'text': content})
            if not found_language:
                runner.block('fonts', '没有可读取的对应语言文案', language=language)
            for point, occurrences in sorted(affected.items()):
                # Individual combining/variation sequences need rendering validation too.
                runner.add('font.coverage', 'error' if settings.get('require_static_coverage', False) else 'warning',
                           '指定静态字体未覆盖该字符；实际显示仍取决于完整字体链', language=language,
                           details={'character': chr(point), 'codepoint': f'U+{point:04X}',
                                    'font_paths': sorted(checked_paths), 'affected': occurrences},
                           location=occurrences[0]['location'])
        except Exception as exc:
            runner.add('font.read', 'error', f'字体检查未完成：{exc}', language=language, technical=True)
            runner.block('fonts', '字体资源或回退链未完成解析', language=language)
    if any(b['check'] == 'fonts' for b in runner.data['blocked']):
        runner.data['coverage']['fonts'] = 'partial'
