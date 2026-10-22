"""Unity text documents: keep local IDs; parse only relevant safe data blocks."""
import os
from pathlib import Path
import re

HEADER = re.compile(r'^--- !u!(\d+) &(-?\d+)(?: stripped)?\s*$', re.M)
IGNORED = {'.git', '.svn', 'Library', 'Temp', 'Logs', 'Obj', 'obj', 'Build', 'Builds',
           'node_modules', '.venv', 'venv', 'Plugins', 'PackageCache'}


def walk(root, suffixes):
    for directory, folders, files in os.walk(root, followlinks=False):
        folders[:] = sorted(f for f in folders if f not in IGNORED and not f.startswith('.'))
        for name in sorted(files):
            path = Path(directory) / name
            if path.suffix.lower() in suffixes:
                yield path


def blocks(text):
    matches = list(HEADER.finditer(text))
    if not matches:
        raise ValueError('不是受支持的 Unity 文本 YAML 文档')
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        yield int(match[1]), int(match[2]), text[match.end():end], text.count('\n', 0, match.end()) + 1


def safe_data(body):
    import yaml
    # CSafeLoader only constructs basic YAML values; Unity tags are document headers,
    # not arbitrary constructors. Nested explicit custom tags remain rejected.
    loader = getattr(yaml, 'CSafeLoader', yaml.SafeLoader)
    value = yaml.load(body, Loader=loader)
    if not isinstance(value, dict):
        raise ValueError('Unity 文档根不是映射')
    return value


def read_guid(path):
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            match = re.match(r'guid:\s*([0-9a-fA-F]{32})\s*$', line)
            if match:
                return match[1].lower()
    return None
