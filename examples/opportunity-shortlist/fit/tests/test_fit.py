import copy
import json
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import cog_core
import task_logic

sys.path.insert(0, str(ROOT / 'scripts'))
from fixture_usage import fixture_result
from cog_cli import replay_binding

class FitTests(unittest.TestCase):
    def setUp(self):
        self.bundle = json.loads((ROOT / 'examples/sample-bundle.json').read_text())

    def finish(self):
        return cog_core.finish(self.bundle, fixture_result(self.bundle), replay_binding())

    def test_default_recommendation_and_honest_replay_binding(self):
        result = self.finish()
        self.assertTrue(result['ok'])
        self.assertEqual(result['problems'], [])
        self.assertEqual(result['payload']['decision']['recommendation'], 'pursue')
        self.assertFalse(result['binding']['provider_called'])
        self.assertIn('not-a-model', result['payload']['answered_by']['model'])

    def test_policy_changes_reuse_judgment_but_change_recommendation(self):
        baseline = self.finish()
        self.bundle['policy']['pursue_at'] = 0.95
        changed = self.finish()
        self.assertEqual(changed['payload']['answers'], baseline['payload']['answers'])
        self.assertEqual(changed['payload']['decision']['recommendation'], 'review')
        self.assertNotIn('policy', cog_core.prepare(self.bundle)['task']['state'])

    def test_both_threshold_boundaries_are_inclusive(self):
        answers = {'scope_match': {'type': 'noul', 'noul': .75}, 'delivery_capacity': {'type': 'noul', 'noul': .9}}
        self.assertEqual(task_logic.decide(self.bundle, answers)['recommendation'], 'pursue')
        answers['scope_match']['noul'] = .4
        self.assertEqual(task_logic.decide(self.bundle, answers)['recommendation'], 'review')
        answers['scope_match']['noul'] = .399
        self.assertEqual(task_logic.decide(self.bundle, answers)['recommendation'], 'pass')

    def test_changed_evidence_is_not_answered_by_old_fixture(self):
        self.bundle['company']['capabilities'].append('security auditing')
        with self.assertRaisesRegex(ValueError, 'No synthetic fixture matches'):
            fixture_result(self.bundle)

    def test_changed_policy_order_refused(self):
        self.bundle['policy']['review_at'] = .9
        with self.assertRaisesRegex(ValueError, 'review_at must be less'):
            fixture_result(self.bundle)

    def test_malformed_provider_answer_is_not_a_recommendation(self):
        answer = copy.deepcopy(fixture_result(self.bundle))
        answer['answers']['scope_match']['noul'] = 1.1
        result = cog_core.finish(self.bundle, answer, replay_binding())
        self.assertFalse(result['ok'])
        self.assertEqual(result['error']['code'], 'answers-invalid')

    def test_questions_and_example_match_declared_output(self):
        self.assertEqual(cog_core.self_check(), [])

    def test_changed_questions_cannot_reuse_old_synthetic_answers(self):
        from unittest.mock import patch
        changed = copy.deepcopy(cog_core.QUESTIONS['scope_match'])
        changed['instructions'] = 'A different question about the same inputs.'
        with patch.dict(cog_core.QUESTIONS, {'scope_match': changed}):
            with self.assertRaisesRegex(ValueError, 'No synthetic fixture matches'):
                fixture_result(self.bundle)
