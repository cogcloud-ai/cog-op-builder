#!/usr/bin/env python3
"""Small learning client; the shared Op runtime owns execution and decisions."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parents[2]
PACKAGES = ('prepare', 'fit', 'shortlist', 'op', 'op-live')
LATEST = ROOT / 'var/latest.json'


def read(path):
    return json.loads(Path(path).read_text())


def child_env():
    return {key: value for key, value in os.environ.items() if not key.startswith('PIXI_')}


def command(package, args):
    completed = subprocess.run([sys.executable, *args], cwd=ROOT / package,
                               env=child_env(), capture_output=True, text=True)
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        raise ValueError(completed.stderr.strip() or completed.stdout.strip() or 'The declared command returned no result.') from None
    return completed.returncode, result


def selected_run(args):
    if args.run:
        run_dir = Path(args.run).resolve()
    elif LATEST.exists():
        run_dir = Path(read(LATEST)['run_dir'])
    else:
        raise ValueError('No run selected. Run `pixi run start` first, or supply --run PATH.')
    track = read(run_dir / 'track.json')
    if track['op']['id'] != 'openteams/op-learning-shortlist':
        raise ValueError('This is not an Opportunity Shortlist learning run.')
    # Only read/identify the spec here; execution and digest enforcement stay
    # in the shared runtime. No second scheduling or recovery engine.
    sys.path.insert(0, str(ROOT / 'op/src'))
    import op_spec
    candidates = [package for package in ('op', 'op-live')
                  if op_spec.load(ROOT / package / 'op.yaml').sha256() == track['spec_sha256']]
    if len(candidates) != 1:
        raise ValueError('The Op specification changed. Restore the spec before resuming, or start a new run.')
    return run_dir, track, candidates[0]


def show_run(run_dir, track):
    print(f"Run: {run_dir}\nStatus: {track['status']}")
    print('Track: ' + str(run_dir / 'track.json'))
    for step in track['steps']:
        print(f"  {step['id']}: {step['status']}")
        if step.get('problems'):
            print(json.dumps(step['problems'], indent=2))
    if track['status'] == 'paused':
        pending = read(run_dir / 'pending/shortlist.json')
        print('\nRecommendations (advice, not approval):')
        for row in pending['payload']['ranked']:
            print(f"  {row['opportunity_id']}  {row['recommendation']:7}  {row['score']:.2f}  {row['title']}")
        print('\nChoices awaiting your decision: ' + ', '.join(change['change_id'] for change in pending['payload']['changes']))
        print('Review: ' + str(run_dir / 'pending/shortlist.md'))
        print('Choose explicitly, for example: pixi run decide -- --approve OPP-001 --reject-rest --by learner')
    elif track['status'].startswith('completed'):
        print('\nFinal human choices:')
        for verdict in ('approved', 'rejected'):
            choices = track.get('outputs', {}).get(verdict, [])
            print(f"  {verdict}: " + (', '.join(change['change_id'] if isinstance(change, dict) else change for change in choices) or '(none)'))
    elif track['status'] == 'failed':
        print('\nInspect the failing envelope named in the Track. No later step ran.')


def decision_document(pending, approved, reject_rest, reject_all, by):
    if not by.strip():
        raise ValueError('--by must name the person making this decision.')
    changes = pending['payload']['changes']
    ids = [change['change_id'] for change in changes]
    if len(approved) != len(set(approved)):
        raise ValueError('Do not repeat an approved id.')
    if set(approved) - set(ids):
        raise ValueError('Unknown or unproposed id(s): ' + ', '.join(sorted(set(approved) - set(ids))))
    if reject_all and approved:
        raise ValueError('--reject-all cannot be combined with --approve.')
    if not reject_rest and not reject_all:
        raise ValueError('Use --reject-rest with your approvals, or --reject-all. Nothing is decided implicitly.')
    return {'schema': 'openteams/op-decision [0.1]', 'run_id': pending['run_id'], 'step': pending['step'],
            'payload_sha256': pending['payload_sha256'], 'decided_by': by,
            'decided_at': datetime.now(timezone.utc).isoformat(),
            'decisions': [{'change_id': change_id, 'verdict': 'approve' if change_id in approved else 'reject'} for change_id in ids]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('setup', help='Install the five declared package environments from committed locks.')
    sub.add_parser('check', help='Check every package against Smith and run package tests.')
    single = sub.add_parser('single', help='Run the fit Cog alone; no Op.')
    single.add_argument('--request', default='examples/single.json')
    single.add_argument('--live', action='store_true')
    single.add_argument('--json', action='store_true')
    start = sub.add_parser('start', help='Run the Op to its human Gate.')
    start.add_argument('--request', default='examples/request.json')
    start.add_argument('--live', action='store_true')
    start.add_argument('--dry-run', action='store_true')
    for name in ('status', 'resume', 'decide'):
        p = sub.add_parser(name)
        p.add_argument('--run', help='Run directory; defaults to the last run started by this helper.')
        if name == 'decide':
            p.add_argument('--approve', nargs='+', default=[])
            group = p.add_mutually_exclusive_group(required=True)
            group.add_argument('--reject-rest', action='store_true')
            group.add_argument('--reject-all', action='store_true')
            p.add_argument('--by', required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == 'setup':
            for package in PACKAGES:
                subprocess.run(['pixi', 'install', '--locked'], cwd=ROOT / package, env=child_env(), check=True)
            print('Ready. Start with `pixi run single`, then `pixi run start`.')
            return 0
        if args.action == 'check':
            smith = WORKSPACE / 'cog-smith'
            for package in PACKAGES:
                command_args = ['pixi', 'run', 'python', 'src/cogsmith_cli.py']
                command_args += ['op', 'check'] if package.startswith('op') else ['check']
                command_args += [str(ROOT / package), '--tests']
                subprocess.run(command_args, cwd=smith, env=child_env(), check=True)
            return 0
        if args.action == 'single':
            print('LIVE provider call.' if args.live else 'OFFLINE: hand-authored synthetic answers; no provider call.', file=sys.stderr)
            code, result = command('fit', ['scripts/live_usage.py' if args.live else 'scripts/fixture_usage.py', '--request', str(Path(args.request).resolve())])
            if args.json or not result.get('ok'):
                print(json.dumps(result, indent=2))
            else:
                decision = result['payload']['decision']
                print(f"{decision['opportunity_id']}: {decision['title']}\nRecommendation: {decision['recommendation']} (score {decision['score']:.2f})")
                for reason in decision['reasons']:
                    print('  ' + reason)
                print('This is a recommendation. No opportunity has been approved.')
            return code
        if args.action == 'start':
            package = 'op-live' if args.live else 'op'
            print('LIVE provider calls.' if args.live else 'OFFLINE: hand-authored synthetic answers; no provider calls.')
            argv = ['src/op_runner.py', '--request', str(Path(args.request).resolve())]
            if args.dry_run:
                argv.append('--dry-run')
            code, result = command(package, argv)
            if result.get('run_dir'):
                run_dir = Path(result['run_dir'])
                if not args.dry_run:
                    LATEST.parent.mkdir(exist_ok=True)
                    LATEST.write_text(json.dumps({'run_dir': str(run_dir)}) + '\n')
                show_run(run_dir, read(run_dir / 'track.json'))
            else:
                print(json.dumps(result, indent=2))
            # A pause is an expected, successful handoff in this learning
            # client. The raw shared runtime still returns exit 3.
            return 0 if code == 3 else code
        run_dir, track, package = selected_run(args)
        if args.action == 'status':
            show_run(run_dir, track)
            return 0
        argv = ['src/op_runner.py', '--resume', str(run_dir)]
        if args.action == 'decide':
            if track['status'] != 'paused':
                raise ValueError('This run is not waiting for a decision. Inspect it with `pixi run status`.')
            pending = read(run_dir / 'pending/shortlist.json')
            decision = decision_document(pending, args.approve, args.reject_rest, args.reject_all, args.by)
            print('Applying your choices: ' + ', '.join(f"{item['change_id']}={item['verdict']}" for item in decision['decisions']))
            # Store proposed decision input outside the runtime's owned
            # control directories. The runtime validates and copies it.
            decision_dir = ROOT / 'var/decision-inputs'
            decision_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', dir=decision_dir, delete=False) as f:
                json.dump(decision, f, indent=2)
                decision_path = Path(f.name)
            argv += ['--decision', str(decision_path)]
        code, result = command(package, argv)
        if code not in (0, 3):
            print(json.dumps(result, indent=2))
        show_run(run_dir, read(run_dir / 'track.json'))
        return 0 if code == 3 else code
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as exc:
        print('Could not continue: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
