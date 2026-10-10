"""Deterministic suite for op-live (created by cog-smith `op new`).

Model-free and Cog-free: the spec must load, its declared steps must name
the Cogs and tasks it claims, and a dry run must write a planned Track.
Extend with Op-specific assertions; never edit src/ (that is shared Op
machinery, enforced by `smith op check`).
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import op_runner  # noqa: E402
import op_spec    # noqa: E402


class SpecTests(unittest.TestCase):
    def setUp(self):
        self.spec = op_spec.load(ROOT / "op.yaml")

    def test_identity(self):
        self.assertEqual(self.spec.id, "openteams/op-learning-shortlist")
        self.assertEqual(self.spec.version, "0.1.0")

    def test_every_step_names_a_cog_usage_task(self):
        for step in self.spec.steps:
            self.assertIn("cog", step, step["id"])
            for field in ("id", "source", "task"):
                self.assertTrue(step["cog"].get(field), (step["id"], field))

    def test_order_respects_depends_on(self):
        seen = []
        for step in self.spec.ordered:
            for dep in step.get("depends_on") or []:
                self.assertIn(dep, seen, step["id"])
            seen.append(step["id"])


class DryRunTests(unittest.TestCase):
    def test_dry_run_writes_a_planned_track(self):
        request = ROOT / "examples" / "request.json"
        spec = op_spec.load(ROOT / "op.yaml")
        try:
            # ONLY an unfilled starter request is a skip: the example is
            # checked against the declared inputs here, so a broken mapping
            # in the dry run below fails the suite instead of hiding in it.
            spec.build_inputs(json.loads(request.read_text()))
        except op_spec.OpSpecError as exc:
            self.skipTest("examples/request.json is still the generated "
                          "starter: " + "; ".join(exc.problems))
        with tempfile.TemporaryDirectory() as directory:
            code, output = op_runner.run(ROOT, request, dry_run=True,
                                         runs_dir=directory)
            self.assertEqual(code, 0)
            track = json.loads(Path(output["track"]).read_text())
            self.assertEqual(track["status"], "planned")
            self.assertEqual([s["id"] for s in track["steps"]],
                             [s["id"] for s in op_spec.load(ROOT / "op.yaml").ordered])
            for step in track["steps"]:
                self.assertEqual(step["status"], "planned")


if __name__ == "__main__":
    unittest.main()
