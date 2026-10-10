import copy
import json
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import cog_core
import task_logic

class ShortlistTests(unittest.TestCase):
    def setUp(self):
        self.bundle = json.loads((ROOT / 'examples/sample-bundle.json').read_text())

    def test_ranked_proposals_are_grounded_and_digest_bound(self):
        self.assertEqual(cog_core.validate_input(self.bundle), [])
        payload, problems = task_logic.run(self.bundle, None, None)
        self.assertEqual(problems, [])
        self.assertEqual(cog_core.validate_output(payload, self.bundle), [])
        self.assertEqual([row['change_id'] for row in payload['changes']], ['OPP-001', 'OPP-002'])
        self.assertEqual([row['opportunity_id'] for row in payload['ranked']], ['OPP-001', 'OPP-002', 'OPP-003'])
        for change in payload['changes']:
            self.assertEqual(change['content_sha256'], cog_core.change_content_sha256(change))
        self.assertNotIn('approved', payload)

    def test_matches_by_id_even_when_assessments_are_reordered(self):
        expected, _ = task_logic.run(self.bundle, None, None)
        self.bundle['assessments'].reverse()
        actual, _ = task_logic.run(self.bundle, None, None)
        self.assertEqual(actual, expected)

    def test_missing_duplicate_and_foreign_assessments_refused(self):
        for mode in ('missing', 'duplicate', 'foreign'):
            bundle = copy.deepcopy(self.bundle)
            if mode == 'missing':
                bundle['assessments'].pop()
            elif mode == 'duplicate':
                bundle['assessments'][1] = bundle['assessments'][0]
            else:
                bundle['assessments'][0]['decision']['opportunity_id'] = 'OPP-999'
            with self.subTest(mode=mode):
                self.assertEqual(cog_core.validate_input(bundle)[0]['check'], 'assessment-coverage')

    def test_equal_scores_have_a_stable_id_tiebreak(self):
        for item in self.bundle['assessments']:
            item['decision']['score'] = .5
        self.bundle['assessments'].reverse()
        payload, _ = task_logic.run(self.bundle, None, None)
        self.assertEqual([item['opportunity_id'] for item in payload['ranked']], ['OPP-001', 'OPP-002', 'OPP-003'])
