"""Explicit synthetic-fixture usage task; uses the real decision-Cog finish path."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import cog_core
from cog_cli import replay_binding

def fixture_result(bundle):
    task = cog_core.prepare(bundle)['task']
    encoded = json.dumps(task, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    key = hashlib.sha256(encoded).hexdigest()
    fixtures = json.loads((ROOT / 'examples/fixtures.json').read_text())['fixtures']
    for fixture in fixtures:
        if fixture['task_sha256'] == key:
            return fixture['result']
    raise ValueError('No synthetic fixture matches this opportunity, company profile and question set. Use an unchanged supplied example, explicitly author a matching fixture, or choose live mode. A changed policy can reuse answers; changed evidence cannot.')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', '--bundle', dest='request', required=True)
    args = parser.parse_args()
    binding = {**replay_binding(), 'fixture_source': 'hand-authored-synthetic', 'fixture_file': 'examples/fixtures.json'}
    try:
        bundle = json.loads(Path(args.request).read_text())
        result = fixture_result(bundle)
        envelope = cog_core.finish(bundle, result, binding)
        envelope['task'] = 'fixture'
    except (ValueError, KeyError, TypeError, OSError) as exc:
        envelope = cog_core.envelope('fixture', False, error={'code': 'fixture-refused', 'detail': str(exc)}, binding=binding)
    print(json.dumps(envelope, indent=2, allow_nan=False))
    return 0 if envelope['ok'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
