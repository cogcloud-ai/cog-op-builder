# Implementation and verification

## Ownership and boundaries

All required example source, fictional data and teaching material live in the
public coordinating repository. Dependencies are the suite's manifest-listed
Cog Smith and, for optional live use, Workbench and a System One provider. No
private source, profile, provider answers, credentials or private notes are used.

The three Cog packages and both Op packages were generated with the checked-out
Cog Smith corresponding to the suite manifest. Shared runtime files stay
byte-identical to its templates. Work is implemented only in author-owned
`task_logic.py`, schemas and scripts. The Op owns sequencing, Gates and recovery.
The learning client calls its entry points and formats results; it does not add
a second execution engine.

`fit/scripts/live_usage.py` is an explicit adapter for this nested example layout.
It checks the installed composition integrity, consumer path and Workbench host
fingerprint, then invokes Workbench's existing composition service. It does not
accept request-supplied provider commands or host paths.

## Contracts

- Prepare takes one to ten unique fictional opportunities, a company profile,
  and thresholds satisfying `0 <= review_at < pursue_at <= 1`.
- Fit asks two Noul questions. It takes their minimum and applies the thresholds.
  The model receives evidence and questions, but not thresholds.
- Shortlist requires exactly one assessment per opportunity, matches by id,
  checks titles, sorts by score descending with id as the tie-break, and proposes
  only `pursue` and `review` items. It never approves anything.
- Each proposed change hashes the supplied opportunity as the target and uses
  Cog Smith's canonical content hashing. The human decision binds to the exact
  pending payload. The shared runtime validates, records and applies it.
- There are no `reaches`, grants, independent Guards, external effects, or
  cross-run state. The “latest” pointer is only a convenience for selecting a
  run to inspect; no Cog uses it as task input.

## Synthetic answer provenance

The committed fixtures are authored teaching values, not recorded model answers.
They are matched against a SHA-256 of the entire prepared task: state plus
question set, using canonical sorted-key JSON, compact separators and UTF-8.
Changing a profile, opportunity or question refuses an old fixture. Changing
thresholds can reuse it because policy is intentionally absent from the task.

Replay binding records `provider_called: false` and
`fixture_source: hand-authored-synthetic`. The model field is
`synthetic-teaching-fixture-not-a-model`. The typed result uses `llm-adapter` as
its contract-compatible answer-source category; that field alone is not a claim
that an LLM was invoked. The mode label, model name and replay binding explain
its synthetic provenance.

The normal offline task is explicitly declared as a usage interface. Its default
status does not turn replay into live inference. The live task uses a separately
activated binding and never falls back to fixtures.

## Verification commands

From the learning example directory:

```sh
pixi install --locked
pixi run setup
pixi run check
pixi run test
```

Smith checks runtime-copy integrity and declared interfaces, and runs the native
package suites. Integration tests exercise real child processes and the shared
runtime. They cover human pause/restart/resume, explicit approval and rejection,
reuse of completed attempts, altered pending evidence, named preparation errors,
unknown fixture evidence, the alternate profile, policy-only changes and refusal
to substitute fixtures for unavailable live inference.

From the workspace, using Python 3.11 or newer:

```sh
python3 cog-op-builder/scripts/check_workspace.py
python3 cog-op-builder/scripts/verify.py
```

Full model-free verification includes the learning example. `--strict` is for a
clean checkout at the published manifest revisions; working changes use the
normal boundary check. No new boundary exceptions are needed.

## Limits

This teaches composition and inspectable decisions, not model accuracy. A
human-supplied `decided_by` is not authenticated identity. Trusted local package
code executes with the owner's authority. The example has no installed-package
catalog, GUI, real opportunity sources, documents, proposal writing, or release
publication. Those can be taught after the small workflow is understood.

Offline CLI tests import public Workbench and TypeSafe machinery from the
manifest-listed sibling checkouts. Install the suite before running them; live
providers and credentials are optional.
