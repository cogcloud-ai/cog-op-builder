"""Shared bounded Op cycles: declarative transitions, immutable phases, reservations.

This is Smith machinery. Op-specific behavior belongs only in op.yaml and Cog
usage steps. Reservation units bound declared invocations, not vendor invoices.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import sys

import op_runner
import op_spec
import op_track

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'openteams/op-cycle [0.1]'
MASTERS = ('op_runner.py', 'op_spec.py', 'op_track.py', 'op_cycle.py')


class BudgetExhausted(ValueError):
    pass


def read(path):
    return json.loads(Path(path).read_text())


def machinery_digest(package):
    return op_runner.canonical_sha256({name: op_runner.sha256_file(Path(package) / 'src' / name) for name in MASTERS})


def save(state, directory):
    op_track.write_json(Path(directory) / 'cycle.json', state, base=directory)


def summary(state, directory, child=None):
    value = {'ok': state['status'] in ('completed', 'completed-with-problems'), 'status': state['status'],
             'cycle_dir': str(directory), 'cycle': str(Path(directory) / 'cycle.json'),
             'run_dir': state['phases'][-1].get('run_dir') if state['phases'] else None,
             'attempts': len(state['phases']), 'cost_units_reserved': state['cost_units_reserved'],
             'max_attempts': state['max_attempts'], 'max_cost_units': state['max_cost_units']}
    if state.get('reason'):
        value['reason'] = state['reason']
    if child:
        value['child'] = child
        for key in ('step', 'pending', 'track', 'outputs'):
            if key in child:
                value[key] = child[key]
    return value


def preflight(package, phases):
    for phase in phases.values():
        spec = op_spec.OpSpec(phase)
        problems = op_spec.declaration_problems(spec, package)
        for step in spec.ordered:
            source = (Path(package) / step['cog']['source']).resolve()
            manifest, error = op_spec.read_cog_manifest(source)
            if error or manifest is None or manifest.get('reaches'):
                problems.append('Cycles require installed pure Cog declarations: ' + step['id'])
        if problems:
            raise op_spec.OpSpecError(problems)


def previous_input(track):
    context = {'steps': {}}
    op_runner._restore_context(track, context)
    for record in track['steps']:
        if record.get('request'):
            context['steps'][record['id']]['request'] = read(record['request'])
    return {'steps': context['steps']}


def new_phase(package, directory, state, phases, outcome='initial', prior=None):
    number = len(state['phases']) + 1
    if number > state['max_attempts']:
        raise BudgetExhausted('Attempt budget exhausted; every candidate and review is retained.')
    phase_dir = Path(directory) / 'phases' / f'{number:04d}'
    op_track.ensure_dir(phase_dir)
    phase_package = phase_dir / 'package'
    op_track.ensure_dir(phase_package / 'src')
    doc = copy.deepcopy(phases[outcome])
    for step in doc['steps']:
        source = (Path(package) / step['cog']['source']).resolve()
        step['cog']['source'] = os.path.relpath(source, phase_package)
    spec = op_spec.OpSpec(doc)
    op_track.write_json(phase_package / 'op.yaml', doc, base=directory)
    for name in MASTERS:
        shutil.copyfile(Path(package) / 'src' / name, phase_package / 'src' / name)
    for name in ('pixi.toml', 'pixi.lock', 'LICENSE', 'LICENSE.smith', 'NOTICE', 'NOTICE.smith', 'LICENSING.md'):
        if (Path(package) / name).is_file():
            shutil.copyfile(Path(package) / name, phase_package / name)
    request = copy.deepcopy(state['request'])
    seed = []
    if prior:
        request['cycle_previous'] = previous_input(prior)
        restart = state['configuration']['transitions'][outcome]['restart']
        original = op_spec.load(Path(package) / 'op.yaml')
        prefix = [step['id'] for step in original.ordered]
        prefix = prefix[:prefix.index(restart)]
        records = {record['id']: record for record in prior['steps']}
        for sid in prefix:
            record = copy.deepcopy(records[sid])
            if record['status'] not in ('passed', 'passed-with-problems'):
                raise op_spec.OpSpecError('A cycle may reuse only passed prefix steps: ' + sid)
            if op_spec.gate_policy(original.step(sid)) == 'human' and ((record.get('decision') or {}).get('value') or {}).get('verdict') != 'accept':
                raise op_spec.OpSpecError('A cycle cannot reuse an unaccepted artifact: ' + sid)
            step = original.step(sid)
            if record.get('cog_sha256') != op_runner.cog_package_sha256(Path(package) / step['cog']['source']):
                raise op_spec.OpSpecError('A reusable prefix Cog changed; start a new cycle: ' + sid)
            record['imported_from'] = {'run_id': prior['run_id'], 'step': sid}
            seed.append(record)
    spec.build_inputs(request)
    op_track.write_json(phase_dir / 'request.json', request, base=directory)
    op_track.write_json(phase_dir / 'seed.json', seed, base=directory)
    state['phases'].append({'number': number, 'outcome': outcome, 'package': str(phase_package),
                            'request': str(phase_dir / 'request.json'), 'seed': str(phase_dir / 'seed.json'),
                            'run_dir': None, 'status': 'prepared'})
    save(state, directory)  # Phase ownership is durable before any Cog runs.


def drive(package, directory, state, phases, decision=None):
    def reserve(sid):
        units = state['configuration']['costs'][sid]
        if state['cost_units_reserved'] + units > state['max_cost_units']:
            raise BudgetExhausted('Cost reservation budget exhausted before invoking step ' + sid)
        state['cost_units_reserved'] += units
        state['reservations'].append({'phase': len(state['phases']), 'step': sid, 'units': units, 'at': op_track.utc_now()})
        save(state, directory)
    policy = {**state['configuration'], 'reserve': reserve, 'owner': str(Path(directory).resolve())}
    try:
        if not state['phases']:
            new_phase(package, directory, state, phases)
        while True:
            phase = state['phases'][-1]
            phase_package = Path(phase['package'])
            op_track.contained(phase_package, directory)
            if phase['run_dir'] is None:
                existing = list((phase_package / 'runs').glob('*/track.json'))
                if len(existing) > 1:
                    raise op_spec.OpSpecError('Ambiguous phase runs; inspect the saved cycle.')
                if existing:
                    phase['run_dir'] = str(existing[0].parent)
                    save(state, directory)
            track = read(Path(phase['run_dir']) / 'track.json') if phase['run_dir'] else None
            if track and track['status'] == 'cycle-transition':
                phase['status'] = 'cycle-transition'
                save(state, directory)
                new_phase(package, directory, state, phases, track['cycle_outcome'], track)
                continue
            if track and track['status'] in ('completed', 'completed-with-problems', 'rejected'):
                phase['status'] = track['status']
                state['status'] = 'completed' if track['status'] == 'completed' else track['status']
                save(state, directory)
                return (0 if state['status'] in ('completed', 'completed-with-problems') else 1), summary(state, directory, {'outputs': track.get('outputs')})
            prior_status = state['status']
            state['status'] = 'running'; save(state, directory)
            try:
                if phase['run_dir']:
                    op_track.contained(Path(phase['run_dir']), directory)
                    code, child = op_runner.resume(phase_package, phase['run_dir'], decision_path=decision, cycle_policy=policy)
                else:
                    code, child = op_runner.run(phase_package, phase['request'], cycle_policy=policy, seed=read(phase['seed']), request_dir=state['request_dir'])
            except Exception:
                state['status'] = prior_status
                discovered = list((phase_package / 'runs').glob('*/track.json'))
                if len(discovered) == 1:
                    phase['run_dir'] = str(discovered[0].parent)
                    phase['status'] = read(discovered[0])['status']
                    if phase['status'] != 'paused':
                        state['status'] = phase['status']
                save(state, directory)
                raise
            decision = None
            phase['run_dir'], phase['status'] = child['run_dir'], child['status']
            save(state, directory)
            if code == 4:
                continue
            state['status'] = child['status']
            if child['status'] == 'failed':
                track = read(Path(child['run_dir']) / 'track.json')
                failed = next((row for row in track['steps'] if row['status'] == 'failed'), None)
                if failed:
                    state['reason'] = '; '.join((failed.get('gate') or {}).get('reasons') or ['Step failed: ' + failed['id']])
                    envelope = read(failed['envelope']) if failed.get('envelope') else {}
                    error = envelope.get('error') or {}
                    reported = envelope.get('raw')
                    if error.get('code') == 'invocation-failed' and isinstance(reported, dict) and not op_runner.envelope_problems(reported) and reported.get('ok') is False:
                        error = reported.get('error') or error
                    if error.get('code') in state['configuration'].get('terminal_errors', {}).get(failed['id'], []):
                        state['status'] = 'refused'
                        state['reason'] = error.get('detail') or envelope.get('detail') or state['reason']
            save(state, directory)
            return code, summary(state, directory, child)
    except BudgetExhausted as exc:
        if state['phases']:
            phase = state['phases'][-1]
            if phase.get('run_dir'):
                track_path = Path(phase['run_dir']) / 'track.json'
                track = read(track_path)
                if track['status'] == 'running':
                    track['status'] = 'budget-exhausted'
                    for step in track['steps']:
                        if step['status'] == 'running':
                            step['status'] = 'budget-exhausted'
                            step['gate'] = {'status': 'fail', 'reasons': [str(exc)]}
                    op_track.save(track, Path(phase['run_dir']))
                    phase['status'] = 'budget-exhausted'
        state['status'], state['reason'] = 'budget-exhausted', str(exc)
        save(state, directory)
        return 1, summary(state, directory)


def start(package, request_path, cycles_dir=None):
    package = Path(package).resolve()
    spec = op_spec.load(package / 'op.yaml')
    phases = op_spec.cycle_phases(spec.doc)
    request = op_spec.load_document(request_path)
    values = spec.build_inputs(request)
    context = {'inputs': values, 'steps': {}}
    limits = {key: op_spec.evaluate(spec.doc['cycle'][key], context) for key in ('max_attempts', 'max_cost_units')}
    if type(limits['max_attempts']) is not int or limits['max_attempts'] < 1 or type(limits['max_cost_units']) is not int or limits['max_cost_units'] < 0:
        raise op_spec.OpSpecError('Cycle limits need positive integer attempts and nonnegative integer reservation units.')
    preflight(package, phases)
    directory = (Path(cycles_dir).resolve() if cycles_dir else package / 'cycles') / op_track.new_run_id()
    op_track.ensure_dir(directory)
    state = {'schema': SCHEMA, 'status': 'running', 'package': str(package),
             'spec_sha256': spec.sha256(), 'machinery_sha256': machinery_digest(package),
             'configuration': spec.doc['cycle'], 'request': request, 'request_dir': str(Path(request_path).resolve().parent),
             'input_request': str(Path(request_path).resolve()),
             'request_sha256': op_runner.canonical_sha256(request),
             **limits, 'cost_units_reserved': 0, 'reservations': [], 'phases': []}
    with op_runner.RunLock(directory):
        save(state, directory)
        return drive(package, directory, state, phases)


def resume(package, directory, decision=None):
    package, directory = Path(package).resolve(), Path(directory).resolve()
    with op_runner.RunLock(directory):
        state = read(directory / 'cycle.json')
        spec = op_spec.load(package / 'op.yaml')
        if state['schema'] != SCHEMA or state['package'] != str(package) or state['spec_sha256'] != spec.sha256() or state['machinery_sha256'] != machinery_digest(package) or state['request_sha256'] != op_runner.canonical_sha256(state['request']):
            raise op_spec.OpSpecError('Cycle package, machinery or request changed; resume cannot adopt new work or budgets.')
        expected = {key: op_spec.evaluate(spec.doc['cycle'][key], {'inputs': spec.build_inputs(state['request']), 'steps': {}}) for key in ('max_attempts', 'max_cost_units')}
        if any(state[key] != value for key, value in expected.items()) or state['configuration'] != spec.doc['cycle'] or state['cost_units_reserved'] != sum(row['units'] for row in state['reservations']):
            raise op_spec.OpSpecError('Cycle limits or reservation ledger changed; inspect the saved cycle.')
        costs = state['configuration']['costs']
        for row in state['reservations']:
            if row.get('step') not in costs or type(row.get('units')) is not int or row['units'] != costs[row['step']] or type(row.get('phase')) is not int or not 1 <= row['phase'] <= len(state['phases']):
                raise op_spec.OpSpecError('Cycle reservation units or phase differ from the declared policy.')
        from collections import Counter
        recorded = Counter((row['phase'], row['step']) for row in state['reservations'])
        for phase in state['phases']:
            tracks = list((Path(phase['package']) / 'runs').glob('*/track.json'))
            if len(tracks) > 1:
                raise op_spec.OpSpecError('Ambiguous cycle child Tracks.')
            if tracks:
                child = read(tracks[0])
                for step in child['steps']:
                    if step.get('imported_from'):
                        continue
                    count = len(step.get('attempts') or [])
                    if recorded[(phase['number'], step['id'])] < count:
                        raise op_spec.OpSpecError('Cycle reservation ledger is smaller than the child Track invocation ledger.')
        if state['status'] in ('completed', 'completed-with-problems', 'rejected', 'refused', 'budget-exhausted'):
            return (0 if state['status'] in ('completed', 'completed-with-problems') else 1), summary(state, directory)
        phases = op_spec.cycle_phases(spec.doc); preflight(package, phases)
        return drive(package, directory, state, phases, decision)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--request'); source.add_argument('--resume')
    parser.add_argument('--decision'); parser.add_argument('--cycles-dir')
    args = parser.parse_args()
    if args.decision and not args.resume:
        parser.error('--decision requires --resume')
    try:
        code, output = resume(ROOT, args.resume, args.decision) if args.resume else start(ROOT, args.request, args.cycles_dir)
    except (op_spec.OpSpecError, OSError, ValueError, KeyError, TypeError) as exc:
        code, output = 2, {'ok': False, 'status': 'invalid-input', 'problems': exc.problems if isinstance(exc, op_spec.OpSpecError) else [str(exc)]}
    print(json.dumps(output, indent=2))
    return code


if __name__ == '__main__':
    sys.exit(main())
