#!/usr/bin/env python3
"""Check publication boundaries for tracked and non-ignored source files.

This is a focused source-release check, not a comprehensive secret detector.
Local ignored SDKs/installations are deliberately outside the public file set.
"""
import argparse
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
TEXT_SUFFIXES = {'.py', '.cs', '.c', '.md', '.json', '.xml', '.yml', '.yaml'}
SPECIAL = {'LICENSE', '.gitignore', 'bin/xppc-mac'}
FORBIDDEN_PARTS = {'.local', 'runtime', 'framework', 'references', 'verification', '__pycache__'}
BINARY_MAGIC = (b'MZ', b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe', b'PK\x03\x04')
SENSITIVE = [re.compile(pattern) for pattern in (
    r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    r'\b(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}',
    r'\bAKIA[0-9A-Z]{16}\b',
    r'/(?:Users|home)/[^/\s"\']+/',
    r'https?://[^\s/]+\.(?:crm\d*\.dynamics|operations\.dynamics)\.com',
)]


def problems(relative, data):
    path = Path(relative)
    issues = []
    if any(part in FORBIDDEN_PARTS for part in path.parts):
        issues.append('private/generated directory')
    if path.suffix == '.png':
        if path.parent != Path('docs/assets') or not data.startswith(b'\x89PNG\r\n\x1a\n'):
            issues.append('unexpected image location or format')
        return issues
    if relative not in SPECIAL and path.suffix not in TEXT_SUFFIXES:
        issues.append('unexpected publication file type')
    if data.startswith(BINARY_MAGIC) or b'\x00' in data:
        return issues + ['binary content outside illustration assets']
    try:
        content = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        return issues + ['non-UTF-8 source']
    if any(pattern.search(content) for pattern in SENSITIVE):
        issues.append('private key, credential, local home path or environment URL pattern')
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tracked-only', action='store_true')
    args = parser.parse_args()
    command = ['git', 'ls-files', '-z', '--cached']
    if not args.tracked_only:
        command += ['--others', '--exclude-standard']
    paths = sorted(set(subprocess.check_output(command, cwd=ROOT).decode().split('\0')) - {''})
    failures = []
    for relative in paths:
        path = ROOT / relative
        if path.is_symlink():
            failures.append((relative, 'symbolic link'))
            continue
        if not path.is_file():
            failures.append((relative, 'tracked file missing'))
            continue
        for issue in problems(relative, path.read_bytes()):
            failures.append((relative, issue))
    for relative, issue in failures:
        print(relative + ': ' + issue, file=sys.stderr)
    if failures:
        return 1
    print('PASS public source boundary: ' + str(len(paths)) + ' files; no packaged executable/SDK artifacts')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
