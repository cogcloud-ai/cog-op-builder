#!/usr/bin/env python3
"""Decision-Cog entry points (cog-smith decision-cog machinery, generic —
edit task_logic.py and context/, not this).

    pixi run check                                   # package self-check
    pixi run prepare -- --bundle examples/sample-bundle.json   # the turn, no call
    pixi run replay -- --bundle B.json --result R.json         # decide from saved answers
    pixi run derive-schema                           # $defs.answers from questions.json
    python src/cog_cli.py bridge prepare|finish --request DOC.json   # Workbench bridge

Live answers come only through `pixi run ask-composed` (a host-admitted
System One binding activated by Workbench). Nothing here selects a provider.
"""
import argparse
import json
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
            result = cog_core.finish(read(args.bundle), read(args.result), replay_binding())
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
