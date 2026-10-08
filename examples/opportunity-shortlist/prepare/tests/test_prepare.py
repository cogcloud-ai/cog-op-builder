import copy
import json
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import cog_core
import task_logic

class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.bundle = json.loads((ROOT / 'examples/sample-bundle.json').read_text())

    def test_preserves_inputs_and_reaches_nothing(self):
        self.assertEqual(cog_core.validate_input(self.bundle), [])
        payload, problems = task_logic.run(self.bundle, None, None)
        self.assertEqual(payload, {**self.bundle, 'authority_use': []})
        self.assertEqual(problems, [])
        self.assertEqual(cog_core.validate_output(payload, self.bundle), [])

    def test_duplicate_ids_refused(self):
        self.bundle['opportunities'][1]['id'] = self.bundle['opportunities'][0]['id']
        self.assertEqual(cog_core.validate_input(self.bundle)[0]['check'], 'duplicate-opportunity')

    def test_invalid_threshold_order_refused(self):
        self.bundle['policy']['review_at'] = self.bundle['policy']['pursue_at']
        self.assertEqual(cog_core.validate_input(self.bundle)[0]['check'], 'policy-order')

    def test_missing_or_blank_description_refused(self):
        del self.bundle['opportunities'][0]['description']
        self.assertTrue(cog_core.validate_input(self.bundle))
        self.bundle['opportunities'][0]['description'] = '   '
        self.assertTrue(cog_core.validate_input(self.bundle))
