"""Real Workbench admission/composition with a synthetic provider turn; no HTTP."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[2]
HOST = WORKSPACE / 'cog-workbench'
sys.path.insert(0, str(HOST / 'src'))
from workbench_suite import Suite, digest
sys.path.insert(0, str(WORKSPACE / 'cog-typesafe/src'))
import typesafe_runtime

spec = importlib.util.spec_from_file_location('shortlist_live_adapter', ROOT / 'fit/scripts/live_usage.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class LiveAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='.learning-live-test-', dir=WORKSPACE)
        self.addCleanup(self.temp.cleanup)
        self.clone = Path(self.temp.name) / 'fit'
        shutil.copytree(ROOT / 'fit', self.clone, ignore=shutil.ignore_patterns('.pixi', '.op-composition.json', '__pycache__'))
        self.patch_root = patch.object(adapter, 'ROOT', self.clone)
        self.patch_root.start(); self.addCleanup(self.patch_root.stop)
        self.journal = patch.object(Suite, 'journal', return_value=None)
        self.journal.start(); self.addCleanup(self.journal.stop)
        self.suite = Suite(WORKSPACE, Path(self.temp.name) / 'state', journal=lambda entry: None)
        request = json.loads((WORKSPACE / 'cog-typesafe/examples/bind-request.json').read_text())
        request['binding_id'] = 'synthetic-learning-test'
        original_call = self.suite.call

        class OfflineAPI:
            def models(self, key):
                return {'models': ['jev']}

        def offline_admission(root, task, args=(), **kwargs):
            if task != 'bind':
                return original_call(root, task, args, **kwargs)
            supplied = json.loads(Path(args[args.index('--request') + 1]).read_text())
            candidate = typesafe_runtime.candidate(supplied, api=OfflineAPI())
            return typesafe_runtime.envelope('bind', candidate)

        with patch.dict('os.environ', {'TYPESAFE_API_KEY': 'synthetic-test-only-not-a-credential'}):
            with patch.object(self.suite, 'call', side_effect=offline_admission):
                binding = self.suite.bind('cog-typesafe', request)
        self.reference = {'binding_id': binding['binding_id'], 'revision': binding['revision']}
        self.suite.activate_composition(self.clone, self.reference)
        self.bundle = json.loads((ROOT / 'examples/single.json').read_text())
        self.original_call = Suite.call

    def invoke(self):
        original = self.original_call
        sample = json.loads((ROOT / 'fit/examples/sample-result.json').read_text())
        sample['model'] = 'jev-1.13.0'
        sample['answer_source'] = 'system-one-model'
        seen = []

        def fake_turn(suite, root, task, args=(), **kwargs):
            if task != 'turn':
                return original(suite, root, task, args, **kwargs)
            request = json.loads(Path(args[args.index('--request') + 1]).read_text())
            binding = json.loads(Path(args[args.index('--binding') + 1]).read_text())
            seen.append(request)
            return {'envelope': 1, 'ok': True, 'error': None, 'problems': [], 'cog': binding['provider'],
                    'binding': binding, 'payload': {'document_kind': 'harness_turn_result',
                    'contract': request['contract'], 'request_id': request['request_id'],
                    'binding': request['binding'], 'model_binding': request['model_binding'],
                    'result': sample, 'tool_uses': []}}

        with patch.object(Suite, 'call', new=fake_turn):
            result = adapter.invoke(self.bundle)
        return result, seen

    def test_nested_live_cog_uses_admitted_host_and_real_packaged_checks(self):
        result, seen = self.invoke()
        self.assertTrue(result['ok'])
        self.assertEqual(result['problems'], [])
        self.assertEqual(result['task'], 'ask-composed')
        self.assertEqual(result['binding']['composition']['binding'], self.reference)
        self.assertEqual(result['payload']['decision']['recommendation'], 'pursue')
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]['task']['state']['opportunity'], self.bundle['opportunity'])
        self.assertNotIn('policy', seen[0]['task']['state'])
        self.assertNotIn('fixture_source', result['binding'])

    def test_revoked_binding_refuses_execution(self):
        self.suite.revoke(self.reference)
        with self.assertRaisesRegex(ValueError, 'revoked'):
            self.invoke()

    def test_changed_consumer_refuses_execution(self):
        with (self.clone / 'context/questions.json').open('a') as f:
            f.write('\n')
        with self.assertRaisesRegex(ValueError, 'recompose'):
            self.invoke()

    def test_changed_host_requires_reactivation(self):
        path = self.clone / '.op-composition.json'
        config = json.loads(path.read_text()); config.pop('sha256')
        config['host_sha256'] = '0' * 64
        config['sha256'] = digest(config)
        path.write_text(json.dumps(config))
        with self.assertRaisesRegex(ValueError, 'Workbench changed'):
            self.invoke()


if __name__ == '__main__':
    unittest.main()
