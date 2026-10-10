"""Exercise actual CLI tasks, shared-runtime pause/resume, and classroom examples."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('learning_demo', ROOT / 'demo.py')
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)

    def run_op(self, *arguments, package='op'):
        process = subprocess.run([sys.executable, str(ROOT / package / 'src/op_runner.py'), *map(str, arguments)],
                                 cwd=ROOT / package, env=demo.child_env(), text=True, capture_output=True)
        self.assertTrue(process.stdout, process.stderr)
        return process.returncode, json.loads(process.stdout)

    def start(self, request='request.json'):
        code, result = self.run_op('--request', ROOT / 'examples' / request, '--runs-dir', self.work / 'runs')
        self.assertEqual(code, 3, result)
        return Path(result['run_dir'])

    def write_decision(self, run, approved=(), reject_all=False):
        pending = demo.read(run / 'pending/shortlist.json')
        doc = demo.decision_document(pending, list(approved), not reject_all, reject_all, 'classroom-learner')
        path = self.work / 'decision.json'; path.write_text(json.dumps(doc))
        return path

    def test_pause_survives_restart_and_decision_reuses_completed_work(self):
        run = self.start()
        before = demo.read(run / 'track.json')
        self.assertEqual([step['status'] for step in before['steps']], ['passed', 'passed', 'awaiting-decision'])
        self.assertEqual(len(before['steps'][1]['elements']), 3)
        self.assertNotIn('approved', before.get('outputs', {}))
        for element in before['steps'][1]['elements']:
            envelope = demo.read(element['envelope'])
            self.assertFalse(envelope['binding']['provider_called'])
            self.assertEqual(envelope['binding']['fixture_source'], 'hand-authored-synthetic')
        code, result = self.run_op('--resume', run)
        self.assertEqual(code, 3, result)
        code, result = self.run_op('--resume', run, '--decision', self.write_decision(run, ['OPP-001']))
        self.assertEqual(code, 0, result)
        after = demo.read(run / 'track.json')
        self.assertEqual(after['status'], 'completed')
        self.assertEqual([item['change_id'] for item in after['outputs']['approved']], ['OPP-001'])
        self.assertEqual(after['outputs']['rejected'], ['OPP-002'])
        self.assertEqual(after['steps'][0]['attempts'], before['steps'][0]['attempts'])
        self.assertEqual(after['steps'][1]['elements'], before['steps'][1]['elements'])
        self.assertTrue((run / 'decisions/shortlist.json').exists())

    def test_person_can_reject_every_recommendation(self):
        run = self.start()
        code, result = self.run_op('--resume', run, '--decision', self.write_decision(run, reject_all=True))
        self.assertEqual(code, 0, result)
        self.assertEqual(demo.read(run / 'track.json')['outputs']['approved'], [])

    def test_changed_pending_payload_refuses_the_old_decision(self):
        run = self.start()
        decision = self.write_decision(run, ['OPP-001'])
        pending_path = run / 'pending/shortlist.json'
        pending = demo.read(pending_path)
        pending['payload']['changes'][0]['summary'] = 'Changed after the human reviewed it'
        pending_path.write_text(json.dumps(pending))
        code, result = self.run_op('--resume', run, '--decision', decision)
        self.assertNotEqual(code, 0, result)
        self.assertNotEqual(demo.read(run / 'track.json')['status'], 'completed')

    def test_bad_input_stops_before_fit(self):
        code, result = self.run_op('--request', ROOT / 'examples/request-duplicate.json', '--runs-dir', self.work / 'runs')
        self.assertEqual(code, 1, result)
        track = demo.read(Path(result['run_dir']) / 'track.json')
        self.assertEqual(track['failed_step'], 'prepare')
        self.assertEqual(track['steps'][1]['status'], 'not-reached')

    def test_alternate_profile_uses_its_own_explicit_fixtures(self):
        run = self.start('request-construction.json')
        pending = demo.read(run / 'pending/shortlist.json')
        self.assertEqual([item['change_id'] for item in pending['payload']['changes']], ['OPP-003'])
        self.assertEqual(pending['payload']['ranked'][0]['recommendation'], 'pursue')

    def test_unknown_evidence_stops_at_fit_without_silent_substitution(self):
        request = demo.read(ROOT / 'examples/request.json')
        request['company']['capabilities'].append('certified security auditing')
        path = self.work / 'changed.json'; path.write_text(json.dumps(request))
        code, result = self.run_op('--request', path, '--runs-dir', self.work / 'runs')
        self.assertEqual(code, 1, result)
        track = demo.read(Path(result['run_dir']) / 'track.json')
        self.assertEqual(track['failed_step'], 'fit')
        self.assertEqual(track['steps'][2]['status'], 'not-reached')
        self.assertEqual(track['steps'][1]['elements'][1]['status'], 'not-reached')

    def test_single_cog_exercise_changes_policy_not_answers(self):
        results = []
        for request in ('single.json', 'single-strict.json', 'single-construction.json'):
            process = subprocess.run([sys.executable, str(ROOT / 'demo.py'), 'single', '--json', '--request', str(ROOT / 'examples' / request)],
                                     cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            results.append(json.loads(process.stdout))
        self.assertEqual([r['payload']['decision']['recommendation'] for r in results], ['pursue', 'review', 'pass'])
        self.assertEqual(results[0]['payload']['answers'], results[1]['payload']['answers'])
        self.assertNotEqual(results[0]['payload']['answers'], results[2]['payload']['answers'])

    def test_decision_helper_refuses_unknown_ids_and_implicit_rejection(self):
        pending = {'run_id': 'test', 'step': 'shortlist', 'payload_sha256': 'a' * 64, 'payload': {'changes': [{'change_id': 'OPP-001'}]}}
        with self.assertRaisesRegex(ValueError, 'Unknown'):
            demo.decision_document(pending, ['OPP-999'], True, False, 'learner')
        with self.assertRaisesRegex(ValueError, 'Nothing is decided implicitly'):
            demo.decision_document(pending, ['OPP-001'], False, False, 'learner')
        with self.assertRaisesRegex(ValueError, 'person'):
            demo.decision_document(pending, ['OPP-001'], True, False, ' ')

    def test_live_entry_point_never_falls_back_to_fixtures(self):
        # Use a clean copy so this remains model-free even if a developer
        # has activated a live composition in the real package.
        import shutil
        copy_root = self.work / 'fit'
        shutil.copytree(ROOT / 'fit', copy_root, ignore=shutil.ignore_patterns('.pixi', '.op-composition.json', '__pycache__'))
        process = subprocess.run([sys.executable, str(copy_root / 'scripts/live_usage.py'), '--request', str(ROOT / 'examples/single.json')], text=True, capture_output=True)
        self.assertNotEqual(process.returncode, 0)
        result = json.loads(process.stdout)
        self.assertIn('admitted, activated', result['error'])
        self.assertNotIn('payload', result)

if __name__ == '__main__':
    unittest.main()
