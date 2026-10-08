"""Declared live task for this nested example, using an activated Workbench composition.

The host path is fixed to the public suite's manifest-listed Workbench sibling.
No provider, command or host path is accepted from the task input.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
HOST = next((parent / 'cog-workbench' for parent in ROOT.parents
             if (parent / 'cog-workbench/src/workbench_suite.py').is_file()), None)

def invoke(bundle):
    if HOST is None:
        raise ValueError('Install the public Workbench sibling in the example workspace.')
    sys.path.insert(0, str(HOST / 'src'))
    from workbench_suite import Suite, digest, package_digest, require
    config = json.loads((ROOT / '.op-composition.json').read_text())
    checksum = config.pop('sha256')
    require(checksum == digest(config), 'Installed composition integrity failure.')
    require(config['host_sha256'] == package_digest(HOST), 'Workbench changed; activate composition again.')
    composition = config['composition']
    suite = Suite(workspace=HOST.parent, state=HOST.parent / config['state'])
    require(suite.root(composition['path']) == ROOT, 'Installed composition belongs to another consumer.')
    result = suite.invoke(composition, bundle)
    result['task'] = 'ask-composed'
    return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', '--bundle', dest='request', required=True)
    args = parser.parse_args()
    try:
        result = invoke(json.loads(Path(args.request).read_text()))
    except (ValueError, KeyError, TypeError, OSError, ImportError) as exc:
        print(json.dumps({'error': 'Live mode needs an admitted, activated System One binding: ' + str(exc)}))
        return 1
    print(json.dumps(result, indent=2))
    return 0 if result.get('ok') else 1

if __name__ == '__main__':
    raise SystemExit(main())
