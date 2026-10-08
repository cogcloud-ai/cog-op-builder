#!/usr/bin/env python3
"""CLI entry point for a code Cog (cog-smith machinery, generic — edit
task_logic.py, not this).

    pixi run run -- --bundle examples/sample-bundle.json
    pixi run run -- --bundle b.json --grant grant.json --run-id RUN \
                    --journal journal.jsonl
    pixi run check                  # what this Cog is and what it reaches

The Op runner passes `--grant`, `--run-id` and `--journal` when a step is
issued authority; a code Cog that declares `reaches` refuses to run without
a grant (error code `no-grant`). The grant is checked HERE, by this Cog,
before it reaches outside the run — the local host is not an enforced
restricted environment and must never be described as one.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cog_core  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(prog=cog_core.DEFAULT_TASK)
    ap.add_argument("--bundle", help="path to an input bundle (JSON)")
    ap.add_argument("--grant", help="path to this invocation's grant "
                                    "(openteams/op-grant [0.1])")
    ap.add_argument("--run-id", dest="run_id",
                    help="the Op run this invocation belongs to; a grant "
                         "bound to another run is refused")
    ap.add_argument("--journal", help="append-only JSONL record of external "
                                      "effects, read first and written as "
                                      "they happen")
    ap.add_argument("--check", action="store_true",
                    help="report identity, machinery and declared reaches")
    args = ap.parse_args(argv)

    if args.check:
        ok, detail = cog_core.health()
        print(("OK " if ok else "DOWN ") + detail)
        return 0 if ok else 1

    if not args.bundle:
        ap.error("--bundle is required (or use --check)")
    bundle = json.loads(Path(args.bundle).read_text())

    grant = None
    if args.grant:
        try:
            grant = cog_core.load_grant(args.grant)
        except (OSError, ValueError) as exc:
            print(json.dumps(cog_core._fail(
                cog_core.DEFAULT_TASK, "grant-invalid", str(exc)), indent=2))
            return 1
    journal = None
    if args.journal:
        # Creating the journal is the first thing that can fail with an
        # OSError, and it fails with a NAME: a Cog that cannot open the
        # record of its external effects prints a structured envelope, not a
        # traceback.
        try:
            journal = cog_core.Journal(args.journal)
        except OSError as exc:
            print(json.dumps(cog_core._fail(
                cog_core.DEFAULT_TASK, "journal-unreadable",
                f"{args.journal} cannot be created "
                f"({type(exc).__name__}: {exc}); a Cog that cannot open its "
                f"journal cannot record what it does outside the run, and "
                f"does nothing"), indent=2))
            return 1

    result = cog_core.invoke(bundle, grant=grant, journal=journal,
                             run_id=args.run_id)
    print(json.dumps(result, indent=2))
    if not result.get("ok"):
        return 1
    if result.get("problems"):
        print(f"\n{len(result['problems'])} problem(s) — ok with problems; "
              f"a gate (human or reviewer) decides.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
