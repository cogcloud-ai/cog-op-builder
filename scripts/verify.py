#!/usr/bin/env python3
"""Run model-free suite checks; never admit providers or invoke live models."""
import argparse
import json
from pathlib import Path
import subprocess
from check_workspace import check

SUITE = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=SUITE.parent)
    parser.add_argument('--package', help='Run only this component’s tests.')
    parser.add_argument('--strict', action='store_true', help='Require clean checkouts and pinned component revisions.')
    args = parser.parse_args()
    errors = check(args.workspace.resolve(), strict=args.strict)
    if errors:
        raise SystemExit('\n'.join(errors))
    names = [r['name'] for r in json.loads((SUITE / 'repositories.json').read_text())['repositories']]
    if args.package and args.package not in names:
        parser.error('Unknown package')
    failed = []
    for name in ([args.package] if args.package else names):
        print(f'\nTesting {name}', flush=True)
        result = subprocess.run(['pixi', 'run', 'test'], cwd=args.workspace / name)
        if result.returncode:
            failed.append(name)
    if failed:
        raise SystemExit('Failed: ' + ', '.join(failed))
    print('All requested model-free tests passed.')

if __name__ == '__main__':
    main()
