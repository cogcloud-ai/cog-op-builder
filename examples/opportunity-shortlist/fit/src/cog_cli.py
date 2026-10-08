#!/usr/bin/env python3
"""Decision-Cog entry points (cog-smith decision-cog machinery, generic —
edit task_logic.py and context/, not this).

    pixi run check                                   # package self-check
    pixi run prepare -- --bundle examples/sample-bundle.json   # the turn, no call
    pixi run replay -- --bundle B.json --result R.json         # decide from saved answers
    pixi run export-fixtures -- --run RUN_DIR --step ID --name NAME
    pixi run derive-schema                           # $defs.answers from questions.json
    python src/cog_cli.py bridge prepare|finish --request DOC.json   # Workbench bridge

Live answers come only through `pixi run ask-composed` (a host-admitted
System One binding activated by Workbench). Nothing here selects a provider.
"""
import argparse
import json
import re
import shutil
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cog_core  # noqa: E402


def read(path):
    return json.loads(Path(path).read_text())


def replay_binding():
    """Binding identity for a result decided from saved answers: the code
    that decided, and a plain statement that no provider was called."""
    return {"kind": "replay", "cog": dict(cog_core.SELF_ID),
            "task_logic_sha256": cog_core.task_logic_sha256(),
            "machinery": cog_core.MACHINERY, "provider_called": False}


def saved_result(document):
    """Accept a bare turn result or envelope v1 without reconstructing it."""
    if isinstance(document, dict) and "envelope" in document:
        if type(document["envelope"]) is not int or document["envelope"] != 1:
            raise ValueError("Expected envelope v1")
        if document.get("ok") is not True:
            raise ValueError("Expected a successful envelope")
        if "provider_result" not in document:
            raise ValueError("Envelope has no validated provider_result; capture a new run")
        return document["provider_result"]
    return document


def export_fixtures(run_dir, step_id, name):
    """Copy one decision step's recorded inputs and results, never invoke it."""
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", name):
        raise ValueError("Fixture name must contain only letters, digits, _ or -")
    run_dir = Path(run_dir).resolve()
    track = read(run_dir / "track.json")
    steps = [step for step in track["steps"] if step["id"] == step_id]
    if len(steps) != 1:
        raise ValueError("Expected exactly one recorded step with that id")
    step = steps[0]
    if step.get("cog") != cog_core.SELF_ID:
        raise ValueError("Recorded step belongs to another Cog id or version")

    def recorded(path):
        if not isinstance(path, str):
            raise ValueError("Step has no recorded request or envelope")
        target = Path(path)
        target = (target if target.is_absolute() else run_dir / target).resolve()
        if not target.is_relative_to(run_dir):
            raise ValueError("Recorded file is outside the run directory; export from the original run location")
        return read(target)

    fixtures = []
    slots = step.get("elements")
    if slots is None:
        slots = [step]
    for slot in slots:
        if slot.get("repeats") is not None:
            raise ValueError("Repeated steps are not supported; select an unrepeated run")
        bundle = recorded(slot.get("request"))
        env = recorded(slot.get("envelope"))
        if env.get("cog") != cog_core.SELF_ID or env.get("ok") is not True:
            raise ValueError("Expected a successful envelope from this Cog")
        result = saved_result(env)
        cog_core.prepare(bundle)
        problems = cog_core.contract.result_problems(result, cog_core.questions_for(bundle))
        if problems:
            raise ValueError("Recorded provider result is invalid: " + problems[0])
        decision = env["payload"]["decision"]
        cog_core.Draft202012Validator(cog_core.OUTPUT_SCHEMA).validate(env["payload"])
        replayed = cog_core.finish(bundle, result, replay_binding())
        if not replayed.get("ok") or replayed["payload"]["decision"] != decision:
            raise ValueError("Replayed decision differs from the recorded decision")
        fixtures.append({"bundle": bundle, "result": result, "decision": decision})
    if not fixtures:
        raise ValueError("Step contains no recorded elements")
    parent = cog_core.ROOT / "tests" / "fixtures"
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / name
    if destination.exists():
        raise ValueError("Fixture set already exists")
    staging = Path(tempfile.mkdtemp(prefix=".fixture-", dir=parent))
    try:
        for index, fixture in enumerate(fixtures):
            element = staging / str(index)
            element.mkdir()
            for key, value in fixture.items():
                (element / (key + ".json")).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
        # The test lives with the fixtures; a discovery shim in tests imports it.
        test_source = '''import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

class TestRecordedDecisions(unittest.TestCase):
    def test_replay(self):
        cases = sorted(case for case in Path(__file__).parent.iterdir() if case.is_dir())
        self.assertTrue(cases, "No recorded elements to replay")
        for case in cases:
            with self.subTest(element=case.name):
                call = subprocess.run([sys.executable, str(ROOT / "src/cog_cli.py"),
                    "replay", "--bundle", str(case / "bundle.json"),
                    "--result", str(case / "result.json")],
                    cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(call.returncode, 0, call.stdout + call.stderr)
                env = json.loads(call.stdout)
                self.assertTrue(env["ok"], env)
                self.assertEqual(env["payload"]["decision"],
                    json.loads((case / "decision.json").read_text()))
'''
        (staging / "replay_test.py").write_text(test_source)
        shim = cog_core.ROOT / "tests" / ("test_fixture_" + name.replace("-", "_") + ".py")
        if shim.exists():
            raise ValueError("Generated test already exists")
        staging.chmod(parent.stat().st_mode & 0o777)
        staging.rename(destination)
        shim.write_text("import runpy\nfrom pathlib import Path\n"
                        + "TestRecordedDecisions = runpy.run_path(str(Path(__file__).parent / "
                        + repr("fixtures/" + name + "/replay_test.py")
                        + "))['TestRecordedDecisions']\n")
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return {"fixtures": len(fixtures), "path": str(destination)}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="cog_cli", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="package self-check")
    sub = parser.add_subparsers(dest="command")
    bridge = sub.add_parser("bridge", help="Workbench composition bridge")
    bridge.add_argument("operation", choices=["prepare", "finish"])
    bridge.add_argument("--request", required=True)
    prepare = sub.add_parser("prepare", help="print the System One turn for a bundle")
    prepare.add_argument("--bundle", required=True)
    replay = sub.add_parser("replay", help="decide from a saved System One result")
    replay.add_argument("--bundle", required=True)
    replay.add_argument("--result", required=True)
    export = sub.add_parser("export-fixtures", help="save an Op decision step as replay fixtures")
    export.add_argument("--run", required=True)
    export.add_argument("--step", required=True)
    export.add_argument("--name", required=True)
    derive = sub.add_parser("derive-schema", help="derive $defs.answers from questions.json")
    derive.add_argument("--write", action="store_true", help="rewrite the declared output schema")
    args = parser.parse_args(argv)

    if args.check:
        problems = cog_core.self_check()
        for p in problems:
            print(f"[{p['severity'].upper()}] {p['check']}: {p['detail']}")
        print("OK decision Cog self-check" if not problems else f"{len(problems)} problem(s)")
        return 1 if problems else 0

    try:
        if args.command == "bridge":
            document = read(args.request)
            if args.operation == "prepare":
                result = cog_core.prepare(document["bundle"])
            else:
                result = cog_core.finish(document["bundle"], document["result"], document["provenance"])
        elif args.command == "prepare":
            result = cog_core.prepare(read(args.bundle))["task"]
        elif args.command == "replay":
            result = cog_core.finish(read(args.bundle), saved_result(read(args.result)), replay_binding())
        elif args.command == "export-fixtures":
            result = export_fixtures(args.run, args.step, args.name)
        elif args.command == "derive-schema":
            result = cog_core.derived_output_schema()
            if args.write:
                target = cog_core.ROOT / (cog_core.MANIFEST.get("context") or {}).get(
                    "output_schema", "context/output-schema.json")
                target.write_text(json.dumps(result, indent=2) + "\n")
                print(f"wrote {target.relative_to(cog_core.ROOT)}", file=sys.stderr)
                return 0
        else:
            parser.print_help()
            return 2
        text = json.dumps(result, indent=2, allow_nan=False)
    except Exception as exc:  # noqa: BLE001 — task logic is author code
        # The bridge reports failures as data; Workbench and Ops record them
        # as invocation failures, never as decisions. Author-code errors and
        # non-finite numbers included: never a traceback, never NaN on stdout.
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"[:500]}))
        return 1
    print(text)
    if args.command == "bridge":
        return 0    # an envelope, even a failed one, is the bridge's answer
    return 0 if not isinstance(result, dict) or result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
