#!/usr/bin/env python3
"""Fetch the documented sibling layout without replacing existing checkouts."""
import argparse
import json
from pathlib import Path
import subprocess

SUITE = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=SUITE.parent)
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    repositories = json.loads((SUITE / 'repositories.json').read_text())['repositories']
    for repo in repositories:
        dest = workspace / repo['name']
        if dest.exists():
            if not (dest / '.git').exists():
                raise SystemExit(f'{dest} exists but is not a Git checkout; refusing to replace it.')
            print(f'Keeping existing checkout: {dest}', flush=True)
        else:
            subprocess.run(['git', 'clone', repo['url'], str(dest)], check=True)
            subprocess.run(['git', '-C', str(dest), 'checkout', '--detach', repo['revision']], check=True)
        if args.install:
            subprocess.run(['pixi', 'install', '--locked', '--manifest-path', str(dest / 'pixi.toml')], check=True)

if __name__ == '__main__':
    main()
