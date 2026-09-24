#!/usr/bin/env python3
"""Check public source boundaries; optionally require clean, pinned checkouts."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

if sys.version_info < (3, 11):
    raise SystemExit('Workspace checks require Python 3.11 or newer; select a supported Python interpreter.')

import tomllib
from urllib.parse import unquote, urlsplit

SUITE = Path(__file__).resolve().parents[1]
MACHINE_PATH = re.compile(r'(?:/' r'Volumes/[^\s\"\'`<>]+|/(?:Users|home)/[^\s/\"\'`<>]+/[^\s\"\'`<>]+)')
SIBLING = re.compile(r'(?:\.\./)+((?:cog-|op-)[A-Za-z0-9_-]+|planning|public|_xfer\w*|trial-workspaces)(?:/[^\s\"\'`<>),}]*)?')
PRIVATE = re.compile(r'\b(?:cog-' r'demo|cog-' r'forge|cog-' r'issue-classifier|cog-' r'collab-qwen35b)\b')
LINK = re.compile(r'!?\[[^\]\n]*\]\(<?([^\s)>]+)>?(?:\s+"[^"]*")?\)')


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args]).decode().strip()


def repositories(suite=SUITE):
    return json.loads((suite / 'repositories.json').read_text())['repositories']


def checkout_errors(workspace, suite=SUITE, strict=False):
    errors = []
    for repo in [{'name': suite.name}, *repositories(suite)]:
        root = workspace / repo['name']
        if not (root / '.git').exists():
            errors.append(f"{repo['name']}: missing Git checkout")
            continue
        if root.is_symlink() or Path(git(root, 'rev-parse', '--show-toplevel')).resolve() != root.resolve():
            errors.append(f"{repo['name']}: checkout must be a real directory in this workspace")
        if strict:
            if git(root, 'status', '--porcelain', '--untracked-files=all'):
                errors.append(f"{repo['name']}: dirty checkout")
            if 'revision' in repo and git(root, 'rev-parse', 'HEAD') != repo['revision']:
                errors.append(f"{repo['name']}: HEAD differs from repositories.json")
    return errors


def scan(workspace, suite=SUITE):
    names = {suite.name, *(r['name'] for r in repositories(suite))}
    roots = [(workspace / name).resolve() for name in sorted(names)]
    findings = []
    def add(path, line, rule, value):
        findings.append({'path': path, 'line': line, 'rule': rule,
                         'value': value, 'fingerprint': hashlib.sha256(value.encode()).hexdigest()})
    for root in roots:
        paths = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z', '--cached', '--others', '--exclude-standard']).decode().split('\0')
        for rel in sorted(set(filter(None, paths))):
            file = root / rel
            label = f'{root.name}/{rel}'
            # The exception ledger contains the offending strings by design.
            if root.name == suite.name and rel == 'workspace-exceptions.json':
                continue
            if file.is_symlink():
                target = file.resolve()
                if not any(target.is_relative_to(r) for r in roots) or not target.exists():
                    add(label, 0, 'symlink', str(file.readlink()))
                continue
            if not file.is_file():
                add(label, 0, 'missing-file', rel)
                continue
            try:
                content = file.read_bytes()
                if b'\0' in content:
                    continue
                content = content.decode('utf-8')
            except UnicodeDecodeError:
                continue
            if file.name in {'pixi.toml', 'pyproject.toml'}:
                try:
                    manifest = tomllib.loads(content)
                except tomllib.TOMLDecodeError as exc:
                    add(label, 0, 'invalid-manifest', str(exc))
                    continue
                def local_paths(value):
                    if isinstance(value, dict):
                        for name, entry in value.items():
                            if name == 'path' and isinstance(entry, str):
                                yield entry
                            else:
                                yield from local_paths(entry)
                    elif isinstance(value, list):
                        for entry in value:
                            yield from local_paths(entry)
                for value in local_paths(manifest):
                    target = (file.parent / value).resolve()
                    if not any(target.is_relative_to(r) for r in roots) or not target.exists():
                        add(label, 0, 'local-dependency', value)
            for number, line in enumerate(content.splitlines(), 1):
                for match in PRIVATE.finditer(line):
                    add(label, number, 'private-reference', match.group())
                for match in MACHINE_PATH.finditer(line):
                    add(label, number, 'machine-path', match.group())
                for match in SIBLING.finditer(line):
                    if match.group(1) not in names:
                        add(label, number, 'undeclared-sibling', match.group())
                if file.suffix.lower() == '.md':
                    for match in LINK.finditer(line):
                        url = urlsplit(match.group(1))
                        if url.scheme or url.netloc or not url.path:
                            continue
                        target = (file.parent / unquote(url.path)).resolve()
                        if not any(target.is_relative_to(r) for r in roots) or not target.exists():
                            add(label, number, 'local-link', match.group(1))
    return findings


def key(item):
    return item['path'], item['rule'], item['fingerprint']


def check(workspace, suite=SUITE, strict=False):
    errors = checkout_errors(workspace, suite, strict)
    if any('missing Git checkout' in error or 'real directory' in error for error in errors):
        return errors
    findings = scan(workspace, suite)
    ledger = json.loads((suite / 'workspace-exceptions.json').read_text())
    allowed = {key(item): item for item in ledger['exceptions']}
    counts = {}
    for item in findings:
        identity = key(item)
        counts[identity] = counts.get(identity, 0) + 1
        if identity not in allowed or counts[identity] > allowed[identity]['count']:
            errors.append(f"{item['path']}:{item['line']}: {item['rule']}: {item['value']}")
    for identity, item in allowed.items():
        if counts.get(identity, 0) < item['count']:
            errors.append(f"{item['path']}: remove or reduce stale exception for {item['rule']}")
    print(f"Boundary scan: {len(findings)} findings; {sum(i['count'] for i in allowed.values())} explicitly recorded legacy occurrences.", flush=True)
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=SUITE.parent)
    parser.add_argument('--strict', action='store_true', help='Also reject dirty checkouts and component revision drift.')
    args = parser.parse_args()
    errors = check(args.workspace.resolve(), strict=args.strict)
    if errors:
        raise SystemExit('\n'.join(errors))
    print('Public workspace checks passed.')


if __name__ == '__main__':
    main()
