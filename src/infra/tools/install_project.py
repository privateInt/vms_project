#!/usr/bin/env python3
"""Install a verified starter package. Existing conflicting files are never overwritten."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sys


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reject_symlinks(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError(f'Symlink is not allowed in installation paths: {part}')


def install(source, target, apply=False):
    reject_symlinks(target)
    manifest = json.loads((source / 'project-manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format_version') != 1 or not isinstance(manifest.get('files'), dict):
        raise ValueError('Unsupported package manifest')
    files = dict(manifest['files'])
    files['project-manifest.json'] = digest(source / 'project-manifest.json')
    additions, identical, conflicts = [], [], []
    for name, expected in sorted(files.items()):
        rel = PurePosixPath(name)
        if rel.is_absolute() or '..' in rel.parts or '\\' in name or str(rel) != name:
            raise ValueError('Unsafe manifest path')
        src, dst = source / name, target / name
        reject_symlinks(src)
        reject_symlinks(dst)
        if not src.is_file() or digest(src) != expected:
            raise ValueError(f'Package integrity check failed: {name}')
        for parent in dst.parents:
            if parent.exists() and not parent.is_dir():
                raise ValueError(f'Parent path is not a directory: {parent}')
        if dst.exists():
            if dst.is_file() and digest(dst) == expected:
                identical.append(name)
            else:
                conflicts.append(name)
        else:
            additions.append(name)
    if conflicts:
        print(json.dumps({'status':'conflict','written':0,'paths':conflicts}, ensure_ascii=False, indent=2))
        return 2
    if apply:
        # Recheck per file and use exclusive creation. A concurrent edit can stop an
        # install partway through; rerun safely after resolving the conflict.
        for name in additions:
            dst = target / name
            reject_symlinks(dst)
            dst.parent.mkdir(parents=True, exist_ok=True)
            data = (source / name).read_bytes()
            if hashlib.sha256(data).hexdigest() != files[name]:
                raise ValueError(f'Package changed during installation: {name}')
            fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            with os.fdopen(fd, 'wb') as f:
                f.write(data)
    print(json.dumps({'status':'installed' if apply else 'dry_run','target':str(target),'added':len(additions),'identical':len(identical),'written':len(additions) if apply else 0}, ensure_ascii=False, indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', required=True, type=Path)
    parser.add_argument('--apply', action='store_true', help='Write files after the entire preflight succeeds')
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[3]
    target = Path(os.path.abspath(os.path.expanduser(args.project_root)))
    try:
        return install(source, target, args.apply)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f'Installation stopped: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
