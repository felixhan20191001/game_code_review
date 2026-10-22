"""Small CLI: discovery, deterministic scan, and paginated evidence inspection."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import uuid

from .core import Scan, digest, load_config, project_directory, safe_output


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def discover(root):
    tables, errors = [], []
    table_root = root / 'Table'
    candidates = sorted({*table_root.glob('*i18n*.xlsx'), *table_root.glob('*i18n*.csv'),
                         *root.glob('*i18n*.xlsx'), *root.glob('*i18n*.csv')})
    for path in candidates:
        if path.name.startswith(('~$', '.~')):
            continue
        try:
            if path.suffix == '.xlsx':
                import openpyxl
                book = openpyxl.load_workbook(path, read_only=True, data_only=False, keep_links=False)
                try:
                    for sheet in book:
                        rows = list(sheet.iter_rows(min_row=1, max_row=2, values_only=True))
                        tables.append({'path': str(path.relative_to(root)), 'sheet': sheet.title,
                                       'headers': [v for v in rows[0] if v is not None] if rows else [],
                                       'note': '候选表头；语言生效范围须结合代码确认'})
                finally:
                    book.close()
            else:
                import csv
                with path.open(encoding='utf-8-sig', newline='') as stream:
                    headers = next(csv.reader(stream), [])
                tables.append({'path': str(path.relative_to(root)), 'sheet': '', 'headers': [v for v in headers if v]})
        except Exception as exc:
            errors.append({'file': str(path), 'error': str(exc)})
    fonts_root = root / 'Client/Assets/Game/GameRes/Fonts'
    fonts = []
    for path in sorted(fonts_root.glob('*.asset')):
        with path.open(errors='replace') as stream:
            header = ''.join(stream.readline() for _ in range(400))
        if 'm_AtlasPopulationMode:' in header:
            import re
            mode = re.search(r'm_AtlasPopulationMode:\s*(\d+)', header)
            fonts.append({'path': str(path.relative_to(root)), 'mode': 'static' if mode and mode[1] == '0' else 'dynamic_or_unknown'})
    entries = sorted((root / 'Client/Assets/Game/Scripts/I18N').glob('*.cs'))
    return {'root': str(root), 'tables': tables, 'fonts': fonts,
            'entry_sources': [str(p.relative_to(root)) for p in entries],
            'state_directory': str(project_directory(root)), 'errors': errors,
            'note': '仅发现候选；未决定必需语言、字体绑定和正式包生效分支'}


def main(argv=None):
    parser = argparse.ArgumentParser(description='只读检查翻译表、静态字体和明确的 Key 引用；不代表游戏实测')
    sub = parser.add_subparsers(dest='command', required=True)
    discovery = sub.add_parser('discover', help='发现团队常见布局中的翻译表、字体与入口候选')
    discovery.add_argument('--root', type=Path, required=True)
    scan = sub.add_parser('scan', help='按配置扫描；只向项目外写报告')
    scan.add_argument('--root', type=Path, required=True)
    scan.add_argument('--config', type=Path, required=True)
    scan.add_argument('--checks', default='text,fonts,refs')
    scan.add_argument('--out', type=Path, help='项目外输出目录，生成 scan.json；省略时创建独立批次目录')
    inspect = sub.add_parser('inspect', help='按需分页读取扫描证据')
    inspect.add_argument('--report', type=Path, required=True)
    for name in ['rule', 'key', 'language']:
        inspect.add_argument('--' + name)
    inspect.add_argument('--limit', type=int, default=20)
    inspect.add_argument('--offset', type=int, default=0)
    args = parser.parse_args(argv)
    try:
        if args.command == 'inspect':
            if args.limit < 1 or args.offset < 0:
                raise ValueError('limit 必须大于零，offset 不能为负')
            data = json.loads(args.report.read_text(encoding='utf-8'))
            items = [f for f in data['findings']
                     if all(not getattr(args, k) or f.get(k) == getattr(args, k) for k in ['rule', 'language'])
                     and (not args.key or f.get('key') == args.key or any(
                         a.get('key') == args.key for a in f.get('details', {}).get('affected', [])))]
            emit({'total': len(items), 'offset': args.offset, 'limit': args.limit,
                  'findings': items[args.offset:args.offset + args.limit]})
            return 0
        root = args.root.expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError('--root 必须是项目目录')
        if args.command == 'discover':
            result = discover(root)
            emit(result)
            return 2 if result['errors'] else 0
        checks = set(args.checks.split(','))
        if not checks or checks - {'text', 'fonts', 'refs'}:
            raise ValueError('--checks 只能包含 text,fonts,refs')
        output = safe_output(root, args.out or project_directory(root) / 'runs' /
                             (datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]))
        target = output / 'scan.json'
        if target.is_symlink() or target.resolve() == args.config.expanduser().resolve():
            raise ValueError('报告目标不能是符号链接或项目配置文件')
        try:
            config, config_hash = load_config(args.config.expanduser().resolve(), root)
        except Exception as exc:
            runner = Scan(root, {}, checks)
            runner.add('input.config', 'error', str(exc), technical=True)
        else:
            runner = Scan(root, config, checks)
            runner.data['config'] = {'path': str(args.config.expanduser().resolve()), 'sha256': config_hash}
            runner.read_sources()
            for check in ['text', 'fonts', 'refs']:
                runner.data['coverage'][check] = 'not_requested' if check not in checks else 'completed'
            if 'text' in checks:
                runner.check_text()
            if 'fonts' in checks:
                from .fonts import check_fonts
                check_fonts(runner)
            if 'refs' in checks:
                from .references import check_references
                check_references(runner)
        data = runner.finish()
        output.mkdir(parents=True, exist_ok=True)
        import tempfile
        import os
        # Atomic replacement prevents partial reports and never follows a report symlink.
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        try:
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        emit({'report': str(output / 'scan.json'), 'summary': data['summary'],
              'coverage': data['coverage'], 'exit_code': data['exit_code']})
        return data['exit_code']
    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        emit({'error': str(exc), 'exit_code': 2})
        return 2
