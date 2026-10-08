"""The durable Track (`openteams/op-track [0.1]`) an Op run leaves behind.

Machinery master (cog-smith `templates/op/src/`) — never edited inside an Op
package. The Track is the run's record: the input request, every step
request, every Cog envelope unchanged, the contract-check problems the Cogs
reported, the Gate decision for each step, the model bindings those
envelopes carried, and the output artifacts. It is rewritten after every
step, so a crash leaves a readable partial Track.

Shape lifted from an earlier internal Op's track.json and extended with
step status, attempts, foreach elements, and repeats.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "openteams/op-track [0.1]"

DEFAULT_RECORDS = ["input_request", "step_requests", "cog_envelopes",
                   "contract_check_problems", "gate_decisions",
                   "model_bindings", "output_artifacts"]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def new_run_id():
    return (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + "-" + uuid.uuid4().hex[:8])


def contained(path, base):
    """PATH, checked to resolve INSIDE base through no link at all. The
    runner's own control files (the Track, grants, pending, decisions,
    journals) go through this.

    Two rules, because resolving alone is not enough:

    - the destination's parent must RESOLVE inside the run directory, so a
      link out of the run is refused rather than followed; and
    - no component of the path at or below the run directory may be a
      symlink, so an alias INSIDE the run (`outputs` -> `grants`) cannot
      make a step's output path address the runner's own control files. A
      path that reaches the run only by following a link from outside is
      refused for the same reason.

    This is application-level integrity, not host sandboxing: it keeps the
    runner from writing its own records somewhere else by accident or by a
    planted link — it does not confine the Cogs it invokes."""
    path, base = Path(path), Path(base).resolve()
    if path.is_symlink():
        raise ValueError(f"{path} is a symlink; the runner writes its own "
                         f"records, never through a link")
    parent = Path(os.path.abspath(str(path.parent)))
    resolved = parent.resolve()
    if resolved != base and base not in resolved.parents:
        raise ValueError(f"{path} resolves outside the run directory {base}; "
                         f"the runner's records stay inside the run")
    current, inside = Path(parent.anchor), False
    for part in parent.parts[1:]:
        current = current / part
        if inside:
            if current.is_symlink():
                raise ValueError(
                    f"{current} is a symlink inside the run directory "
                    f"{base}; the runner writes its own records to real "
                    f"directories, never through a link")
        elif current.resolve() == base:
            inside = True
    if not inside:
        raise ValueError(f"{path} reaches the run directory {base} only by "
                         f"following a link; the runner's records stay "
                         f"inside the run")
    return path


def _fsync_dir(path):
    """Persist a directory ENTRY. `os.replace` is atomic, but the rename
    itself is only durable once the containing directory is synced — without
    this, a power loss can lose a file the process was told it had written."""
    try:
        fd = os.open(str(path), getattr(os, "O_DIRECTORY", os.O_RDONLY))
    except OSError:                                    # pragma: no cover
        return
    try:
        os.fsync(fd)
    except OSError:                                    # pragma: no cover
        pass
    finally:
        os.close(fd)


def ensure_dir(path):
    """Create PATH and every missing ancestor DURABLY: each new directory's
    entry is fsynced in its own parent. `mkdir(parents=True)` alone leaves a
    newly created directory unpersisted, so a power loss could leave a
    durable Track pointing at a grants or journal directory that is not
    there."""
    path = Path(path)
    missing, probe = [], path
    while not probe.exists():
        missing.append(probe)
        if probe.parent == probe:                      # pragma: no cover
            break
        probe = probe.parent
    for directory in reversed(missing):
        directory.mkdir(exist_ok=True)
        _fsync_dir(directory.parent)
    return path


def touch_durable(path, base=None):
    """Create an empty file and persist its DIRECTORY ENTRY. The journal is
    created this way: the Track names it before anything external happens,
    so the entry has to survive the same power loss the Track does."""
    path = Path(path)
    if base is not None:
        contained(path, base)
    ensure_dir(path.parent)
    if not path.exists():
        fd = os.open(str(path), os.O_CREAT | os.O_WRONLY, 0o644)
        try:
            os.fsync(fd)
        except OSError:                                # pragma: no cover
            pass
        finally:
            os.close(fd)
        _fsync_dir(path.parent)
    return path


# `remove_durable` is GONE (machinery 0.6.6). 0.6.5 cleared a slot's envelope
# when the slot was reserved, because the path was derived from the slot index
# alone and an earlier attempt's file sat exactly where a recovery would look.
# The reservation and the deletion were two durable operations, not one: a
# crash between them left the new digests on the Track with the OLD answer on
# disk. 0.6.6 removes the reason instead of the
# file — every attempt owns an immutable path that names it, so nothing a run
# wrote is ever deleted or overwritten.


def write_atomic(path, text, base=None):
    """Write TEXT to PATH atomically and durably: a temporary sibling is
    written, flushed and fsynced, then replaces the destination in one step,
    and the containing directory is fsynced so the rename survives a power
    loss. An interrupted write leaves the earlier file exactly as it was.

    `base`, when given, is the run directory the destination must resolve
    inside — checked BEFORE anything is created, so a refused destination
    leaves no directories behind."""
    path = Path(path)
    if base is not None:
        contained(path, base)
    ensure_dir(path.parent)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def write_json(path, value, base=None):
    """Write one JSON document the same way `write_atomic` writes text."""
    return write_atomic(path, json.dumps(value, indent=2, ensure_ascii=False)
                        + "\n", base=base)


def new_track(spec, run_id, input_request, status="running"):
    return {
        "schema": SCHEMA,
        "op": {"id": spec.id, "version": spec.version},
        "run_id": run_id,
        "status": status,
        "started_at": utc_now(),
        "ended_at": None,
        "input_request": str(Path(input_request).resolve()),
        # Where the request was READ from: relative `$path` operands resolve
        # against it, so a resume must resolve them the same way the first
        # run did.
        "request_dir": None,
        "spec_sha256": spec.sha256(),
        "records": (spec.track or {}).get("records") or DEFAULT_RECORDS,
        # Authority: the admission this run was started with,
        # every grant it issued (scope and provenance, never a credential),
        # and every time a human resumed it. A resume entry carries `at`, the
        # `decision` it applied, the `changed_cogs` it is keeping results
        # from, and (0.6.5) `renewed_budgets`: the steps this resume bought a
        # new `until-required` repeat budget for, by name. No edit renews a
        # budget silently, so this list is the whole record of it.
        "authority": None,
        "grants": [],
        "resumes": [],
        # The step a stopping verdict ended the run at — the resume point of
        # a failed run. `None` while the run is live.
        "failed_step": None,
        "steps": [],
    }


#: Step statuses a Track carries. `not-reached` is a step the run never got
#: to because an earlier `on_fail: stop` ended it — recorded so a Track
#: always lists every step of the spec. `denied` is a step whose grant was
#: refused, so it was never invoked; `awaiting-decision` is a human-gated
#: step whose proposals are waiting for a person; `running` is a step a
#: crash interrupted, which a resume runs again.
STEP_STATUSES = ("passed", "passed-with-problems", "failed", "skipped",
                 "blocked", "planned", "not-reached", "denied", "running",
                 "awaiting-decision", "rejected")

#: Run statuses. `paused` is a run waiting on a human Gate; `rejected`
#: (machinery 0.7.0) is a run a person ended by refusing the artifact its
#: human Gate asked about — final, and never resumed.
RUN_STATUSES = ("planned", "running", "paused", "completed",
                "completed-with-problems", "failed", "rejected")


def step_record(step, status, **fields):
    """One step's record. Paths are absolute; unknown-to-this-run fields are
    present and null rather than absent, so a partial Track reads the same
    way as a complete one."""
    cog = step.get("cog") or {}
    record = {
        "id": step["id"],
        "status": status,
        "cog": {"id": cog.get("id"), "version": cog.get("version")},
        # The Cog's PACKAGE DIGEST at invocation (machinery 0.6.2): its
        # manifest, `context/`, `src/`, and the `model` and `response_format`
        # of an installed `model.json` — never the endpoint, never a
        # credential. A result belongs to a Cog as well as to a request, so a
        # resume reuses a passed repeat or element only when this matches too,
        # and a resume whose passed steps used another version says so in its
        # `changed_cogs`.
        #
        # Since 0.6.3 the digest is taken immediately before EVERY invocation
        # and recorded on the record that invocation produced: the repeat,
        # the element, and the entry in `attempts`. The step's own value here
        # summarises them — the Cog its LAST invocation ran under — and the
        # finer records are what a reader compares.
        "cog_sha256": None,
        "task": cog.get("task"),
        "request": None,
        "envelope": None,
        "binding": None,
        "problems": [],
        "gate": None,
        "elapsed_s": None,
        # One entry per invocation, in order:
        # `{attempt, envelope, request_sha256, cog_sha256, phase}` — which
        # invocation it was, the immutable file it owns, the question it put,
        # the digest of the Cog it put it to, and whether it reached an answer
        # (0.6.6; 0.6.3 wrote `{envelope, cog_sha256}` and only when
        # `retry-once` actually retried; before that, a bare list of paths).
        #
        # Since 0.6.6 `attempt` counts every invocation ever made for that
        # slot IN THIS RUN — a retry, a re-ask after a renewal, a re-run after
        # a changed request or Cog — and the envelope path names it, so
        # nothing a run wrote is ever overwritten and the record's own
        # `envelope` is simply the attempt that decided the slot.
        "attempts": [],
        # One record per `foreach` element, in element order. Each carries an
        # element-level `status`; since 0.6.2 a `foreach` stops at its first
        # finally-failed element, so the elements after it are `not-reached`:
        # nothing was built for them and nothing was paid for, and a resume
        # runs them for the first time.
        "elements": None,
        # Repetition (machinery 0.6.0): what the step DECLARED
        # (`{count, require, mode}`, null when it runs once) and what each
        # repeat of it actually did. On a `foreach` step the per-repeat
        # records live on each ELEMENT, and `repeats` here stays null. Since
        # 0.6.1 a repeat record names the request it answered
        # (`request_sha256`) and is written here as soon as it completes,
        # before the next repeat is invoked — a partial `running` record
        # already lists them. Under `mode: until-required` (0.6.4) `repeats`
        # holds only the repeats that RAN, so it can be shorter than `count`.
        #
        # Since 0.6.5 a repeat record carries a `phase`: it is written
        # `asking` — with its slot index, its `request_sha256` and its
        # `cog_sha256` and no gate — BEFORE the Cog is invoked, and rewritten
        # `answered` after. An `asking` record a crash left behind is a SPENT
        # attempt: the resume recovers its result from the envelope beside it
        # when that file is a valid envelope, and otherwise keeps the record
        # with a failing Gate and `spent: true` saying why. A record the
        # resume read back out of an envelope nobody had checkpointed carries
        # `recovered: true`, and since 0.6.6 every repeat record names the
        # `attempt` that decided it and lists every attempt of its slot.
        "repeat": None,
        "repeats": None,
        # The repeats a `--renew-budget` retired (0.6.6): off the ledger the
        # new budget is measured against, still on the Track, their envelopes
        # still on disk. Attempt numbering continues from them, so a renewed
        # slot never writes over the first budget's files. On a `foreach` step
        # this stays null and each ELEMENT carries its own.
        "retired_repeats": None,
        # Authority: the grant this step was issued, the
        # journal it recorded its external effects in, what it reported
        # attempting, and — for a human Gate — the decision it carries.
        "grant": None,
        "journal": None,
        "authority_use": None,
        "decision": None,
    }
    record.update(fields)
    return record


def save(track, run_dir):
    """Rewrite track.json; returns its absolute path."""
    path = Path(run_dir) / "track.json"
    write_json(path, track, base=run_dir)
    return str(path.resolve())
