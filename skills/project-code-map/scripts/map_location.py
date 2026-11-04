#!/usr/bin/env python3
"""Print an external code-map location without creating or modifying files."""

import argparse
import hashlib
from pathlib import Path
import re


def map_location(project_root, storage_root=None):
    project = Path(project_root).expanduser().resolve(strict=True)
    if not project.is_dir():
        raise ValueError("project root must be a directory")
    storage = (
        Path(storage_root).expanduser()
        if storage_root is not None
        else Path.home() / ".local" / "share" / "project-code-maps"
    ).resolve()
    label = re.sub(r"[^A-Za-z0-9._-]+", "-", project.name).strip(".-") or "project"
    digest = hashlib.sha256(str(project).encode("utf-8")).hexdigest()[:16]
    directory = (storage / (label + "-" + digest)).resolve()
    index = (directory / "INDEX.md").resolve()
    for path in (storage, directory, index):
        if path == project or project in path.parents:
            raise ValueError("map storage must resolve outside the project root")
    return project, directory, index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--storage-root", help="Optional external storage base")
    args = parser.parse_args()
    try:
        project, directory, index = map_location(args.project_root, args.storage_root)
    except (OSError, ValueError, RuntimeError) as error:
        parser.error(str(error))
    print("project_root: " + str(project))
    print("map_directory: " + str(directory))
    print("index_path: " + str(index))


if __name__ == "__main__":
    main()
