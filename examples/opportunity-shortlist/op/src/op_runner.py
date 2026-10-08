#!/usr/bin/env python3
"""The Op runner: run the declared steps of this package's op.yaml.

    python src/op_runner.py --request examples/request.json [--dry-run]
                            [--runs-dir DIR] [--authority FILE]
    python src/op_runner.py --resume RUN_DIR [--decision FILE]
                            [--renew-budget STEP ...]

Machinery master (cog-smith `templates/op/src/`) — never edited inside an Op
package. The runner is the Op layer: it sequences steps, builds each step's
request from the spec's mapping expressions, invokes each Cog ONLY through
the usage task that Cog declares, gates the envelope it gets back, and
writes the durable Track. It never imports a Cog's Python and never calls a
model itself.

Gate semantics come from an earlier internal Op: three
states (pass, pass-with-problems, fail) with the reasons listed. The Gate
decides; the Cog never decides its own acceptance.

Authority: a step declares what it `requires`, the runner issues
the grant immediately before the invocation — from the run's admission
(`--authority`) for a read, and from a human Gate's decision for a write —
and passes `--grant`, `--run-id` and `--journal` to the Cog. The Cog checks
that grant itself before it reaches outside the run: this runner sequences
and records, it does not enforce a restricted environment.

A step with `gate: {policy: human}` pauses the run once its Cog has passed
the ordinary envelope Gate: the proposed changes are written to
`pending/<step>.json` (and a readable `.md`), the Track goes `paused`, and
the process exits 3. `--resume RUN_DIR --decision FILE` applies the human's
answer and carries on; steps that already passed are never re-run.

A human Gate says WHAT it asks about (machinery 0.7.0). `decides: changes`
— the default, and every human Gate before 0.7.0 — asks about a list of
proposed changes, each approved, rejected or edited, and feeds a write
grant. `decides: artifact` asks about ONE versioned thing — a contract the
step designed, a candidate the run built and reviewed — declared on the Gate
as `artifact: {kind, digests: {<name>: <expr>, ...}, id, summary, detail}`
and evaluated after the step's Cog answered, so it may read the step's own
payload. The pending document carries the artifact and its canonical
`artifact_sha256` beside the payload and `payload_sha256`; the decision names
BOTH digests and gives one `verdict`, `accept` or `reject`, with a `reason`.
An accepted artifact lets the run continue and exposes
`steps.<id>.decision` as `{verdict, artifact, artifact_sha256, reason,
decided_by, decided_at}`, so a later step can bind to exactly the digests
the person accepted. A REJECTED artifact ends the run: the step is recorded
`rejected`, the run `rejected`, and a rejected run is never resumed — a
rejection is a final decision about those bytes, and a different candidate
is a new run. An artifact the Gate cannot state — a digest expression that
reads a null contract, a digest that is not a sha256 — is a FAILED Gate with
the reasons named, never a pause asking a person to accept nothing; the
step is the run's `failed_step` and a resume runs it again. Completion of the
step whose Gate asks is review; only the decision is acceptance.

A step may declare `repeat: {count, require, mode}` (machinery 0.6.0): the SAME
request is invoked `count` times in sequence, each repeat gets its own Gate
decision, and the step's payload is the LIST of the repeat payloads (`null`
where a repeat's Gate failed). The step's Gate fails when fewer than
`require` repeats passed. Repetition is for steps that only read and only
propose: a step with `authority`, a human Gate, or a Cog that declares
`reaches` is refused at load. Each repeat is recorded with the
`request_sha256` of the request it answered, and is written to the Track
before the next one is invoked (0.6.1), so a resume reuses a passed repeat
only when it answered the question the step is asking now.

`repeat.mode` says how many of the `count` repeats actually run (0.6.4).
`all` — the default, and today's behaviour — runs
all `count` and unions the answers: for a step whose RECALL varies run to
run. `until-required` runs them one at a time and STOPS as soon as `require`
have passed, so `{count: 4, require: 1, mode: until-required}` costs one
invocation when the first answer is clean and fails the element only after
four rejected answers in a row. Its payload is the list of the repeats that
RAN — a repeat that never ran is absent, not null — and `count` is a budget
of attempts that holds across a resume: a reused pass counts toward
`require`, and a failed attempt already on the Track has spent its slot.

The budget is an ACCOUNT, and 0.6.5 is what makes it one. An attempt is
RESERVED before it is paid for: the record goes on the Track with
`phase: asking` before `invoke_cog`, and is completed after, so a crash in
that window leaves a record of the expenditure. A resume recovers that
attempt's result from its envelope when the file is there and is envelope v1,
and spends the slot when it is not — nothing refunds an attempt, and deleting
an envelope only makes an answer unreadable. In `until-required` `count` is
the ceiling on INVOCATIONS, so `retry-once` does not run inside a slot: the
NEXT slot is the retry. And spending is a ledger, not a cache: a changed Cog
or request invalidates the REUSE of earlier answers, never the record that
they were paid for, so a resume that finds a budget spent refuses that
element by name and `--renew-budget STEP` is the explicit, recorded
(`resumes[].renewed_budgets`) way to buy a new one after a fix.

Every attempt OWNS AN IMMUTABLE FILE (0.6.6). The envelope
path names its attempt — `envelopes/<step>[/<index>].r<slot>.a<attempt>.json`,
`attempt` counting every invocation ever made for that slot in this run — and
a reservation records the exact path it will write, so recovery reads only the
file that reservation named and an older attempt's answer can never be taken
for a newer one. Nothing a run wrote is ever deleted or overwritten; a retry
is an attempt like any other, reserved with its own digests and its own path
before it is invoked; and a renewal keeps the old attempts on the Track
(`retired_repeats`) and their files on disk, opening a new budget only.

A `foreach` STOPS at its first finally-failed element (0.6.2): when an
element's Gate is `fail` after its repeats and its retries are exhausted,
the loop ends, the step fails, and the remaining elements are recorded
`not-reached`. The completed elements and repeats stay on the Track and a
resume continues from the element that failed. This is the rule for every
`foreach`, whatever `on_fail` says — `on_fail` decides what a failed step
does to the run, not how many elements a failing step buys.

A result belongs to a Cog as well as to a request (0.6.2), and the digest
that says so is taken PER INVOCATION (0.6.3). Immediately before every
invocation — every element, every repeat, every retry attempt — the runner
digests the Cog it is about to invoke — its manifest, `context/`, `src/`, and
the `model` and `response_format` of an installed `model.json`, never the
endpoint and never a credential — and records that digest on the record the
invocation produced, so a binding or a code change mid-step can never sit
under one digest. A passed repeat or element is reused only when BOTH the
record's OWN digest and the request hash match what the step is asking now,
so one union never mixes two versions of a Cog or two models. A step that already PASSED is
never re-run for a changed Cog: the resume entry's `changed_cogs` records
which version produced what, and fix-and-resume keeps working.

A FAILED run resumes too: the step that stopped it — the one
the Track names in `failed_step` — is the resume point, so a Cog that
reports unfinished work (a write left uncertain, say) is re-run and finishes
it, and the steps after it then run for the first time. Steps that passed
are still never re-run.

One run, one process: `runs/<run_id>/run.lock` is locked with `flock` at the
start and on every resume, so two resumes of the same paused run cannot both
accept the decision and both write. The lock is the open DESCRIPTOR, held for
the process lifetime and inherited by every Cog this runner launches; a run
another process holds is refused by name (exit 2), and the kernel releases
the lock when the last holder exits — there is no pid to parse and no stale
lock to take over.

Durability order, so the Track on disk always says what was attempted before
anything external could happen: accept the decision → record the decision and
the resume, save → issue the grant, create the journal, record the step
`running`, save → invoke.

Exit codes: 0 completed (or completed-with-problems, or a planned dry run),
1 failed, 2 an invalid spec, request or authority document (and a run another
process holds), 3 paused for a human. Stdout is one JSON object.

A run validates every step's Cog declaration before it creates anything (so
a refused declaration leaves no run directory and no half-open Track), and a
run that stops records the steps it never reached as `not-reached`, so the
Track always lists every step of the spec.
"""
from __future__ import annotations

import argparse
import errno
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import op_spec    # noqa: E402
import op_track   # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------- the Cog seam ----

#: How much of a failed process's output is kept as evidence.
EVIDENCE_TAIL = 2000


def _tail(text):
    text = (text or "").strip()
    return text[-EVIDENCE_TAIL:]


def parse_envelope(stdout):
    """The last JSON object on stdout that looks like an envelope.

    A Cog may print progress before its result and may print the envelope
    pretty-printed over many lines (cog-smith's own context-cog machinery
    does), so this scans stdout for JSON objects rather than reading lines.
    """
    decoder = json.JSONDecoder()
    found = None
    index = stdout.find("{")
    while index != -1:
        try:
            value, end = decoder.raw_decode(stdout, index)
        except json.JSONDecodeError:
            index = stdout.find("{", index + 1)
            continue
        if isinstance(value, dict) and "envelope" in value:
            found = value
        index = stdout.find("{", max(end, index + 1))
    if found is None:
        raise ValueError("Cog command did not emit a JSON envelope")
    return found


#: Request-file flags the seam will try, in order. `--request` is the seam's
#: flag; `--bundle` is the flag cog-smith's own context-cog machinery gives a
#: created Cog, so an Op must be able to call one.
REQUEST_FLAGS = ("--request", "--bundle")

#: argparse's exit code for a command line it could not parse.
ARGPARSE_EXIT = 2


def _rejected_flag(completed, flag):
    """True when the Cog's CLI refused FLAG by name WITHOUT DOING ANY WORK,
    so trying the next flag cannot run an effectful Cog twice.

    Three conditions, all required: argparse's own exit code (2), the
    diagnostic on STDERR (where argparse writes it) naming this exact flag,
    and no envelope anywhere on stdout. An exit-1 envelope whose error detail
    happens to quote "unrecognized arguments: --request" is a RESULT, not a
    rejection — the Cog already ran."""
    if completed.returncode != ARGPARSE_EXIT:
        return False
    if f"unrecognized arguments: {flag}" not in (completed.stderr or ""):
        return False
    try:
        parse_envelope(completed.stdout or "")
    except ValueError:
        return True
    return False                 # it produced a result: never re-invoke


def envelope_problems(value):
    """Why VALUE is not an envelope v1 the Gate can decide about. Field TYPES
    are checked, not merely field presence: an `ok` that is the string
    "false", or `problems` that are bare strings, are malformed output, not a
    result — they become a controlled invocation failure with the output kept
    as evidence."""
    if not isinstance(value, dict):
        return ["the Cog's result is not a JSON object."]
    problems = []
    version = value.get("envelope")
    if type(version) is not int or version != 1:
        # `type(x) is int`, not isinstance: True == 1 in Python, and
        # `{"envelope": true}` is malformed output, not envelope v1.
        problems.append(f"the Cog's result declares envelope "
                        f"{version!r}, not envelope v1.")
    if not isinstance(value.get("ok"), bool):
        problems.append(f"the Cog's result declares ok {value.get('ok')!r}, "
                        f"which is not true or false.")
    listed = value.get("problems")
    if not isinstance(listed, list) or any(not isinstance(p, dict)
                                           for p in listed):
        # `problems` is REQUIRED: missing or null is malformed, not an empty
        # list the Gate may assume.
        problems.append("the Cog's result declares problems that are not a "
                        "list of problem objects.")
    return problems


def failed_envelope(cog_dir, task, detail, raw=None, carried=None,
                    evidence=None):
    """A synthetic ok:false envelope for an invocation that never produced a
    usable result. What the Cog did emit is kept in `raw` as evidence; when
    that output was a well-formed envelope, its identity, binding and
    problems are carried across rather than thrown away.

    `error.evidence` is the ONE place process evidence lives, on EVERY
    synthetic failure: `{command, returncode, stdout_tail, stderr_tail}` and,
    when the seam tried the other request flag first, `previous_attempts`
    with the same fields (BUILDING_OPS, "When a Cog invocation fails")."""
    carried = carried if isinstance(carried, dict) else {}
    return {
        "envelope": 1,
        "cog": carried.get("cog") or {"id": f"unavailable:{Path(cog_dir).name}",
                                      "version": None},
        "task": task,
        "ok": False,
        "error": {"code": "invocation-failed", "detail": detail,
                  "evidence": evidence},
        "payload": None,
        "raw": raw,
        "problems": [p for p in carried.get("problems") or []
                     if isinstance(p, dict)],
        "binding": carried.get("binding"),
        "timing": {"latency_s": 0},
    }


def _evidence(command, returncode, stdout, stderr, previous):
    """One attempt's process evidence: what was run, how it exited, and the
    tail of each stream. Captured once, kept on every synthetic failure."""
    record = {
        "command": list(command),
        "returncode": returncode,
        "stdout_tail": _tail(stdout),
        "stderr_tail": _tail(stderr),
    }
    if previous:
        record["previous_attempts"] = list(previous)
    return record


def invoke_cog(cog_dir, task, request_path, grant_path=None, run_id=None,
               journal_path=None):
    """Run one declared Cog task and return its envelope.

    `grant_path`, `run_id` and `journal_path` are the invocation context a
    granted step gets: they are passed as `--grant`, `--run-id`
    and `--journal` BESIDE the request, never inside it, and only for a step
    the runner issued a grant to.

    Anything short of a well-formed envelope from a process that exited 0 is
    an invocation failure with a synthetic ok:false envelope, so the Gate
    always has something to decide about: a command that could not be
    launched, a nonzero exit (even after printing an envelope — a process
    that dies at 139 has not succeeded), output with no envelope, and a
    malformed envelope all arrive the same way.

    The run lock's descriptor is passed to the child (`pass_fds`): while a
    Cog is running, the run stays locked even if this runner dies."""
    cog_dir = Path(cog_dir)
    inherited = tuple(fd for fd in (LOCK_FD,) if fd is not None)
    previous = []
    context = []
    if grant_path:
        context += ["--grant", str(grant_path)]
    if run_id:
        context += ["--run-id", str(run_id)]
    if journal_path:
        context += ["--journal", str(journal_path)]
    for index, flag in enumerate(REQUEST_FLAGS):
        command = [
            "pixi", "run", "--manifest-path", str(cog_dir / "pixi.toml"),
            task, "--", flag, str(request_path), *context,
        ]
        try:
            completed = subprocess.run(command, text=True, capture_output=True,
                                       pass_fds=inherited)
        except OSError as exc:
            return failed_envelope(
                cog_dir, task,
                f"could not launch {command[0]!r} for task {task!r}: {exc}",
                evidence=_evidence(command, None, "", "", previous))
        if (not _rejected_flag(completed, flag)
                or index == len(REQUEST_FLAGS) - 1):
            break
        # The CLI refused this flag before doing any work; the next flag is
        # tried, and this attempt stays as evidence.
        previous.append(_evidence(command, completed.returncode,
                                  completed.stdout, completed.stderr, []))
    stdout = completed.stdout or ""
    stderr = (completed.stderr or "").strip()
    evidence = _evidence(command, completed.returncode, stdout, stderr,
                         previous)
    try:
        envelope = parse_envelope(stdout)
    except ValueError as exc:
        detail = stderr or stdout.strip() or str(exc)
        return failed_envelope(cog_dir, task, detail, raw=stdout,
                               evidence=evidence)
    malformed = envelope_problems(envelope)
    if malformed:
        return failed_envelope(cog_dir, task, " ".join(malformed), raw=envelope,
                               evidence=evidence)
    if completed.returncode != 0:
        detail = (f"the Cog command for task {task!r} exited "
                  f"{completed.returncode}")
        if stderr:
            detail += f": {stderr[-400:]}"
        return failed_envelope(cog_dir, task, detail, raw=envelope,
                               carried=envelope, evidence=evidence)
    return envelope


def gate_envelope(envelope):
    """The Gate: a three-state decision over one envelope, with reasons."""
    reasons = []
    malformed = envelope_problems(envelope)
    if malformed:
        # The Gate decides about envelope v1 and nothing else: a result whose
        # required fields are the wrong TYPE never reaches the policy.
        return {
            "policy": op_spec.GATE_POLICY, "status": "fail",
            "reasons": ["Cog result is not envelope v1."] + malformed,
            "decided_at": op_track.utc_now(), "guards": [],
        }
    if envelope.get("ok") is not True:
        error = envelope.get("error") or {}
        error = error if isinstance(error, dict) else {}
        reasons.append(
            f"Cog invocation failed: {error.get('code', 'unknown')}: "
            f"{error.get('detail', '')}".rstrip())
    # `envelope_problems` above has already established that `problems` is a
    # list of objects: the policy reads it without re-checking its type.
    listed = envelope.get("problems") or []
    error_problems = [p for p in listed if p.get("severity") == "error"]
    reasons.extend(str(p.get("detail") or p.get("check")
                       or "contract check failed") for p in error_problems)
    if reasons:
        status = "fail"
    elif listed:
        status = "pass-with-problems"
        reasons = [str(p.get("detail") or p.get("check")) for p in listed]
    else:
        status = "pass"
    return {
        "policy": op_spec.GATE_POLICY,
        "status": status,
        "reasons": reasons,
        "decided_at": op_track.utc_now(),
        "guards": [],
    }


def combine_gates(gates):
    """One Gate decision over a foreach step's per-element decisions."""
    statuses = [g["status"] for g in gates]
    if "fail" in statuses:
        status = "fail"
    elif "pass-with-problems" in statuses:
        status = "pass-with-problems"
    else:
        status = "pass"
    reasons = [f"element {i}: {reason}"
               for i, gate in enumerate(gates) for reason in gate["reasons"]]
    return {
        "policy": op_spec.GATE_POLICY,
        "status": status,
        "reasons": reasons,
        "decided_at": op_track.utc_now(),
        "guards": [],
    }


def combine_repeat_gates(gates, require):
    """One Gate decision over the repeats of a step, or of one `foreach`
    element.

    `fail` when fewer than `require` repeats passed — the step did not get
    the evidence it asked for; otherwise `pass-with-problems` when any repeat
    failed or carried problems, because a run that needed three answers and
    got two is a result with a caveat, not a clean pass; otherwise `pass`."""
    passed = [g for g in gates if g["status"] != "fail"]
    reasons = [f"repeat {i}: {reason}"
               for i, gate in enumerate(gates) for reason in gate["reasons"]]
    if len(passed) < require:
        status = "fail"
        reasons.insert(0, f"{len(passed)} of {len(gates)} repeats passed; "
                          f"{require} required.")
    elif len(passed) < len(gates) or any(g["status"] == "pass-with-problems"
                                         for g in passed):
        status = "pass-with-problems"
    else:
        status = "pass"
    return {
        "policy": op_spec.GATE_POLICY,
        "status": status,
        "reasons": reasons,
        "decided_at": op_track.utc_now(),
        "guards": [],
    }


STEP_STATUS = {"pass": "passed", "pass-with-problems": "passed-with-problems",
               "fail": "failed"}


# ----------------------------------------------- the authority documents --
#
# Three documents, all validated by their `schema` string BY NAME. None of
# them carries a credential, and none of them can be built by a mapping
# expression: authority is trusted invocation context, separate from the
# request document.

AUTHORITY_SCHEMA = "openteams/op-authority [0.1]"
GRANT_SCHEMA = "openteams/op-grant [0.1]"
PENDING_SCHEMA = "openteams/op-pending-decision [0.1]"
DECISION_SCHEMA = "openteams/op-decision [0.1]"
VERDICTS = ("approve", "reject", "edit")
#: The verdicts of a decision about an ARTIFACT (machinery 0.7.0): one
#: thing, taken whole or refused whole. There is no edit — an edited
#: artifact is a different artifact, with different digests, and is decided
#: about by the run that produces it.
ARTIFACT_VERDICTS = ("accept", "reject")

#: The exit code of a run that paused for a human.
PAUSED_EXIT = 3


class Denied(Exception):
    """Why a step was denied its grant. The step is recorded `denied` and
    never invoked; `on_fail` then applies as it does for a failure."""


#: One run, one process. Two resumes of the same paused
#: run would each accept the decision, issue the same grant, read the same
#: empty journal, and apply the same change twice: atomically replacing the
#: Track orders the WRITES, not the executions. The lock does.
LOCK_NAME = "run.lock"

#: The open descriptor of the lock this process holds, if any. It is passed
#: to every Cog subprocess (`pass_fds`), so the lock outlives a runner that
#: dies with a Cog still running: the kernel drops it only when the LAST
#: holder exits.
LOCK_FD = None


class RunLock:
    """An advisory `flock` on one run directory's `run.lock`, held for the
    process lifetime — taken BEFORE the Track is read, so two processes
    cannot even reach the same decision.

    The lock is the OPEN DESCRIPTOR, not the file's content: there is no pid
    to parse, nothing to take over, and nothing to unlink. A process that
    dies releases it because the kernel closes its descriptors; a process
    that is alive holds it because the kernel says so. The file's JSON (pid,
    time) is INFORMATIONAL — it says who to look for, and is never the
    thing consulted to decide.

    The lock FILE is a control file like the Track: contained in the run
    and opened `O_NOFOLLOW`, so it is never a link to something else.

    The descriptor is inherited by every Cog this runner launches, so a
    runner killed mid-invocation keeps the run locked until its Cog is
    finished too: the lock protects the whole execution, including an
    outstanding external effect."""

    def __init__(self, run_dir):
        self.run_dir = Path(run_dir)
        self.path = self.run_dir / LOCK_NAME
        self.fd = None
        self.held = False

    def acquire(self):
        """Take the lock, then say who holds it.

        The lock file is a CONTROL FILE, opened like every other one: the
        path is contained in the run directory (no link out, no alias
        inside), and the open itself is `O_NOFOLLOW`, so `run.lock` pointing
        at `track.json` is refused rather than followed and truncated.
        Containment is checked before
        the descriptor exists; `O_NOFOLLOW` closes the window between the
        check and the open.

        The metadata is written only AFTER the lock is held, and a failure
        while writing it releases the descriptor before re-raising: an
        embedding process that catches the exception is not left holding a
        lock it does not know about."""
        global LOCK_FD
        op_track.ensure_dir(self.path.parent)
        try:
            op_track.contained(self.path, self.run_dir)
        except ValueError as exc:
            raise op_spec.OpSpecError(
                f"the run lock {self.path} is not a real file inside the run "
                f"({exc}); the lock is a control file of the run and is "
                f"never opened through a link.")
        try:
            fd = os.open(str(self.path),
                         os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o644)
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.EMLINK):
                raise op_spec.OpSpecError(
                    f"{self.path} is a symlink; the run lock is a control "
                    f"file of the run and is never opened through a link.")
            raise
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            holder = self._holder(fd)
            os.close(fd)
            raise op_spec.OpSpecError(
                f"run {self.path.parent.name} is already running as pid "
                f"{holder.get('pid')} (since {holder.get('at')}); one run, "
                f"one process — wait for that process to finish.")
        self.fd, self.held, LOCK_FD = fd, True, fd
        try:
            os.ftruncate(fd, 0)
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, json.dumps({"pid": os.getpid(),
                                     "at": op_track.utc_now()}).encode("utf-8"))
            try:
                os.fsync(fd)
            except OSError:                            # pragma: no cover
                pass
        except BaseException:
            self.release()
            raise
        return self

    def _holder(self, fd):
        """Who the lock file SAYS is running. Informational only: a lock
        file that is empty, truncated or not JSON at all still locks."""
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            value = json.loads(os.read(fd, 4096).decode("utf-8", "replace"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def release(self):
        """Close the descriptor; the kernel releases the lock when the last
        holder — this process or a Cog that inherited it — is gone. The file
        stays: unlinking it would let a second process create a NEW file and
        lock that instead."""
        global LOCK_FD
        if self.fd is not None:
            if LOCK_FD == self.fd:
                LOCK_FD = None
            os.close(self.fd)
            self.fd, self.held = None, False

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
        return False


#: How much of a file is held in memory while it is hashed (machinery
#: 0.6.3). A digest must not depend on a file fitting in RAM: a Cog's
#: `context/` can carry a fixture of any size, and a whole-file read made
#: the cost of an invocation a function of the largest file in the package.
DIGEST_CHUNK_BYTES = 1 << 20


def sha256_file(path, chunk_bytes=DIGEST_CHUNK_BYTES):
    """The digest of a file, read in chunks rather than whole. The result is
    hashlib over the same bytes — the chunking is about memory, never about
    what is hashed."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk_bytes), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value):
    """The hash of a JSON value, canonically serialized — the same bytes for
    the same document however it was written."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


#: The manifest a Cog package may carry, in the order they are read. Both
#: are hashed when both are there: which one a Cog declares in is a profile
#: matter, and the digest is about what changed, not about which file.
COG_MANIFESTS = ("pixi.toml", "cog.yaml")

#: The directories whose every file is part of a Cog's package digest: its
#: context (prompts, schemas, fixtures the Cog reads) and its source.
COG_DIGEST_DIRS = ("context", "src")

#: What of an installed binding belongs to a RESULT's identity. `model.json`
#: is gitignored installation state and carries the endpoint and the name of
#: the credential's environment variable; neither is part of what produced an
#: answer, and neither is ever hashed here. The model that answered, and the
#: response format it was asked for, are.
BINDING_DIGEST_KEYS = ("model", "response_format")

#: Directory names the digest walk never descends into (machinery 0.6.3).
#: `__pycache__` holds build products of files already hashed; `.pixi` holds
#: an INSTALLED ENVIRONMENT — gigabytes of third-party files that are not the
#: Cog, and whose presence would make the digest a function of whether
#: anyone had run `pixi install` in that package yet.
COG_DIGEST_SKIP_DIRS = ("__pycache__", ".pixi")


def _digest_entries(base, cog_dir):
    """`[relative path, file digest]` for every file under BASE that belongs
    to the package (machinery 0.6.3).

    The walk NEVER follows a symlink — not a file symlink, not a directory
    symlink. A symlink points outside what this package is; following one
    would let a link's target decide a Cog's identity, and a directory
    symlink can also make the walk unbounded or cyclic. A link is skipped
    rather than hashed by name, so what the digest covers stays "the files
    this package carries"."""
    entries = []
    for root, dirnames, filenames in os.walk(base, followlinks=False):
        here = Path(root)
        dirnames[:] = sorted(name for name in dirnames
                             if name not in COG_DIGEST_SKIP_DIRS
                             and not (here / name).is_symlink())
        for name in sorted(filenames):
            path = here / name
            if path.is_symlink() or path.suffix == ".pyc" or not path.is_file():
                continue
            entries.append([path.relative_to(cog_dir).as_posix(),
                            sha256_file(path)])
    return entries


def cog_package_sha256(cog_dir):
    """The digest of the Cog a step invokes, taken immediately before THAT
    invocation (machinery 0.6.3).

    A result belongs to a Cog as well as to a request: two answers are
    evidence of the same thing only when the same Cog produced them. The
    digest covers the Cog's manifest, every file under `context/` and `src/`
    by sorted relative path, and — when an installation left a `model.json` —
    ONLY the `model` and `response_format` it names.

    It never covers the endpoint or `api_key_env`: relocating a served model
    does not change what answered, and a credential's name has no business in
    a Track. `__pycache__`, `.pyc` and `.pixi` are excluded and symlinks are
    skipped (`_digest_entries`); files are read in chunks, never whole, so a
    large fixture costs time and not memory.

    A Cog that is not present on this machine digests as the empty package —
    deterministically, so a run and its resume agree about it."""
    cog_dir = Path(cog_dir)
    files = []
    for name in COG_MANIFESTS:
        path = cog_dir / name
        if path.is_file() and not path.is_symlink():
            files.append([name, sha256_file(path)])
    for folder in COG_DIGEST_DIRS:
        base = cog_dir / folder
        if not base.is_dir() or base.is_symlink():
            continue
        files.extend(_digest_entries(base, cog_dir))
    files.sort()
    binding = None
    model_json = cog_dir / "model.json"
    if model_json.is_file():
        try:
            installed = json.loads(model_json.read_text())
        except (OSError, ValueError):
            installed = None
        if not isinstance(installed, dict):
            installed = {}
        binding = {key: installed.get(key) for key in BINDING_DIGEST_KEYS}
    return canonical_sha256({"files": files, "binding": binding})


#: A change carries TWO hashes, and they answer different questions.
#: `content_sha256` is the hash of the change OBJECT — what
#: the human approved, recomputed on an edit, checked by the runner at
#: issuance. `target_sha256` is the content hash of the TARGET ITEM as the Op
#: read it — the staleness precondition the write Cog checks against a fresh
#: fetch, and which an edit never changes. Neither may be null.
CHANGE_HASHES = ("content_sha256", "target_sha256")


def change_content_sha256(change):
    """The content hash of a proposed change: everything about it EXCEPT the
    two hash fields. An edited change is re-hashed with this, and that is
    what the write grant carries as `content_sha256`."""
    return canonical_sha256({k: v for k, v in change.items()
                             if k not in CHANGE_HASHES})


#: A content hash is 64 hexadecimal characters. Checked, not assumed: a
#: grant that carried `target_sha256: "yes"` would authorize a write whose
#: staleness precondition no fetch can ever match — or, worse, one a Cog
#: comparing loosely would treat as satisfied.
#: `fullmatch`, never `match`: with `re.match`, `"<64 hex>\n"` passed —
#: `$` also matches before a trailing newline, so a digest with a newline
#: glued to it was accepted as a content hash.
HEX64 = re.compile(r"[0-9a-f]{64}")


def hex64_problem(value, field, where):
    """Why VALUE is not a content hash, or None."""
    if not isinstance(value, str) or not value:
        return (f"{where} carries {field} {value!r}; a change carries both "
                f"hashes, and neither may be null")
    if not HEX64.fullmatch(value):
        return (f"{where} carries {field} {value!r}, which is not a sha256 "
                f"(64 hex characters)")
    return None


def _document(path, schema, what):
    doc = op_spec.load_document(path)
    if not isinstance(doc, dict):
        raise op_spec.OpSpecError(f"{Path(path).name} is not a {what} "
                                  f"document.")
    if doc.get("schema") != schema:
        raise op_spec.OpSpecError(
            f"{Path(path).name} declares schema {doc.get('schema')!r}; a "
            f"{what} is {schema!r}.")
    return doc


def load_authority(path):
    """The run's ADMISSION: the owner's authority for the whole run, in the
    same operation shape as a grant. `write` operations carry the
    repositories writes may EVER touch — never change ids, which only a
    human decision can name."""
    doc = _document(path, AUTHORITY_SCHEMA, "run admission")
    operations = doc.get("operations")
    problems = []
    if not isinstance(operations, list) or not operations:
        raise op_spec.OpSpecError(
            f"{Path(path).name} admits no operations; a run admission is a "
            f"list of {{resource, action, repositories}} operations.")
    for index, operation in enumerate(operations):
        where = f"the admission's operations[{index}]"
        if not isinstance(operation, dict):
            problems.append(f"{where} must be an object.")
            continue
        for field in ("resource", "action"):
            if not isinstance(operation.get(field), str) or not operation[field]:
                problems.append(f"{where} declares {field} "
                                f"{operation.get(field)!r}; it is a string.")
        repositories = operation.get("repositories")
        if not isinstance(repositories, list) or any(
                not isinstance(r, str) for r in repositories):
            problems.append(f"{where} declares repositories "
                            f"{repositories!r}; an admitted operation names "
                            f"the repositories it may touch.")
        if "changes" in operation:
            problems.append(f"{where} names changes; an admission admits "
                            f"repositories, and only a human decision names "
                            f"change ids.")
    if problems:
        raise op_spec.OpSpecError(problems)
    return doc


def admitted_repositories(authority, resource, action):
    """The repositories the run was admitted to touch for one operation."""
    out = set()
    for operation in (authority or {}).get("operations") or []:
        if (operation.get("resource") == resource
                and operation.get("action") == action):
            out |= {r for r in operation.get("repositories") or []}
    return out


def admission_problems(spec, authority):
    """Why this run may not start: a step requires authority the run was
    never admitted to have. Refused at LOAD, before anything is created."""
    problems = []
    for step in spec.ordered:
        for requirement in op_spec.requirements(step):
            if not isinstance(requirement, dict):
                continue
            resource = requirement.get("resource")
            action = requirement.get("action")
            if authority is None:
                problems.append(
                    f"step {step['id']!r} requires {resource} {action}; the "
                    f"run was admitted with none (pass --authority FILE).")
            elif not any(o.get("resource") == resource
                         and o.get("action") == action
                         for o in authority.get("operations") or []):
                problems.append(
                    f"step {step['id']!r} requires {resource} {action}, which "
                    f"this run's admission does not carry.")
    return problems


# ------------------------------------------------------------- the grant --

def grant_document(step, run_id, operations, provenance, ttl_minutes,
                   cog_version=None, index=0):
    expires = (datetime.now(timezone.utc)
               + timedelta(minutes=float(ttl_minutes)))
    sid = step["id"]
    return {
        "schema": GRANT_SCHEMA,
        "grant_id": f"{run_id}/{sid}/{index}",
        "run_id": run_id,
        "recipient": {"step": sid,
                      "cog": {"id": (step.get("cog") or {}).get("id"),
                              "version": cog_version
                              or (step.get("cog") or {}).get("version")}},
        "issued_at": op_track.utc_now(),
        "issued_by": provenance,
        "operations": operations,
        "valid": {"expires_at": expires.isoformat(), "run_id": run_id},
    }


def _change_id(value):
    """The change id of a requested entry, as a STRING, or None. A list- or
    object-valued id is not an id: it is refused by name rather than raising
    an unhashable-value error inside a set lookup."""
    cid = value.get("change_id") if isinstance(value, dict) else value
    return cid if isinstance(cid, str) and cid else None


def granted_change(change):
    """What a grant carries about one approved change: its id, the
    repository it touches, and BOTH hashes. Every field is required and none
    may be null — a grant that fails open on a hash authorizes anything."""
    entry = {"change_id": change.get("change_id"),
             "repository": change.get("repository")}
    for field in CHANGE_HASHES:
        entry[field] = change.get(field)
    return entry


def _next_grant_index(run_dir, sid):
    """The next issuance number for this step. Every issuance gets its OWN
    id and file: a reissue after an interruption never overwrites the grant
    an earlier Track entry points at."""
    directory = Path(run_dir) / "grants" / sid
    index = 0
    while (directory / f"{index}.json").exists():
        index += 1
    return index


def cog_version(step, package_root):
    """The recipient's version: the spec's when it states one, otherwise the
    version the Cog's own manifest declares — a grant names the recipient it
    has, never a null it could have read."""
    declared = (step.get("cog") or {}).get("version")
    if declared:
        return declared
    source = (step.get("cog") or {}).get("source")
    if not package_root or not isinstance(source, str):
        return None
    manifest, _ = op_spec.read_cog_manifest(Path(package_root) / source)
    return (manifest or {}).get("version")


def issue_grant(step, context, authority, spec, run_id, run_dir, decisions,
                package_root=None):
    """The grant for a step that requires authority, written into the run.

    Raises `Denied` with the reason when the run's admission does not cover
    a read, or when a write asks for anything the human did not approve.
    Requesting more than was approved is a DENIAL, never a trim."""
    declared = op_spec.requirements(step)
    if not declared:
        return None, None
    sid = step["id"]
    operations, provenance = [], {"kind": "admission"}
    for requirement in declared:
        resource = requirement.get("resource")
        action = requirement.get("action")
        if action == "write":
            target = op_spec.decision_step(requirement)
            record = (decisions or {}).get(target)
            if not record:
                raise Denied(f"step {sid!r} requires a {resource} write "
                             f"authorized by step {target!r}, which produced "
                             f"no human decision")
            path = record.get("decision")
            if not path or not Path(path).exists():
                raise Denied(f"the decision record for step {target!r} is "
                             f"missing; no write grant can be issued")
            if sha256_file(path) != record.get("decision_sha256"):
                raise Denied(f"the decision record {Path(path).name} changed "
                             f"since the Track recorded it; no write grant "
                             f"can be issued")
            approved = {c["change_id"]: c
                        for c in record["value"].get("approved") or []
                        if isinstance(c, dict) and _change_id(c)}
            requested = op_spec.evaluate(requirement.get("changes"), context)
            if requested is not None and not isinstance(requested, list):
                raise Denied(f"step {sid!r} requires a write of {requested!r}, "
                             f"which is not a list of changes")
            for change in requested or []:
                cid = _change_id(change)
                if cid is None:
                    raise Denied(f"step {sid!r} requires a write for "
                                 f"{change!r}, which names no change id")
                if cid not in approved:
                    raise Denied(f"step {sid!r} requires a write for change "
                                 f"{cid!r}, which the human did not approve")
                if isinstance(change, dict) and change.get("content_sha256") \
                        != approved[cid].get("content_sha256"):
                    raise Denied(f"change {cid!r} was approved against other "
                                 f"content than the one requested")
            admitted = admitted_repositories(authority, resource, "write")
            for cid, change in approved.items():
                repository = change.get("repository")
                if not isinstance(repository, str) or repository not in admitted:
                    raise Denied(f"change {cid!r} targets repository "
                                 f"{repository!r}, which this run was not "
                                 f"admitted to write")
                for field in CHANGE_HASHES:
                    problem = hex64_problem(change.get(field), field,
                                            f"change {cid!r}")
                    if problem:
                        raise Denied(problem)
                # The runner recomputes what it is about to authorize: the
                # grant's `content_sha256` is the hash of THIS object, not a
                # digest copied along with it.
                recomputed = change_content_sha256(change)
                if change["content_sha256"] != recomputed:
                    raise Denied(f"change {cid!r} carries content_sha256 "
                                 f"{change['content_sha256']!r}, but its "
                                 f"content hashes to {recomputed!r}; the "
                                 f"approved change is not the one recorded")
            # EXACTLY the approved list, never the requested one.
            operations.append({
                "resource": resource, "action": "write",
                "changes": [granted_change(c)
                            for c in record["value"].get("approved") or []],
            })
            provenance = {"kind": "gate", "step": target,
                          "decision": str(Path(path).resolve()),
                          "decision_sha256": record.get("decision_sha256")}
        else:
            requested = op_spec.evaluate(requirement.get("repositories"),
                                         context) or []
            if not isinstance(requested, list) or any(
                    not isinstance(r, str) for r in requested):
                raise Denied(f"step {sid!r} requires {resource} {action} of "
                             f"{requested!r}, which is not a list of "
                             f"repositories")
            admitted = admitted_repositories(authority, resource, action)
            outside = [r for r in requested if r not in admitted]
            if outside:
                raise Denied(f"step {sid!r} requires {resource} {action} of "
                             f"{outside}, which this run's admission does not "
                             f"cover")
            operations.append({"resource": resource, "action": action,
                               "repositories": list(requested)})
    index = _next_grant_index(run_dir, sid)
    grant = grant_document(step, run_id, operations, provenance,
                           spec.ttl_minutes,
                           cog_version=cog_version(step, package_root),
                           index=index)
    path = Path(run_dir) / "grants" / sid / f"{index}.json"
    op_track.write_json(path, grant, base=run_dir)
    return grant, path


def grant_record(grant, path):
    """What the Track keeps about a grant: its scope and its provenance —
    never a credential, because a grant carries none."""
    return {
        "grant_id": grant["grant_id"],
        "step": grant["recipient"]["step"],
        "path": str(Path(path).resolve()),
        "operations": [{"resource": o.get("resource"),
                        "action": o.get("action"),
                        "count": len(o.get("repositories")
                                     or o.get("changes") or [])}
                       for o in grant["operations"]],
        "issued_by": grant["issued_by"],
    }


# -------------------------------------------------------- the human gate --

def pending_changes(payload, sid):
    """The proposed changes in a human-gated step's payload.

    Change ids are unique STRINGS. Two proposals sharing an id would collapse
    into one entry the moment they were indexed, so one approval would
    silently authorize both: a duplicate refuses the pause.

    HASHES ARE NEVER REPAIRED. Every proposal states its own
    `content_sha256`, and here — at the pause, before a human ever sees it —
    that digest must EQUAL the canonical hash of the object it arrived on,
    and `target_sha256` must be 64 hex characters. A proposal carrying
    `"content_sha256": "placeholder"` used to pass the pause and be
    laundered into a valid digest at approval; now the pause is refused by
    name."""
    changes = payload.get("changes") if isinstance(payload, dict) else None
    if not isinstance(changes, list) or any(
            not isinstance(c, dict) or not isinstance(c.get("change_id"), str)
            or not c["change_id"] for c in changes):
        raise op_spec.OpSpecError(
            f"Op step {sid!r} has a human Gate, so its payload must carry a "
            f"`changes` list of objects with a change_id (a string): that is "
            f"what the human decides about.")
    seen, duplicates, unhashed, misstated = set(), [], [], []
    for change in changes:
        cid = change["change_id"]
        if cid in seen and cid not in duplicates:
            duplicates.append(cid)
        seen.add(cid)
        value = change.get("content_sha256")
        if not isinstance(value, str) or not value:
            unhashed.append(cid)
        elif not HEX64.fullmatch(value):
            misstated.append((cid, "content_sha256", value,
                              "which is not a sha256 (64 hex characters)"))
        elif value != change_content_sha256(change):
            misstated.append((cid, "content_sha256", value,
                              f"but its content hashes to "
                              f"{change_content_sha256(change)!r}"))
        target = change.get("target_sha256")
        if not isinstance(target, str) or not HEX64.fullmatch(target):
            misstated.append((cid, "target_sha256", target,
                              "which is not a sha256 (64 hex characters); a "
                              "change states the content hash of the item it "
                              "modifies"))
    if unhashed:
        # A proposal with no content hash is not repaired into one: the hash
        # is what the human's approval is ABOUT, so a Cog that states none
        # has not produced something decidable.
        raise op_spec.OpSpecError(
            f"Op step {sid!r} proposes change(s) {unhashed} with no "
            f"content_sha256; a proposed change states the hash of its own "
            f"content, and the runner never invents one for it.")
    if duplicates:
        raise op_spec.OpSpecError(
            f"Op step {sid!r} proposes change id(s) {duplicates} more than "
            f"once; a human decides about each change exactly once, so change "
            f"ids are unique.")
    if misstated:
        # Refused, never recomputed: the digest a proposal states is the
        # thing the approval is ABOUT, so a wrong one is a wrong proposal.
        raise op_spec.OpSpecError(
            [f"Op step {sid!r} proposes change {cid!r} carrying {field} "
             f"{value!r}, {why}; hashes are checked at the pause and never "
             f"repaired."
             for cid, field, value, why in misstated])
    return changes


def change_kind(change):
    """What a proposed change IS, whatever the proposing Cog called the field.
    `kind`/`target` were the pending sheet's guess; the change shape the Cogs
    actually emit says `change_type` and `target_item_ids` (machinery 0.5.6 —
    the live sweep's decision sheet had two blank columns). Neither name is
    promoted over the other: the renderer reads what is there."""
    return str(change.get("kind") or change.get("change_type") or "")


def change_target(change):
    """The item a proposed change is about. `target`, else the FIRST of
    `target_item_ids` — the sheet is one line per change, and a human who
    needs every id reads the JSON beside it."""
    target = change.get("target")
    if not target:
        ids = change.get("target_item_ids")
        if isinstance(ids, list) and ids:
            target = ids[0]
    return str(target or "")


# EVERY ASCII punctuation character (the 32 of them, GFM's own list). GFM
# permits a backslash before any one of them, and a backslash-escaped `@`,
# `#`, `:` or `h` -- well, `:` and `@` -- is no longer the start of a mention,
# an issue reference, an emoji shortcode or an autolink. Escaping the whole
# set is what makes the invariant CHECKABLE: a cell is literal text iff no
# ASCII punctuation character in it stands unescaped (machinery 0.5.8).
CELL_ESCAPES = "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"


def _escaped(text):
    """`text` with a backslash before every ASCII punctuation character."""
    return "".join("\\" + ch if ch in CELL_ESCAPES else ch for ch in text)


def cell(value):
    """A pending-sheet cell as LITERAL TEXT (Op machinery 0.5.9).

    The sheet is what the human decides from, and a valid `content_sha256`
    says nothing about how a proposal RENDERS: a target of
    `[owner/repo#1](https://example.invalid)` hides the real target behind
    link text, a pipe shifts the columns, a newline invents a row, `:smile:`
    becomes a picture, and `owner/repo#1<U+200B>0` READS as `owner/repo#10`
    while being a different string. Two rules, both checkable without a
    renderer:

    1. Every ASCII punctuation character is backslash-escaped. That disables
       every GFM construct at once -- autolinks, `@mentions`, `#references`,
       `:emoji:`, links, emphasis, code spans, HTML -- so there is no list of
       metacharacters to keep up to date, and no second escaping pass to
       double up with (0.5.7 HTML-escaped `&<>` as well; `&#124;` came out as
       `&amp;\\#124;`. The backslash rule alone covers them, so the HTML
       escape is gone).
    2. Every character in Unicode category `C*` (control, format including
       zero-width and bidi overrides, surrogate, private use, unassigned) or
       `Z*` (separators) other than an ordinary space is replaced by visible
       text `U+XXXX`.

    Whitespace runs (newlines included) collapse to one space first, so the
    common case stays readable and only the exotic characters get spelled
    out. That is lossy: leading, trailing and repeated whitespace does not
    survive, and the literal text `U+200B` is indistinguishable from an
    encoded U+200B.

    WHAT THIS DOES NOT DO (machinery 0.5.9).
    Rule 2 covers the categories it names and no more; it is not a general
    guarantee about invisibility, and it is not a confusable-character
    defense:

      * combining marks (`Mn`, e.g. U+034F) and variation selectors
        (U+FE0F) are neither `C*` nor `Z*`, so they pass through and can
        change how the characters beside them render;
      * look-alike letters -- Cyrillic `а` for Latin `a` -- are ordinary
        letters and are not detected at all;
      * a character like U+3164 HANGUL FILLER is `Lo` and renders as
        nothing much, and is likewise not detected.

    The sheet is a READING AID. `<step>.json` beside it is the authority:
    the digests are over the JSON and string equality is decided there, not
    by how a cell looks.
    """
    text = " ".join(str("" if value is None else value).split())
    out = []
    for ch in text:
        if ch != " " and unicodedata.category(ch)[0] in ("C", "Z"):
            out.append(_escaped(f"U+{ord(ch):04X}"))
        else:
            out.append(_escaped(ch))
    return "".join(out)


def render_artifact(doc):
    """The human's copy of an ARTIFACT question (0.7.0): the kind, id and
    summary of the one thing asked about, and one line per digest — every
    cell literal text, the JSON beside it the authority."""
    artifact = doc["artifact"]
    lines = [f"# Decision needed: {cell(doc['step'])}", "",
             f"Run: {cell(doc['run_id'])}", f"Asked: {cell(doc['asked_at'])}", "",
             f"The authority is `{cell(doc['step'])}.json` beside this file: "
             "it holds the artifact and the step's payload in full, the "
             "digests are over it, and string equality is decided there — "
             "not by how a cell looks. This sheet is a reading aid, with "
             "every ASCII punctuation character escaped and control, format "
             "and separator characters shown as `U+XXXX`.", "",
             f"Decide with: `{doc['decide_with']}`", "",
             "One verdict, `accept` or `reject`, about this whole artifact; "
             f"the decision names {cell('artifact_sha256')} "
             f"`{cell(doc['artifact_sha256'])}` and {cell('payload_sha256')} "
             f"`{cell(doc['payload_sha256'])}`. A rejection ends the run.", "",
             "| field | value |", "|---|---|",
             f"| kind | {cell(artifact.get('kind'))} |",
             f"| id | {cell(artifact.get('id', ''))} |",
             f"| summary | {cell(artifact.get('summary', ''))} |", "",
             "| digest | sha256 |", "|---|---|"]
    for name in sorted(artifact["digests"]):
        lines.append(f"| {cell(name)} | {cell(artifact['digests'][name])} |")
    return "\n".join(lines) + "\n"


def render_pending(doc):
    """The human's copy: one line per change, every cell literal text."""
    if doc.get("decides") == op_spec.DECIDES_ARTIFACT:
        return render_artifact(doc)
    lines = [f"# Decision needed: {cell(doc['step'])}", "",
             f"Run: {cell(doc['run_id'])}", f"Asked: {cell(doc['asked_at'])}", "",
             # The sheet is a READING AID, and the header says only what the
             # code above actually does (machinery 0.5.9): 0.5.8's "an
             # invisible character shows as U+XXXX" claimed a general property
             # the encoding does not have, and "punctuation shows a backslash"
             # is not how an escape renders.
             f"The authority is `{cell(doc['step'])}.json` beside this file: "
             "it holds each change in full, the digests are over it, and "
             "string equality is decided there — not by how a cell looks. "
             "This sheet is a reading aid: every ASCII punctuation character "
             "is escaped so that Markdown cannot restyle or link the text, "
             "control, format and separator characters are shown as "
             "`U+XXXX`, and runs of whitespace are collapsed to one space. "
             "Combining marks, variation selectors and look-alike letters "
             "are NOT detected.", "",
             f"Decide with: `{doc['decide_with']}`", "",
             "| change_id | kind | target | summary |",
             "|---|---|---|---|"]
    for change in pending_changes(doc["payload"], doc["step"]):
        lines.append("| {} | {} | {} | {} |".format(
            cell(change.get("change_id")), cell(change_kind(change)),
            cell(change_target(change)), cell(change.get("summary", ""))))
    return "\n".join(lines) + "\n"


def pending_artifact(step, context, sid):
    """The artifact an artifact-deciding human Gate asks about, evaluated
    from the Gate's declared mapping AFTER the step's Cog answered, and
    checked to be decidable — or the list of reasons it is not.

    Returns `(artifact, problems)`. The artifact is what the person's
    acceptance is ABOUT, so it is refused rather than repaired: a digest
    that is not 64 hex characters, a null kind, an empty digest set, a
    mapping that reads something this run does not have. A refused artifact
    is a FAILED Gate (the step produced nothing decidable), never a pause."""
    declared = op_spec.gate_artifact(step)
    problems = []
    try:
        artifact = op_spec.evaluate(declared, context)
    except op_spec.OpSpecError as exc:
        return None, [f"Op step {sid!r}'s artifact cannot be stated: {p}"
                      for p in exc.problems]
    if not isinstance(artifact, dict):
        return None, [f"Op step {sid!r}'s artifact evaluated to "
                      f"{type(artifact).__name__}, not an object."]
    kind = artifact.get("kind")
    if not isinstance(kind, str) or not kind.strip():
        problems.append(f"Op step {sid!r}'s artifact declares kind {kind!r}; "
                        f"an artifact says what kind of thing it is.")
    for key in ("id", "summary"):
        value = artifact.get(key)
        if value is not None and not isinstance(value, str):
            problems.append(f"Op step {sid!r}'s artifact declares {key} "
                            f"{value!r}, which is not a string.")
    detail = artifact.get("detail")
    if detail is not None and not isinstance(detail, dict):
        problems.append(f"Op step {sid!r}'s artifact declares detail "
                        f"{type(detail).__name__}, not an object.")
    digests = artifact.get("digests")
    if not isinstance(digests, dict) or not digests:
        problems.append(f"Op step {sid!r}'s artifact carries no digests; an "
                        f"acceptance is bound to the sha256 of each thing it "
                        f"accepts.")
    else:
        for name in sorted(str(n) for n in digests):
            value = digests.get(name)
            if not isinstance(value, str) or not HEX64.fullmatch(value):
                problems.append(f"Op step {sid!r}'s artifact digest {name!r} "
                                f"is {value!r}, which is not a sha256 (64 hex "
                                f"characters); digests are checked at the "
                                f"pause and never repaired.")
    if problems:
        return None, problems
    return artifact, []


def write_pending(run_dir, run_id, sid, payload, artifact=None):
    """The pause: the pending document and its rendered twin.

    With `artifact` (0.7.0) the document asks about that one thing and
    carries its canonical `artifact_sha256`; without it the payload's
    `changes` are what the person decides about, as before."""
    doc = {
        "schema": PENDING_SCHEMA,
        "run_id": run_id,
        "step": sid,
        "decides": (op_spec.DECIDES_ARTIFACT if artifact is not None
                    else op_spec.DECIDES_CHANGES),
        "payload": payload,
        "payload_sha256": canonical_sha256(payload),
        "asked_at": op_track.utc_now(),
        "decide_with": (f"op run --resume {Path(run_dir).resolve()} "
                        f"--decision <file>"),
    }
    if artifact is not None:
        doc["artifact"] = artifact
        doc["artifact_sha256"] = canonical_sha256(artifact)
    else:
        pending_changes(payload, sid)
    json_path = Path(run_dir) / "pending" / f"{sid}.json"
    md_path = Path(run_dir) / "pending" / f"{sid}.md"
    op_track.write_json(json_path, doc, base=run_dir)
    # The human's copy is written the same way as the JSON: a half-written
    # decision sheet is a half-read decision.
    op_track.write_atomic(md_path, render_pending(doc), base=run_dir)
    return doc, json_path, md_path


def load_decision(path):
    return _document(path, DECISION_SCHEMA, "human decision")


def normalized_change(change):
    """An EDITED change with its `content_sha256` recomputed from its own
    content.

    Only an edit is re-hashed. An approval or a rejection carries the digest
    the proposal stated — checked at the pause against the object it arrived
    on, and checked again at issuance — because recomputing it here would
    turn any digest, however wrong, into a valid-looking one."""
    change = dict(change)
    change["content_sha256"] = change_content_sha256(change)
    return change


def edited_change_problems(edit, proposed, where):
    """Why an edited change is not the SAME KIND of change as the one it
    replaces. An edit may change content; it may not change what the change
    IS, the item it targets, or the state it was approved against."""
    problems = []
    unknown = sorted(str(k) for k in set(edit) - set(proposed))
    if unknown:
        problems.append(f"{where} adds key(s) {unknown} the proposed change "
                        f"does not carry; an edit edits the proposal.")
    for key, value in proposed.items():
        if key not in edit:
            problems.append(f"{where} drops {key!r}; an edited change carries "
                            f"the same fields as the one it replaces.")
        elif key != "content_sha256" and type(edit[key]) is not type(value):
            problems.append(f"{where} declares {key} {edit[key]!r}, which is "
                            f"not the type the proposed change declares.")
    if "target_sha256" in proposed and \
            edit.get("target_sha256") != proposed.get("target_sha256"):
        problems.append(f"{where} changes target_sha256; an edit changes what "
                        f"is written, never the target state it was approved "
                        f"against.")
    if "repository" in proposed and \
            edit.get("repository") != proposed.get("repository"):
        problems.append(f"{where} retargets the change to repository "
                        f"{edit.get('repository')!r}; an edit stays on the "
                        f"item that was proposed.")
    return problems


def apply_artifact_decision(pending, decision, problems):
    """A decision about an ARTIFACT (0.7.0), checked against the pending
    document, as {verdict, artifact, artifact_sha256, reason, decided_by,
    decided_at}.

    The pending ARTIFACT is re-hashed here and the decision's
    `artifact_sha256` checked against that — never against the digest string
    the pending file carries beside it — for the same reason the payload is:
    an artifact edited on disk under an old digest would otherwise pass an
    old acceptance off as a decision about new bytes. One verdict, whole:
    there is no partial acceptance of an artifact and no edit."""
    artifact = pending.get("artifact")
    if not isinstance(artifact, dict):
        problems.append("the pending document asks about an artifact but "
                        "carries none; nothing can be decided from it.")
    elif decision.get("artifact_sha256") != canonical_sha256(artifact):
        problems.append("the decision's artifact_sha256 does not match the "
                        "pending artifact; the human decided about "
                        "something else.")
    if "decisions" in decision:
        problems.append("the decision carries a decisions list, but this "
                        "step asks about one artifact; give one verdict.")
    verdict = decision.get("verdict")
    if verdict not in ARTIFACT_VERDICTS:
        problems.append(f"the decision declares verdict {verdict!r}; an "
                        f"artifact is {list(ARTIFACT_VERDICTS)}ed whole.")
    reason = decision.get("reason")
    if reason is not None and not isinstance(reason, str):
        problems.append(f"the decision declares reason {reason!r}, which is "
                        f"not a string.")
    elif verdict == "reject" and not (reason or "").strip():
        problems.append("the decision rejects the artifact with no reason; "
                        "a rejection says why, because the next candidate "
                        "is built from it.")
    if problems:
        raise op_spec.OpSpecError(problems)
    return {"verdict": verdict, "artifact": artifact,
            "artifact_sha256": decision["artifact_sha256"],
            "reason": (reason or "").strip() or None,
            "decided_by": decision["decided_by"].strip(),
            "decided_at": decision["decided_at"].strip()}


def apply_decision(pending, decision):
    """The decision, checked against what was actually proposed, as
    {approved, rejected, edited, history} — or, for a step that asks about
    an artifact (0.7.0), as {verdict, artifact, artifact_sha256, reason,
    decided_by, decided_at}.

    The pending PAYLOAD is re-hashed here and the decision is checked against
    that hash, never against the hash string the pending file carries beside
    it: otherwise editing the proposals and leaving the old hash in place
    would pass an old approval off as a decision about the new ones (review
    B5).

    Every proposed change gets exactly one decision; a decision about
    anything else is refused; an edited change is re-hashed from its edited
    content, and THAT hash is what a write grant will carry. A decision can
    only select among the proposed changes: it can never add one."""
    problems = []
    actual_sha256 = canonical_sha256(pending.get("payload"))
    if decision.get("run_id") != pending["run_id"]:
        problems.append(f"the decision is for run {decision.get('run_id')!r}, "
                        f"not for {pending['run_id']!r}.")
    if decision.get("step") != pending["step"]:
        problems.append(f"the decision is about step "
                        f"{decision.get('step')!r}, not about "
                        f"{pending['step']!r}.")
    if decision.get("payload_sha256") != actual_sha256:
        problems.append("the decision's payload_sha256 does not match the "
                        "pending payload; the human decided about something "
                        "else.")
    for field in ("decided_by", "decided_at"):
        # `strip()`: a whitespace-only identity names nobody, and a Track
        # that records one says nothing about who decided.
        if not isinstance(decision.get(field), str) or not decision[field].strip():
            problems.append(f"the decision declares {field} "
                            f"{decision.get(field)!r}; a decision record says "
                            f"who decided and when.")
    when = decision.get("decided_at")
    if isinstance(when, str) and when.strip():
        try:
            datetime.fromisoformat(when.strip().replace("Z", "+00:00"))
        except ValueError:
            problems.append(f"the decision declares decided_at {when!r}, "
                            f"which is not a timestamp; a durable decision "
                            f"record says WHEN it was made.")
    if pending.get("decides") == op_spec.DECIDES_ARTIFACT:
        return apply_artifact_decision(pending, decision, problems)
    for key in ("verdict", "artifact_sha256"):
        if key in decision:
            problems.append(f"the decision carries {key}, but this step asks "
                            f"about proposed changes; decide each change in "
                            f"a decisions list.")
    if problems:
        raise op_spec.OpSpecError(problems)

    proposed = {c["change_id"]: c
                for c in pending_changes(pending["payload"], pending["step"])}
    decisions = decision.get("decisions")
    if not isinstance(decisions, list):
        raise op_spec.OpSpecError("the decision document declares no "
                                  "decisions list.")
    seen, approved, rejected, edited, history = set(), [], [], [], []
    for index, entry in enumerate(decisions):
        where = f"decisions[{index}]"
        if not isinstance(entry, dict):
            problems.append(f"{where} must be an object with a change_id and "
                            f"a verdict.")
            continue
        cid = entry.get("change_id")
        if not isinstance(cid, str) or cid not in proposed:
            problems.append(f"{where} decides about change {cid!r}, which "
                            f"step {pending['step']!r} never proposed.")
            continue
        if cid in seen:
            problems.append(f"{where} is a second decision about change "
                            f"{cid!r}; every change gets exactly one.")
            continue
        seen.add(cid)
        verdict = entry.get("verdict")
        if verdict not in VERDICTS:
            problems.append(f"{where} declares verdict {verdict!r}; the "
                            f"verdicts are {list(VERDICTS)}.")
            continue
        if verdict == "approve":
            # The SUPPLIED digest, preserved: it is what the pause checked
            # and what the human approved.
            change = dict(proposed[cid])
            approved.append(change)
        elif verdict == "reject":
            change = dict(proposed[cid])
            rejected.append(cid)
        else:
            change = entry.get("change")
            if not isinstance(change, dict) or change.get("change_id") != cid:
                problems.append(f"{where} is an edit without the edited "
                                f"change (the same change_id).")
                continue
            edit_problems = edited_change_problems(change, proposed[cid],
                                                   f"{where}'s edited change")
            if edit_problems:
                problems.extend(edit_problems)
                continue
            change = normalized_change(change)
            approved.append(change)
            edited.append(cid)
        # The durable decision history: every proposal with its verdict and
        # the hashes that were current when it was decided.
        history.append({"change_id": cid, "verdict": verdict,
                        "content_sha256": change["content_sha256"],
                        "target_sha256": change.get("target_sha256"),
                        "reason": entry.get("reason")})
    missing = sorted(set(proposed) - seen)
    if missing:
        problems.append(f"the decision leaves {missing} undecided; every "
                        f"proposed change needs exactly one decision.")
    if problems:
        raise op_spec.OpSpecError(problems)
    # `decided_by`/`decided_at` travel with the decision so a downstream step
    # can record WHO decided and WHEN without reading the decision file;
    # `approved` carries the effective objects, which for an
    # edited change is the EDITED one.
    return {"approved": approved, "rejected": rejected, "edited": edited,
            "history": history,
            "decided_by": decision["decided_by"].strip(),
            "decided_at": decision["decided_at"].strip()}


# ------------------------------------------------------------- the run ---

def _attempt_entry(attempt, envelope_path, request_sha256, cog_sha256, phase):
    """One line of the attempt ledger (machinery 0.6.6): WHICH invocation it
    was, the immutable file it owns, the question it put, the Cog it put it
    to, and whether it got as far as an answer.

    `attempt` counts every invocation ever made for that slot in this run —
    retries in mode `all`, re-asks after a renewal, re-runs after a changed
    request or Cog — so no two attempts of a slot ever name the same file."""
    return {"attempt": attempt,
            "envelope": str(Path(envelope_path).resolve()),
            "request_sha256": request_sha256,
            "cog_sha256": cog_sha256,
            "phase": phase}


def _attempt(cog_dir, task, request_path, envelope_path, on_fail, seam=None,
             cog_sha256=None, first_attempt=1, path_for=None, reserve=None,
             request_sha256=None):
    """Invoke once, gate, and retry exactly once when the failure was a
    transport/model failure (ok:false) and the step asked for retry-once.
    An error-severity problem in an ok envelope is never retried.

    `seam` carries the invocation context a granted step gets: the grant
    path, the run id, and the journal. It is EMPTY for a step with no
    authority, so an ordinary Cog is invoked exactly as before.

    Returns `(envelope, gate, attempts, cog_sha256, elapsed_s, envelope_path)`,
    where the last is the file the DECIDING attempt wrote. The Cog is digested
    immediately before EACH invocation (machinery 0.6.3): a retry is a second
    invocation and can land on a different Cog — a package edited or a model
    re-bound while the first attempt was failing — so each entry of `attempts`
    carries the digest ITS invocation ran under, and the returned `cog_sha256`
    is the one the winning envelope came from. `cog_sha256` may be passed in
    when the caller has just taken it for its reuse check; it is then the
    digest of the first attempt, taken immediately before it.

    **Every attempt owns an immutable file** (machinery 0.6.6). `first_attempt`
    is the number this invocation takes — the one
    after every attempt already on the Track for this slot — and `path_for`
    maps an attempt number to its own path, so nothing is ever overwritten and
    an older attempt's answer can never be read back as a newer one's.

    **A retry is an attempt like any other**: `reserve`, when
    given, is called with `(attempt, path, cog_sha256, attempts_so_far)`
    BEFORE each invocation — the retry included — so the Track carries the
    retry's own digests and its own path before it is paid for."""
    seam = seam or {}
    envelope_path = Path(envelope_path)
    path_for = path_for or (
        lambda n: attempt_envelope_path(envelope_path, n))
    started = time.monotonic()
    number = first_attempt
    digest = cog_sha256 or cog_package_sha256(cog_dir)
    path = Path(path_for(number))
    attempts = []
    if reserve is not None:
        reserve(number, path, digest, list(attempts))
    envelope = invoke_cog(cog_dir, task, request_path, **seam)
    op_track.write_json(path, envelope)
    gate = gate_envelope(envelope)
    attempts.append(_attempt_entry(number, path, request_sha256, digest,
                                   ANSWERED))
    if (gate["status"] == "fail" and on_fail == "retry-once"
            and not envelope.get("ok")):
        number += 1
        digest = cog_package_sha256(cog_dir)
        path = Path(path_for(number))
        if reserve is not None:
            reserve(number, path, digest, list(attempts))
        envelope = invoke_cog(cog_dir, task, request_path, **seam)
        op_track.write_json(path, envelope)
        gate = gate_envelope(envelope)
        attempts.append(_attempt_entry(number, path, request_sha256, digest,
                                       ANSWERED))
    return (envelope, gate, attempts, digest,
            round(time.monotonic() - started, 3), path)


def attempt_envelope_path(base, attempt):
    """Where attempt N of a step (or `foreach` element) that does NOT repeat
    writes its envelope (machinery 0.6.6).

    Attempt 1 keeps today's documented path — `envelopes/<step>.json`,
    `envelopes/<step>/<index>.json` — because that is the Track shape every
    reader and every Op package already knows, and a first attempt has no
    earlier file to collide with. Every LATER attempt of the same slot (the
    `retry-once` second invocation, or a re-run after a resume) takes
    `<name>.a<n>.json`, so it owns its own file and overwrites nothing."""
    base = Path(base)
    if attempt <= 1:
        return base
    return base.with_name(f"{base.stem}.a{attempt}{base.suffix}")


def repeat_envelope_path(base, index, attempt=1):
    """Where attempt N of repeat INDEX of a step (or of a `foreach` element)
    writes its envelope: `<step>.r<j>.a<n>.json`,
    `<step>/<index>.r<j>.a<n>.json`. The REQUEST beside it is written once and
    invoked k times — the repeats are of the same request, which is what makes
    agreeing answers evidence.

    The `.a<n>` component is machinery 0.6.6: a slot may be invoked more than
    once over a run (a retry in mode `all`, a re-ask after a renewal, a re-run
    after a changed request or Cog), and each of those invocations owns its
    own immutable file."""
    return Path(str(base) + f".r{index}.a{attempt}.json")


def _same_question(entry, request_sha256, cog_sha256):
    """Whether a recorded answer answers the question about to be asked:
    the same REQUEST, put to the same COG (machinery 0.6.2).

    The comparison is between the record's OWN digest and the digest of the
    Cog as it is right now, taken immediately before this repeat or element
    would be invoked (0.6.3) — never a digest taken once for the step, which
    could be neither what the record ran under nor what is about to run.

    A record written before 0.6.1 carries no request hash and one written
    before 0.6.2 carries no Cog digest; both are re-run, because silence is
    not a match."""
    if not request_sha256 or entry.get("request_sha256") != request_sha256:
        return False
    return bool(cog_sha256) and entry.get("cog_sha256") == cog_sha256


#: The two phases of a repeat record (machinery 0.6.5). An attempt is
#: RESERVED on the Track — written with `phase: asking`, its request and Cog
#: digests and its slot index — BEFORE the Cog is invoked, and the record is
#: completed (`phase: answered`) after. A crash between the two leaves an
#: `asking` record, which is what makes the budget survive it: the slot was
#: paid for whether or not anyone learned the answer.
ASKING = "asking"
ANSWERED = "answered"


def _reserved_repeat(index, envelope_path, request_sha256, cog_sha256,
                     attempt=1, before=()):
    """The record written BEFORE a repeat is invoked (machinery 0.6.5).

    It names the slot, the EXACT envelope file this invocation is about to
    write, the request it answers and the Cog it is being put to — everything
    a resume needs to decide whether the attempt can be recovered or is simply
    spent. It carries no gate, because nothing has been decided yet.

    Since 0.6.6 it also names WHICH attempt of that slot it is, and carries
    `before` — every attempt already made for this slot in this run — ahead of
    its own `asking` line. Recovery therefore reads only the file THIS
    reservation named: an older attempt's answer sits at its own path and can
    never be taken for this one's."""
    return {"index": index,
            "phase": ASKING,
            "attempt": attempt,
            "envelope": str(Path(envelope_path).resolve()),
            "request_sha256": request_sha256,
            "cog_sha256": cog_sha256,
            "gate": None,
            "binding": None,
            "elapsed_s": None,
            "attempts": list(before) + [
                _attempt_entry(attempt, envelope_path, request_sha256,
                               cog_sha256, ASKING)]}


def _highest_attempt(attempts):
    """The largest attempt number in an attempt ledger, or 0 for an empty
    one. A ledger entry written before 0.6.6 carries no number, so it counts
    as none — a pre-0.6.6 Track is refused at resume rather than renumbered
    (see `_pre_0_6_6_track`)."""
    highest = 0
    for entry in attempts or []:
        number = (entry or {}).get("attempt")
        if isinstance(number, int) and number > highest:
            highest = number
    return highest


def _records_at(prior, index):
    """Every record any earlier pass left for repeat slot INDEX: the live one
    and any the renewals retired (machinery 0.6.6).

    Renewal keeps the old attempts on the Track and their files on disk — it
    opens a new budget only — so attempt numbering has to see them, or a
    renewed slot would start again at `a1` and collide with the file the first
    budget's first attempt still owns."""
    records = []
    entry = _prior_repeat(prior, index)
    if entry is not None:
        records.append(entry)
    for retired in (prior or {}).get("retired_repeats") or []:
        if isinstance(retired, dict) and retired.get("index") == index:
            records.append(retired)
    return records


def _attempts_at(prior, index):
    """Every attempt ever made for repeat slot INDEX in this run, oldest
    first — what a new reservation carries forward as its history."""
    ledger = []
    for record in sorted(_records_at(prior, index),
                         key=lambda r: _highest_attempt(r.get("attempts"))):
        for entry in record.get("attempts") or []:
            if isinstance(entry, dict) and entry.get("attempt") is not None:
                ledger.append(entry)
    return ledger


def _next_attempt(prior, index):
    """The number the next invocation of repeat slot INDEX takes: one past
    the highest ever recorded there, across retired budgets as well. Numbering
    continues and never restarts, so paths never collide."""
    return max([_highest_attempt(r.get("attempts"))
                for r in _records_at(prior, index)] or [0]) + 1


def _answered(attempts):
    """An attempt ledger with its reservation lines closed: what a RECOVERED
    record carries, because the file its last reservation named is on disk."""
    return [dict(entry, phase=ANSWERED) if entry.get("phase") == ASKING
            else entry
            for entry in attempts or []]


def _in_flight(entry):
    """Whether a repeat record is a RESERVATION nobody completed: the
    process died between the reservation and the completion checkpoint.

    A record written before 0.6.5 carries no `phase` and always carries a
    gate, so it is never read as in flight."""
    return (entry.get("phase") == ASKING
            or not isinstance(entry.get("gate"), dict))


def _envelope_on_disk(entry):
    """The envelope a repeat record points at, or None when the file is
    gone, unreadable, or not envelope v1.

    None is never a refund (machinery 0.6.5):
    deleting an envelope does not un-spend the attempt that wrote it. It only
    means the answer cannot be read back, so the slot counts as a failed one."""
    path = (entry or {}).get("envelope")
    if not path:
        return None
    try:
        envelope = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(envelope, dict) or envelope_problems(envelope):
        return None
    return envelope


def _spent_record(entry, reason):
    """`(record, envelope, gate)` for a slot that was PAID FOR and whose
    answer cannot be used: the attempt is kept on the Track with a failing
    Gate that says why, and it contributes `null` downstream.

    Spending is a ledger, not a cache (machinery 0.6.5). A changed Cog or
    request invalidates REUSE of an earlier
    answer; it never invalidates the record that the answer was bought."""
    gate = {"policy": op_spec.GATE_POLICY, "status": "fail",
            "reasons": [reason], "decided_at": op_track.utc_now(),
            "guards": []}
    record = dict(entry, phase=ANSWERED, gate=gate, spent=True)
    record.setdefault("attempts", [])
    return record, None, gate


def _reusable(entry, request_sha256, cog_sha256):
    """The record of a repeat or element an earlier attempt already PASSED
    over this same request and this same Cog, or None.

    A resume re-runs only what failed: a passed
    answer's envelope is on disk and is read back rather than paid for again.
    But an answer belongs to the question it answered AND to the Cog that
    answered it — between the failed run and the resume an upstream envelope
    may have changed, and so may the Cog's own code, context or model. So the
    record is reused only when its envelope is still there and both digests
    match (machinery 0.6.1 and 0.6.2)."""
    if not isinstance(entry, dict) or not entry.get("envelope"):
        return None
    # A RESERVATION is not a result: an attempt that never completed has no
    # Gate, and silence is not a pass (machinery 0.6.5).
    if not isinstance(entry.get("gate"), dict):
        return None
    if entry["gate"].get("status") == "fail":
        return None
    if not _same_question(entry, request_sha256, cog_sha256):
        return None
    return entry if Path(entry["envelope"]).exists() else None


def _reusable_repeat(prior, index, request_sha256, cog_sha256):
    """`_reusable` over the repeat at INDEX of an earlier record."""
    return _reusable(_prior_repeat(prior, index) or {},
                     request_sha256, cog_sha256)


def _prior_repeat(prior, index):
    """The record an earlier attempt left at repeat INDEX, or None when
    nobody has ever reserved that slot."""
    entries = (prior or {}).get("repeats")
    if not isinstance(entries, list) or index >= len(entries):
        return None
    entry = entries[index]
    return entry if isinstance(entry, dict) else None


#: Why a spent slot's answer cannot be used, in the Gate reasons of the
#: record that keeps the expenditure on the Track (machinery 0.6.5).
INTERRUPTED_REASON = (
    "this attempt was reserved and interrupted before any result was "
    "recorded; the attempt is spent and its answer is not recoverable.")
UNREADABLE_REASON = (
    "this attempt was paid for and its envelope is missing or is not "
    "envelope v1; the attempt is spent and its answer cannot be read back.")
CHANGED_QUESTION_REASON = (
    "this attempt was paid for under a different request or a different "
    "Cog; the attempt is spent and its answer is not evidence for the "
    "question being asked now.")


def _from_the_ledger(prior, index, request_sha256, cog_sha256,
                     until_required):
    """What an earlier attempt at repeat INDEX contributes, or None when the
    slot has never been reserved and must be ASKED.

    Returns `(record, envelope, gate)`. Four outcomes, in order:

    - **reused** — a completed PASS over this same request and this same Cog,
      read back from its envelope rather than bought again (0.6.1, 0.6.2);
    - **recovered** — a RESERVATION whose envelope is on disk and is a valid
      envelope for this same question: the ask was paid for, so the result is
      taken from the file and gated as usual, without a second ask (0.6.5);
    - **spent** — any other record at this index, under `until-required`: an
      interrupted attempt, a failed one, one whose envelope has gone, or one
      that answered a question this run is no longer asking. The slot stays
      on the ledger with a failing Gate that says which (0.6.5, should-fix 1);
    - **None** — nothing was ever reserved here, or the mode is `all`, where
      a failed repeat is a missing answer the union still wants and is re-run.

    A failed attempt whose envelope is still readable keeps its own record,
    so its problems stay in the step's evidence exactly as before."""
    entry = _prior_repeat(prior, index)
    if entry is None:
        return None
    reused = _reusable(entry, request_sha256, cog_sha256)
    if reused is not None:
        return reused, json.loads(Path(reused["envelope"]).read_text()), \
            reused["gate"]
    same = _same_question(entry, request_sha256, cog_sha256)
    if _in_flight(entry):
        envelope = _envelope_on_disk(entry) if same else None
        if envelope is not None:
            gate = gate_envelope(envelope)
            return (dict(entry, phase=ANSWERED, recovered=True, gate=gate,
                         binding=envelope.get("binding"),
                         attempts=_answered(entry.get("attempts"))),
                    envelope, gate)
        if not until_required:
            return None
        return _spent_record(entry, INTERRUPTED_REASON if same
                             else CHANGED_QUESTION_REASON)
    if not until_required:
        return None
    if not same:
        return _spent_record(entry, CHANGED_QUESTION_REASON)
    envelope = _envelope_on_disk(entry)
    if envelope is None:
        return _spent_record(entry, UNREADABLE_REASON)
    return entry, envelope, entry["gate"]


def _last_digest(records):
    """The Cog digest of the LAST record that carries one, or None.

    A step or element record's own `cog_sha256` summarises records that each
    carry their own (machinery 0.6.3): the finer records are the evidence,
    and the summary names the Cog the last invocation of this record ran
    under. A reader who needs the rest reads `repeats`/`elements`."""
    for record in reversed(records or []):
        digest = (record or {}).get("cog_sha256")
        if digest:
            return digest
    return None


def _run_repeats(cog_dir, task, request_path, base, on_fail, seam, repeat,
                 request_sha256, prior=None, progress=None, name=None,
                 step_id=None):
    """Invoke ONE request `count` times, sequentially, and gate each repeat
    on its own.

    Returns `(records, gate, payloads, envelopes, all_envelopes, elapsed)`. A
    repeat whose Gate failed contributes `None` to the payloads and to the
    envelopes, so what a later step reads is the same list a resumed run
    restores; `all_envelopes` is what actually came back, failed repeats
    included, which is what the step's problems are read from.

    `progress`, when given, is called with the records so far after EVERY
    completed repeat, before the next one is invoked: a repeat that finished
    is durable before anything else is paid for.

    The Cog is digested afresh for EVERY repeat (machinery 0.6.3): the
    digest is taken immediately before the repeat's first invocation, is what
    that repeat's reuse check compares the prior record's own digest against,
    and is recorded on the repeat it ran under. A model re-bound between
    repeat 0 and repeat 1 therefore leaves two different digests on the two
    records instead of one digest covering both.

    **`mode: until-required` stops as soon as `require` repeats have passed**
    (machinery 0.6.4). `count` is then a budget of
    attempts, not a number of answers: the lists are of the repeats that
    ACTUALLY RAN, so their length is between `require` and `count`, and a
    repeat that never ran is absent rather than null. One clean first answer
    costs one invocation; only `count` rejected answers in a row fail the
    step. A reused pass counts toward `require` and a failed attempt already
    on the Track has spent its slot, so the budget holds across a resume.

    **An attempt is RESERVED before it is paid for** (machinery 0.6.5): the
    record goes on the Track with `phase: asking`,
    its request and Cog digests and its slot index, BEFORE `invoke_cog`, and
    is completed after. A crash in that window leaves an `asking` record, and
    the resume reads it as SPENT — recovering the answer from the envelope on
    disk when there is one, and simply losing the slot when there is not.
    Nothing refunds an attempt: a missing envelope only makes it unreadable.

    **Every attempt owns an immutable file** (machinery 0.6.6): the
    reservation names `<base>.r<j>.a<n>.json`, `n`
    counting every invocation ever made for that slot in this run, and a retry
    reserves its own number, its own digests and its own path before it is
    invoked. Nothing is ever deleted or overwritten, so the recovery reads
    ONLY the file its reservation named and an older attempt's answer can
    never be taken for a newer one.

    **In `until-required`, `count` is the ceiling on INVOCATIONS** (0.6.5):
    `retry-once` does not run inside a slot here, because the
    next slot IS the retry — an `ok: false` answer fails its slot like any
    other bad ask and the loop asks again, up to `count` times. In `all` the
    ceiling stays `count` SLOTS, each of which `retry-once` may run twice.

    `name` and `step_id` are what a refusal is spoken in: when the budget is
    spent and this pass could buy nothing, the Gate names the step or the
    element and says how to renew it."""
    count, require = repeat["count"], repeat["require"]
    until_required = repeat.get("mode") == op_spec.REPEAT_UNTIL_REQUIRED
    # The slot is the retry: `retry-once` would multiply the
    # ceiling, so it is not applied inside a slot in this mode.
    invoke_on_fail = None if until_required else on_fail
    records, gates, payloads, envelopes = [], [], [], []
    all_envelopes = []
    elapsed = 0.0
    passed = 0
    invoked = 0
    for index in range(count):
        if until_required and passed >= require:
            # The step asked for `require` clean answers and has them: every
            # further invocation would buy evidence nobody asked for.
            break
        cog_sha256 = cog_package_sha256(cog_dir)
        from_ledger = _from_the_ledger(prior, index, request_sha256,
                                       cog_sha256, until_required)
        if from_ledger is not None:
            record, envelope, gate = from_ledger
        else:
            # Every attempt of this slot that any earlier pass made, and the
            # number the next one takes (0.6.6): numbering continues across
            # resumes and renewals, so no two attempts share a file.
            carried = _attempts_at(prior, index)
            first_attempt = _next_attempt(prior, index)
            held = {}

            # ---- the reservation: the attempt is on the Track, with the
            # question it is about to ask and the EXACT file it will write,
            # before anything is paid for. A retry reserves the same way.
            def reserve(number, path, digest, done, _c=carried,
                        _i=index, _records=records):
                held["record"] = _reserved_repeat(
                    _i, path, request_sha256, digest, number,
                    _c + list(done))
                if progress is not None:
                    progress(_records + [held["record"]])

            envelope, gate, attempts, cog_sha256, seconds, envelope_path = \
                _attempt(cog_dir, task, request_path, base, invoke_on_fail,
                         seam, cog_sha256=cog_sha256,
                         first_attempt=first_attempt,
                         path_for=(lambda n, _i=index:
                                   repeat_envelope_path(base, _i, n)),
                         reserve=reserve, request_sha256=request_sha256)
            elapsed += seconds
            invoked += 1
            record = dict(held["record"],
                          phase=ANSWERED,
                          # The attempt that DECIDED the slot, and the file
                          # it owns (0.6.6).
                          attempt=attempts[-1]["attempt"],
                          envelope=str(Path(envelope_path).resolve()),
                          # The request this answer answers (0.6.1) and the
                          # Cog that answered THIS repeat (0.6.2, per
                          # invocation since 0.6.3): a resume reuses the
                          # repeat only when both hash the same.
                          cog_sha256=cog_sha256,
                          gate=gate,
                          binding=envelope.get("binding"),
                          elapsed_s=seconds,
                          attempts=carried + attempts)
        failed = gate["status"] == "fail"
        if not failed:
            passed += 1
        records.append(record)
        gates.append(gate)
        payloads.append(None if failed else (envelope or {}).get("payload"))
        envelopes.append(None if failed else envelope)
        all_envelopes.append(envelope)
        if progress is not None:
            progress(records)
    gate = combine_repeat_gates(gates, require)
    if until_required and passed < require and invoked == 0 and records:
        # The budget is spent and this pass could buy nothing: the element is
        # refused BY NAME, exactly as it would be after `count` bad answers,
        # and the reason says the budget — not the Cog — is what ran out
        # (0.6.5, should-fix 1).
        gate = dict(gate, reasons=[
            f"{name or 'this step'}: the repeat budget of {count} attempts "
            f"is spent and {require} passing repeat(s) are still required; "
            f"nothing was asked. Resume with --renew-budget "
            f"{step_id or '<step>'} to buy a new budget after a fix."
        ] + list(gate.get("reasons") or []))
    return (records, gate, payloads,
            envelopes, all_envelopes, round(elapsed, 3))


def _repeat_fields(records, envelopes):
    """What the repeats of a step (or element) contribute to its Track
    record: the binding of the first repeat that carried one, and every
    problem every repeat reported, in repeat order.

    `envelopes` is every envelope the repeats produced, a FAILED repeat's
    included: the step's `problems` are the audit of what the Cogs reported,
    and the null that masks a failed repeat's payload downstream never
    silences what it said."""
    return {
        "binding": next((r.get("binding") for r in records if r.get("binding")),
                        None),
        "problems": [p for e in envelopes if e
                     for p in (e.get("problems") or [])],
    }


def _plan(spec, track, run_dir, context):
    """A dry run: resolve the order and every request that depends only on
    the inputs; list the rest with request: null."""
    for step in spec.ordered:
        request_path = None
        expressions = [step.get("input") or {}]
        if step.get("foreach") is not None:
            expressions.append((step["foreach"] or {}).get("items"))
        if (step.get("foreach") is None
                and not any(op_spec.reads_steps(e) for e in expressions)):
            request = op_spec.evaluate(step.get("input") or {}, context)
            path = Path(run_dir) / "requests" / f"{step['id']}.json"
            op_track.write_json(path, request)
            request_path = str(path.resolve())
        # The plan says how many times each step will run: a step that
        # repeats is a step that costs k invocations, and a dry run is where
        # that is read.
        track["steps"].append(
            op_track.step_record(step, "planned", request=request_path,
                                 repeat=op_spec.repeat_spec(step)))
    track["status"] = "planned"
    track["ended_at"] = op_track.utc_now()
    track_path = op_track.save(track, run_dir)
    return 0, {"ok": True, "status": "planned",
               "run_dir": str(Path(run_dir).resolve()), "track": track_path}


def not_reached_element(index):
    """An element the loop never got to, because an earlier one finally
    failed (machinery 0.6.2). It has no request and
    no envelope: nothing was built for it and nothing was paid for. A resume
    runs it for the first time."""
    return {"index": index, "status": "not-reached", "request": None,
            "envelope": None, "request_sha256": None, "cog_sha256": None,
            "gate": None, "attempts": [], "problems": [], "binding": None,
            "repeats": None}


def _run_foreach(spec, step, cog_dir, run_dir, context,
                 seam=None, prior=None, progress=None):
    """Run one step once per element; returns (record fields, payload list).

    With `repeat`, each ELEMENT is repeated: the element's request is written
    once and invoked k times, the element's payload is the list of its repeat
    payloads, and its Gate is the repeat Gate — so the step's payload is a
    list of lists.

    **The loop stops at the first finally-failed element** (machinery 0.6.2):
    when an element's Gate is `fail` after its
    repeats and its retries are exhausted, the step has already failed —
    every later element could only ever be work bought for a verdict that is
    settled. The remaining elements are recorded `not-reached`, the completed
    ones and their repeats stay on the Track, and a resume continues from the
    element that failed. This is the rule for every `foreach`, whatever
    `on_fail` says: `on_fail` decides what the failed STEP does to the run,
    not how many elements a failing step buys.

    The Cog is digested afresh for EVERY element (machinery 0.6.3), taken
    immediately before that element's first invocation and recorded on its
    record: a 140-element sweep is long enough for a package to be edited or
    a model to be re-bound in the middle of it, and one digest over the whole
    step would say the elements all came from the same Cog when they did
    not."""
    foreach = step["foreach"]
    items = op_spec.evaluate(foreach["items"], context)
    if not isinstance(items, list):
        raise op_spec.OpSpecError(
            f"Op step {step['id']!r} declares foreach over a value that is "
            f"not a list.")
    task = step["cog"]["task"]
    on_fail = step.get("on_fail", "stop")
    repeat = op_spec.repeat_spec(step)
    prior_elements = (prior or {}).get("elements") or []
    elements, gates, payloads, envelopes = [], [], [], []
    # Every envelope any element produced, flattened: what the step's own
    # binding and problems are read from. `envelopes` stays one entry per
    # ELEMENT — the list a later step sees as `steps.<id>.envelope`.
    flat = []
    elapsed = 0.0
    stopped = False
    for index, item in enumerate(items):
        if stopped:
            elements.append(not_reached_element(index))
            payloads.append(None)
            envelopes.append(None)
            continue
        element_context = dict(context)
        element_context[foreach["as"]] = item
        request = op_spec.evaluate(step.get("input") or {}, element_context)
        request_sha256 = canonical_sha256(request)
        request_path = Path(run_dir) / "requests" / step["id"] / f"{index}.json"
        op_track.write_json(request_path, request)
        envelope_path = Path(run_dir) / "envelopes" / step["id"] / f"{index}.json"
        prior_element = (prior_elements[index]
                         if index < len(prior_elements) else None)
        # The Cog as it is right now, immediately before THIS element is
        # invoked — not as it was when the step started (0.6.3).
        cog_sha256 = cog_package_sha256(cog_dir)
        element = {"index": index, "request": str(request_path.resolve()),
                   "request_sha256": request_sha256,
                   "cog_sha256": cog_sha256,
                   # The attempts a renewal retired stay on the element: they
                   # are what attempt numbering continues from (0.6.6).
                   "retired_repeats": (prior_element
                                       or {}).get("retired_repeats")}
        if repeat is None:
            # An element that already passed over this same request and this
            # same Cog is read back, not paid for again — the same reuse rule
            # a repeat has had since 0.6.1.
            reused = _reusable(prior_element or {}, request_sha256, cog_sha256)
            if reused is not None:
                envelope = json.loads(Path(reused["envelope"]).read_text())
                gate, attempts = reused["gate"], reused.get("attempts") or []
                envelope_path = Path(reused["envelope"])
            else:
                # Attempt numbering continues from whatever an earlier pass
                # left here, so a re-run writes its own file (0.6.6).
                envelope, gate, attempts, cog_sha256, seconds, envelope_path \
                    = _attempt(
                        cog_dir, task, request_path, envelope_path, on_fail,
                        seam, cog_sha256=cog_sha256,
                        first_attempt=_highest_attempt(
                            (prior_element or {}).get("attempts")) + 1,
                        request_sha256=request_sha256)
                elapsed += seconds
                # A retry may have run under a different Cog: the element
                # keeps the digest its winning envelope came from (0.6.3).
                element["cog_sha256"] = cog_sha256
            element_envelopes = [envelope]
            element.update({"envelope": str(envelope_path.resolve()),
                            "status": STEP_STATUS[gate["status"]],
                            "gate": gate, "attempts": attempts,
                            "problems": envelope.get("problems") or []})
            payloads.append(None if gate["status"] == "fail"
                            else envelope.get("payload"))
            envelopes.append(envelope)
            flat.append(envelope)
        else:
            # Each completed repeat of THIS element joins the elements this
            # step has already finished, and the Track is rewritten before
            # the next repeat is invoked.
            element_progress = None
            if progress is not None:
                done_elements = list(elements)
                partial = dict(element)

                def element_progress(records, _done=done_elements,
                                     _partial=partial):
                    progress({"elements": _done
                              + [dict(_partial, repeats=list(records))]})

            records, gate, element_payloads, element_envelopes, \
                element_all, seconds = \
                _run_repeats(cog_dir, task, request_path,
                             envelope_path.with_suffix(""), on_fail, seam,
                             repeat, request_sha256,
                             prior=prior_element, progress=element_progress,
                             name=f"element {index} of step {step['id']!r}",
                             step_id=step["id"])
            elapsed += seconds
            element.update({"envelope": None,
                            "status": STEP_STATUS[gate["status"]],
                            "gate": gate, "attempts": [],
                            "repeats": records,
                            # Each repeat carries the digest IT ran under;
                            # the element names the last of them (0.6.3).
                            "cog_sha256": _last_digest(records) or cog_sha256,
                            **_repeat_fields(records, element_all)})
            payloads.append(None if gate["status"] == "fail"
                            else element_payloads)
            envelopes.append(None if gate["status"] == "fail"
                             else element_envelopes)
            flat.extend(e for e in element_all if e)
        gates.append(gate)
        elements.append(element)
        if progress is not None:
            # An element that finished is durable before the next one is
            # invoked, repeated or not.
            progress({"elements": list(elements)})
        # The breaker: this element's repeats and retries are exhausted and
        # its Gate says fail, so the step fails whatever the rest would say.
        stopped = gate["status"] == "fail"
    gate = combine_gates(gates) if gates else combine_gates([])
    fields = {
        "request": str((Path(run_dir) / "requests" / step["id"]).resolve()),
        "envelope": str((Path(run_dir) / "envelopes" / step["id"]).resolve()),
        "binding": next((e.get("binding") for e in flat if e.get("binding")),
                        None),
        "problems": [p for e in flat for p in (e.get("problems") or [])],
        "gate": gate,
        "elapsed_s": round(elapsed, 3),
        "elements": elements,
        "repeat": repeat,
        # Every element carries the digest its own invocations ran under; the
        # step names the last one that ran, and a step with no elements at
        # all names the Cog it would have invoked (0.6.3).
        "cog_sha256": _last_digest(elements) or cog_package_sha256(cog_dir),
    }
    if flat:
        fields["cog"] = flat[0].get("cog") or fields.get("cog")
    return fields, payloads, envelopes


def _run_single(step, cog_dir, run_dir, context, seam=None,
                prior=None, progress=None):
    """Run one step once — or, with `repeat`, k times over the SAME request.

    Returns `(record fields, payload, envelope)`, where a repeated step's
    payload is the LIST of its repeat payloads and its `envelope` for later
    mappings is the list of repeat envelopes (`None` for a failed one).

    The Cog digest is taken per invocation (0.6.3): a repeated step's
    repeats each carry their own and the step names the last, and a step that
    runs once carries the digest of the attempt whose envelope it kept."""
    task = step["cog"]["task"]
    request = op_spec.evaluate(step.get("input") or {}, context)
    request_path = Path(run_dir) / "requests" / f"{step['id']}.json"
    op_track.write_json(request_path, request)
    envelope_path = Path(run_dir) / "envelopes" / f"{step['id']}.json"
    identity = {"id": step["cog"].get("id"),
                "version": step["cog"].get("version")}
    repeat = op_spec.repeat_spec(step)
    on_fail = step.get("on_fail", "stop")
    if repeat is not None:
        records, gate, payloads, envelopes, all_envelopes, seconds = \
            _run_repeats(
                cog_dir, task, request_path, envelope_path.with_suffix(""),
                on_fail, seam, repeat, canonical_sha256(request),
                prior=prior,
                progress=(None if progress is None
                          else lambda rs: progress({"repeats": list(rs)})),
                name=f"step {step['id']!r}", step_id=step["id"])
        fields = {
            "cog": next((e.get("cog") for e in all_envelopes if e), None)
            or identity,
            "cog_sha256": _last_digest(records) or cog_package_sha256(cog_dir),
            "request": str(request_path.resolve()),
            # The step has no single envelope: `repeats` names one file per
            # repeat, and that is where a reader goes.
            "envelope": None,
            "gate": gate,
            "elapsed_s": seconds,
            "attempts": [],
            "repeat": repeat,
            "repeats": records,
            # Kept, not erased: a renewal retires the old attempts here and
            # numbering continues from them (0.6.6).
            "retired_repeats": (prior or {}).get("retired_repeats"),
            **_repeat_fields(records, all_envelopes),
        }
        return fields, payloads, envelopes
    envelope, gate, attempts, cog_sha256, seconds, envelope_path = _attempt(
        cog_dir, task, request_path, envelope_path, on_fail, seam,
        first_attempt=_highest_attempt((prior or {}).get("attempts")) + 1,
        request_sha256=canonical_sha256(request))
    fields = {
        "cog": envelope.get("cog") or identity,
        "cog_sha256": cog_sha256,
        "request": str(request_path.resolve()),
        "envelope": str(envelope_path.resolve()),
        "binding": envelope.get("binding"),
        "problems": envelope.get("problems") or [],
        "gate": gate,
        "elapsed_s": seconds,
        "attempts": attempts,
    }
    return fields, envelope.get("payload"), envelope


def _element_envelopes(record):
    """The envelopes of a foreach step, in element order. An EMPTY aggregate
    is a real result: `elements: []` restores as `[]`, never as an attempt to
    read the step's envelope DIRECTORY as a file."""
    envelopes = []
    for element in record["elements"]:
        if element.get("status") == "not-reached" \
                or (element.get("gate") or {}).get("status") == "fail":
            # An element the loop stopped before, or one whose Gate failed:
            # null, exactly as the live run put it in the context.
            envelopes.append(None)
            continue
        if element.get("repeats") is not None:
            envelopes.append(_repeat_envelopes(element))
            continue
        envelopes.append(json.loads(Path(element["envelope"]).read_text()))
    return envelopes


def _repeat_envelopes(record):
    """The envelopes of one repeated step or element, in repeat order. A
    repeat whose Gate failed restores as None — exactly what the live run put
    in the context."""
    envelopes = []
    for entry in record["repeats"]:
        if (entry.get("gate") or {}).get("status") == "fail" \
                or not entry.get("envelope"):
            envelopes.append(None)
            continue
        envelopes.append(json.loads(Path(entry["envelope"]).read_text()))
    return envelopes


def _payloads_of(envelopes):
    """The payload each restored envelope contributes. An entry that is
    itself a LIST is one element's repeats, so its payloads are a list too:
    a `foreach` step that repeats exposes a list of lists."""
    out = []
    for envelope in envelopes:
        if envelope is None:
            out.append(None)
        elif isinstance(envelope, list):
            out.append(_payloads_of(envelope))
        else:
            out.append(envelope.get("payload"))
    return out


def _results_of(record):
    """(payload, envelope) a finished step contributes to later mappings,
    read back from the envelope(s) the Track points at. Both are restored:
    a resumed run exposes `steps.X.envelope` exactly as the first run did."""
    if record["status"] in ("blocked", "denied", "not-reached", "planned",
                            "running", "failed"):
        return None, None
    if record.get("elements") is not None:
        envelopes = _element_envelopes(record)
        return _payloads_of(envelopes), envelopes
    if record["status"] == "skipped":
        return None, None
    if record.get("repeats") is not None:
        envelopes = _repeat_envelopes(record)
        return _payloads_of(envelopes), envelopes
    if not record.get("envelope"):
        return None, None
    envelope = json.loads(Path(record["envelope"]).read_text())
    return envelope.get("payload"), envelope


def _payload_of(record):
    """The payload a finished step contributes to later mappings."""
    return _results_of(record)[0]


def _restore_context(track, context):
    """Rebuild the run context from a Track: every finished step's payload
    AND envelope, and the human decision a gated step carries."""
    decisions = {}
    for record in track.get("steps") or []:
        payload, envelope = _results_of(record)
        entry = {"payload": payload, "envelope": envelope}
        if record.get("decision"):
            entry["decision"] = record["decision"]["value"]
            decisions[record["id"]] = record["decision"]
        context["steps"][record["id"]] = entry
    return decisions


def _kept_by_index(key, existing, value):
    """What a checkpoint writes for one field: for `repeats` and `elements`,
    the records this attempt has produced followed by every record at a LATER
    index it has not revisited (machinery 0.6.2).

    A checkpoint says what has happened so far, not what the step will end up
    with. Shortening these lists threw away durable evidence — a repeat that
    passed before the crash, or an element that finished — and the next
    resume paid for it again. The element in flight keeps its own repeat tail
    the same way. Every kept record carries its original `request_sha256` and
    Cog digest, so reuse is still validated when the loop reaches it."""
    if key not in ("repeats", "elements") or not isinstance(existing, list) \
            or not isinstance(value, list):
        return value
    kept = list(value)
    if key == "elements" and kept and len(kept) - 1 < len(existing):
        last = len(kept) - 1
        if isinstance(existing[last], dict) and isinstance(kept[last], dict):
            kept[last] = dict(kept[last], repeats=_kept_by_index(
                "repeats", existing[last].get("repeats"),
                kept[last].get("repeats")))
    if len(existing) > len(kept):
        kept += existing[len(kept):]
    return kept


def _paused_output(run_dir, track, sid, pending_path, track_path):
    return PAUSED_EXIT, {
        "ok": False, "status": "paused", "run_dir": str(Path(run_dir).resolve()),
        "track": track_path, "step": sid,
        "pending": str(Path(pending_path).resolve()),
    }


def _execute(spec, track, context, run_dir, package_root, authority, run_id,
             done=None, decisions=None, previous=None):
    """The step loop, shared by a fresh run and a resume.

    `done` holds the records of steps this run already finished — they are
    never re-run. A step recorded `running` (a crash mid-step) is absent
    from `done` and runs again.

    `previous` holds the records an earlier attempt left for the steps that DO
    run again, so a repeated step re-runs only the repeats that failed."""
    done = done or {}
    previous = previous or {}
    decisions = dict(decisions or {})
    dependents = spec.dependents()
    blocked = set()
    track["steps"] = []
    # This attempt has not stopped anywhere yet. `failed_step` names the step
    # a `stop` ended the run at, so a resume knows where to pick it up again.
    track["failed_step"] = None

    for position, step in enumerate(spec.ordered):
        sid = step["id"]
        prior = done.get(sid)
        if prior is not None:
            track["steps"].append(prior)
            if prior["status"] == "awaiting-decision":
                # Still waiting on the human: the run pauses again, with the
                # pending document it already wrote.
                for later in spec.ordered[position + 1:]:
                    if later["id"] not in done:
                        track["steps"].append(
                            op_track.step_record(later, "not-reached"))
                track["status"] = "paused"
                track_path = op_track.save(track, run_dir)
                return _paused_output(
                    run_dir, track, sid,
                    Path(run_dir) / "pending" / f"{sid}.json", track_path)
            if prior["status"] in ("skipped", "denied"):
                blocked |= dependents.get(sid, set())
            continue

        if sid in blocked:
            track["steps"].append(op_track.step_record(step, "blocked"))
            context["steps"][sid] = {"payload": None, "envelope": None}
            op_track.save(track, run_dir)
            continue

        # ---- authority: the grant is issued HERE, immediately before the
        # invocation, and only after every step it depends on has passed.
        seam, grant, grant_path, denial = {}, None, None, None
        if op_spec.requirements(step):
            try:
                grant, grant_path = issue_grant(step, context, authority, spec,
                                                run_id, run_dir, decisions,
                                                package_root=package_root)
            except Denied as exc:
                denial = str(exc)
        if denial is not None:
            record = op_track.step_record(
                step, "denied",
                gate={"policy": "authority", "status": "denied",
                      "reasons": [denial], "decided_at": op_track.utc_now(),
                      "guards": []},
                grant=None)
            track["steps"].append(record)
            context["steps"][sid] = {"payload": None, "envelope": None}
            op_track.save(track, run_dir)
            if step.get("on_fail", "stop") == "stop":
                for later in spec.ordered[position + 1:]:
                    track["steps"].append(
                        op_track.step_record(later, "not-reached"))
                track["status"] = "failed"
                track["failed_step"] = sid
                track["ended_at"] = op_track.utc_now()
                track_path = op_track.save(track, run_dir)
                return 1, {"ok": False, "status": "failed", "failed_step": sid,
                           "run_dir": str(run_dir), "track": track_path,
                           "denied": denial}
            blocked |= dependents.get(sid, set())
            continue

        journal_path = None
        if grant is not None:
            track.setdefault("grants", []).append(
                grant_record(grant, grant_path))
            journal_path = Path(run_dir) / "journal" / f"{sid}.jsonl"
            # Created DURABLY: the Track is about to name this journal as the
            # evidence for an external effect, so its directory entry has to
            # survive the same power loss the Track does.
            op_track.touch_durable(journal_path, base=run_dir)
            seam = {"grant_path": str(Path(grant_path).resolve()),
                    "run_id": run_id,
                    "journal_path": str(journal_path.resolve())}

        # ---- durability: the Track says the step is RUNNING, with the grant
        # and journal it was given, BEFORE the Cog is launched. Nothing
        # external can happen that the run directory does not already
        # describe.
        position_in_track = len(track["steps"])
        repeat_spec = op_spec.repeat_spec(step)
        # A repeat that already completed stays on the record when the step
        # is marked `running` again: rewriting it as a bare `running` record
        # would throw away work a crash left durable, and the resume would
        # pay for it a second time.
        earlier = previous.get(sid) or {}
        carried = {}
        if earlier.get("repeats") is not None \
                or earlier.get("elements") is not None:
            carried = {"repeats": earlier.get("repeats"),
                       "elements": earlier.get("elements")}
        track["steps"].append(op_track.step_record(
            step, "running", repeat=repeat_spec,
            grant=str(Path(grant_path).resolve()) if grant_path else None,
            journal=str(journal_path) if journal_path else None, **carried))
        op_track.save(track, run_dir)

        def checkpoint(partial, _at=position_in_track):
            """Rewrite the RUNNING record with what this step has finished so
            far. Called between repeats, so a completed repeat is on disk
            before the next one is invoked.

            A checkpoint never DISCARDS a record it has not revisited: the
            repeats and elements this attempt has not yet replaced are still
            the earlier attempt's, each with its original `request_sha256` and
            Cog digest, so a second crash cannot lose a repeat that passed
            (machinery 0.6.2). Normal reuse validation
            still applies to what is kept: a preserved record whose request or
            Cog has changed is re-run when the loop reaches it."""
            record = track["steps"][_at]
            for key, value in partial.items():
                record[key] = _kept_by_index(key, record.get(key), value)
            op_track.save(track, run_dir)

        cog_dir = (package_root / step["cog"]["source"]).resolve()
        # The Cog as it is AT INVOCATION: what answers belongs to the version
        # that answered, and a resume reuses an answer only from the same one
        # (machinery 0.6.2). The digest is taken
        # inside the runners, immediately before each invocation, never once
        # for the step — a step is many invocations (0.6.3).
        if step.get("foreach") is not None:
            fields, payload, envelopes = _run_foreach(
                spec, step, cog_dir, run_dir, context, seam,
                prior=previous.get(sid), progress=checkpoint)
            envelope_for_context = envelopes
            authority_use = None
        else:
            fields, payload, envelope_for_context = _run_single(
                step, cog_dir, run_dir, context, seam,
                prior=previous.get(sid),
                progress=checkpoint if repeat_spec else None)
            authority_use = (payload or {}).get("authority_use") \
                if isinstance(payload, dict) else None
        fields["grant"] = str(Path(grant_path).resolve()) if grant_path else None
        fields["journal"] = str(journal_path) if journal_path else None
        fields["authority_use"] = authority_use
        gate = fields["gate"]
        on_fail = step.get("on_fail", "stop")

        # ---- the human Gate: only a PASSING envelope reaches the human.
        artifact = None
        if (op_spec.gate_policy(step) == op_spec.HUMAN_GATE_POLICY
                and gate["status"] != "fail"
                and op_spec.gate_decides(step) == op_spec.DECIDES_ARTIFACT):
            # The artifact is evaluated with THIS step's result in view
            # (0.7.0). An artifact the Gate cannot state is a failed Gate,
            # recorded with its reasons: the step ran, but produced nothing
            # a person can accept.
            context["steps"][sid] = {"payload": payload,
                                     "envelope": envelope_for_context}
            artifact, artifact_problems = pending_artifact(step, context, sid)
            if artifact_problems:
                gate = fields["gate"] = {
                    "policy": op_spec.HUMAN_GATE_POLICY, "status": "fail",
                    "decides": op_spec.DECIDES_ARTIFACT,
                    "envelope_status": gate["status"],
                    "reasons": artifact_problems + list(gate["reasons"]),
                    "decided_at": op_track.utc_now(), "guards": []}
        if (op_spec.gate_policy(step) == op_spec.HUMAN_GATE_POLICY
                and gate["status"] != "fail"):
            pending, pending_path, _ = write_pending(run_dir, run_id, sid,
                                                     payload, artifact)
            fields["gate"] = {"policy": op_spec.HUMAN_GATE_POLICY,
                              "status": "pending",
                              "decides": pending["decides"],
                              # What the ENVELOPE Gate decided before the
                              # human was asked. A human approving proposals
                              # does not erase the problems the Cog reported
                              # making them: the step keeps
                              # `passed-with-problems`.
                              "envelope_status": gate["status"],
                              "asked_at": pending["asked_at"],
                              # The hash the TRACK remembers: a resume
                              # re-hashes the pending payload and compares it
                              # with this, not with the hash the pending file
                              # carries beside it.
                              "payload_sha256": pending["payload_sha256"],
                              # And the artifact's, for the same reason
                              # (0.7.0): the acceptance is about THESE bytes.
                              "artifact_sha256": pending.get("artifact_sha256"),
                              "reasons": gate["reasons"],
                              "decided_at": None, "guards": []}
            track["steps"][position_in_track] = (
                op_track.step_record(step, "awaiting-decision", **fields))
            for later in spec.ordered[position + 1:]:
                track["steps"].append(op_track.step_record(later, "not-reached"))
            track["status"] = "paused"
            track_path = op_track.save(track, run_dir)
            return _paused_output(run_dir, track, sid, pending_path, track_path)

        if gate["status"] == "fail" and on_fail == "skip":
            status = "skipped"
        else:
            status = STEP_STATUS[gate["status"]]
        track["steps"][position_in_track] = op_track.step_record(
            step, status, **fields)
        op_track.save(track, run_dir)

        if status == "failed":
            for later in spec.ordered[position + 1:]:
                track["steps"].append(op_track.step_record(later, "not-reached"))
            track["status"] = "failed"
            track["failed_step"] = sid
            track["ended_at"] = op_track.utc_now()
            track_path = op_track.save(track, run_dir)
            return 1, {"ok": False, "status": "failed", "failed_step": sid,
                       "run_dir": str(run_dir), "track": track_path}
        if status == "skipped":
            blocked |= dependents.get(sid, set())
            if step.get("foreach") is None:
                payload = None
        context["steps"][sid] = {"payload": payload,
                                 "envelope": envelope_for_context}

    problematic = any(s["status"] in ("passed-with-problems", "skipped",
                                      "blocked", "denied")
                      for s in track["steps"])
    track["status"] = "completed-with-problems" if problematic else "completed"
    track["ended_at"] = op_track.utc_now()
    if spec.outputs:
        try:
            track["outputs"] = op_spec.evaluate(spec.outputs, context)
        except op_spec.OpSpecError:
            track["outputs"] = None      # the Track stays readable and final
            op_track.save(track, run_dir)
            raise
    track_path = op_track.save(track, run_dir)
    output = {"ok": True, "status": track["status"],
              "run_dir": str(run_dir), "track": track_path}
    if spec.outputs:
        output["outputs"] = track["outputs"]
    return 0, output


def run(package_root, request_path, dry_run=False, runs_dir=None,
        authority_path=None):
    """Run this Op package's spec over one request. Returns (exit code,
    the JSON object the CLI prints)."""
    package_root = Path(package_root).resolve()
    spec = op_spec.load(package_root / "op.yaml")
    request_path = Path(request_path).resolve()
    request_doc = op_spec.load_document(request_path)
    values = spec.build_inputs(request_doc)
    authority = load_authority(authority_path) if authority_path else None

    # Every step's Cog declaration is checked BEFORE anything is created: a
    # spec naming a task the Cog does not declare for the usage audience is
    # an invalid spec, so it leaves no run directory and no Track stuck at
    # `status: running`. The same is true of a step that requires authority
    # this run was never admitted to have. (These are DECLARATION and
    # ADMISSION checks; the code Cog checks its own grant before it reaches
    # outside the run.) A dry run is
    # portable and checks neither.
    if not dry_run:
        problems = (op_spec.declaration_problems(spec, package_root)
                    + admission_problems(spec, authority))
        if problems:
            raise op_spec.OpSpecError(problems)

    run_id = op_track.new_run_id()
    run_dir = (Path(runs_dir).resolve() if runs_dir
               else package_root / "runs") / run_id
    # Through `ensure_dir`, not `mkdir(parents=True)`: the run directory's
    # OWN entry is fsynced in its parent. Every control directory beneath it
    # is created durably, and a Track, grant or journal whose containing
    # directory did not survive a power loss is not durable either.
    op_track.ensure_dir(run_dir)
    input_request = run_dir / "input-request.json"
    op_track.write_json(input_request, request_doc, base=run_dir)

    track = op_track.new_track(spec, run_id, input_request,
                               status="planned" if dry_run else "running")
    track["authority"] = ({"path": str(Path(authority_path).resolve()),
                           "sha256": sha256_file(authority_path)}
                          if authority_path else None)
    track["request_dir"] = str(request_path.parent)
    context = {
        "inputs": values,
        "steps": {},
        "run": {"dir": str(run_dir), "id": run_id},
        "request": {"dir": str(request_path.parent)},
    }
    lock = RunLock(run_dir).acquire()
    try:
        op_track.save(track, run_dir)
        if dry_run:
            return _plan(spec, track, run_dir, context)
        return _execute(spec, track, context, run_dir, package_root, authority,
                        run_id)
    finally:
        lock.release()


def resume(package_root, run_dir, decision_path=None, authority_path=None,
           renew_budgets=None):
    """Continue a paused, interrupted or FAILED run: apply the human's
    decision to the step that asked for it, and carry on from the next step.

    Steps already `passed` are never re-run; a step left `running` by a
    crash runs again (a Cog with a journal reconciles first), and the step
    that STOPPED a failed run runs again too. A repeat that
    passed is never re-run either: only the failed repeats of that step are
    invoked again.

    `renew_budgets` names the steps whose `until-required` repeat budget this
    resume BUYS AGAIN (machinery 0.6.5): spending is a ledger, so no edit
    replenishes it silently, and this is the explicit, recorded way to start
    a step's unfinished elements from zero attempts after a fix."""
    package_root = Path(package_root).resolve()
    run_dir = Path(run_dir).resolve()
    track_path = run_dir / "track.json"
    if not track_path.exists():
        raise op_spec.OpSpecError(f"{run_dir} carries no track.json; there is "
                                  f"no run to resume there.")
    # The lock is taken BEFORE the Track is read: two resumes that both read
    # `awaiting-decision` would both accept the decision and both write.
    lock = RunLock(run_dir).acquire()
    try:
        return _resume(package_root, run_dir, track_path, decision_path,
                       authority_path, renew_budgets)
    finally:
        lock.release()


def _stopping_step(track):
    """The step a failed run stopped at, for a Track that does not name it:
    the last record the run actually reached with a stopping verdict."""
    for record in reversed(track.get("steps") or []):
        if record["status"] in ("failed", "denied"):
            return record["id"]
    return None


def _changed_cogs(spec, package_root, done):
    """`[{step, cog, was, now}]` for every step this resume will NOT re-run
    whose Cog has changed since it ran (machinery 0.6.2).

    A step that passed keeps its result: re-running it would throw away work
    the run already paid for, and a resume exists to finish a run, not to
    start a new one. What the Track owes its reader is the fact — that the
    Cog at that source is no longer the one whose answer is in evidence."""
    declared = {step["id"]: (step.get("cog") or {}) for step in spec.ordered}
    changed = []
    for sid, record in done.items():
        was = record.get("cog_sha256")
        source = declared.get(sid, {}).get("source")
        if not was or not source:
            continue
        now = cog_package_sha256((Path(package_root) / source).resolve())
        if now != was:
            # The SPEC's declared id: it names the Cog at that source, which
            # is what changed, whatever the envelope of the run happened to
            # identify itself as.
            changed.append({"step": sid,
                            "cog": declared[sid].get("id")
                            or (record.get("cog") or {}).get("id"),
                            "was": was, "now": now})
    return sorted(changed, key=lambda c: c["step"])


def _renewable_budgets(spec, renew_budgets):
    """The step ids this resume buys a new repeat budget for, in the order
    they were named and without duplicates — or a refusal BY NAME.

    Only an `until-required` repeat step HAS a budget: in `mode: all` every
    `count` slot is asked on every attempt, so there is nothing to renew, and
    a step that does not repeat at all has nothing to renew either. Naming
    one is a mistake about what the run did, so it is refused rather than
    ignored (machinery 0.6.5)."""
    named = list(dict.fromkeys(renew_budgets or []))
    if not named:
        return []
    declared = {step["id"]: step for step in spec.ordered}
    for sid in named:
        step = declared.get(sid)
        if step is None:
            raise op_spec.OpSpecError(
                f"--renew-budget names step {sid!r}, which this Op does not "
                f"declare; a budget is renewed for a step of this spec.")
        repeat = op_spec.repeat_spec(step)
        if repeat is None or repeat["mode"] != op_spec.REPEAT_UNTIL_REQUIRED:
            raise op_spec.OpSpecError(
                f"--renew-budget names step {sid!r}, which declares no "
                f"repeat with mode: {op_spec.REPEAT_UNTIL_REQUIRED}; only an "
                f"until-required repeat spends a budget of attempts, so only "
                f"such a step has one to renew.")
    return named


def _retired(record):
    """A record whose spent repeats are RETIRED: off the ledger the new
    budget is measured against, but still on the Track (machinery 0.6.6).

    Earlier machinery cleared them outright, which threw away both the
    expenditure's detail and the attempt numbering. A renewal keeps the old
    attempts on the Track and their files on disk — it opens a new budget
    only — so numbering continues from them and a renewed slot's first ask
    cannot land on the file the first budget's first ask still owns."""
    return dict(record,
                repeats=None,
                retired_repeats=list(record.get("retired_repeats") or [])
                + [entry for entry in record["repeats"]
                   if isinstance(entry, dict)])


def _renewed_budget(record):
    """The record an earlier attempt left for a step whose budget is being
    renewed, with the spent attempts of its UNFINISHED work retired.

    The new budget is `count` fresh slots for those elements, and only for
    them: an element that already finished keeps its answers, because a
    renewal buys a new budget, it does not re-buy work the run has. Nothing is
    erased — the retired attempts stay on the record, their envelopes stay on
    disk, and the resume entry names the step in `renewed_budgets`, which is
    what makes this the EXPLICIT way."""
    renewed = dict(record)
    finished = ("passed", "passed-with-problems")
    if record.get("elements") is not None:
        renewed["elements"] = [
            _retired(element)
            if (isinstance(element, dict)
                and element.get("repeats") is not None
                and element.get("status") not in finished)
            else element
            for element in record["elements"]]
    elif record.get("repeats") is not None \
            and record.get("status") not in finished:
        renewed = _retired(renewed)
    return renewed


def _refuse_pre_0_6_6(track):
    """Refuse BY NAME a Track written by Op machinery before 0.6.6.

    Before 0.6.6 an envelope path was derived from the slot index alone, and
    an attempt left no number on the Track. 0.6.6 cannot safely continue such
    a run: its own attempt 1 would write over the file the old attempt 1
    owns, and a recovery could read an older attempt's answer as this one's —
    the very failure that review found. Refusing is the small, honest
    option; translating old paths would be guessing which file belonged to
    which attempt. The run's results are all still on disk; what is refused
    is continuing it in place.

    An attempt ledger is the tell: from 0.6.6 every entry carries `attempt`,
    and every repeat record does too."""
    for record in track.get("steps") or []:
        holders = [record] + [e for e in (record.get("elements") or [])
                              if isinstance(e, dict)]
        for holder in holders:
            for entry in holder.get("attempts") or []:
                if isinstance(entry, dict) and "attempt" not in entry:
                    break
            else:
                for entry in holder.get("repeats") or []:
                    if isinstance(entry, dict) and "attempt" not in entry:
                        break
                else:
                    continue
            raise op_spec.OpSpecError(
                f"step {record.get('id')!r} of this run was recorded by Op "
                f"machinery before 0.6.6, whose envelope files did not name "
                f"the attempt that wrote them. This machinery cannot resume "
                f"it without risking reading an earlier attempt's answer as "
                f"this one's, so it refuses rather than guess: start a new "
                f"run. The earlier run's Track and envelopes are untouched.")


def _resume(package_root, run_dir, track_path, decision_path,
            authority_path, renew_budgets=None):
    track = json.loads(track_path.read_text())
    spec = op_spec.load(package_root / "op.yaml")
    if spec.sha256() != track.get("spec_sha256"):
        raise op_spec.OpSpecError(
            "op.yaml has changed since this run started; a resume continues "
            "the run it was planned as, so it cannot adopt a new spec.")
    if track.get("status") == "rejected":
        # A rejection is final for THESE bytes (0.7.0): the person refused
        # the artifact this run produced, and no resume can produce another
        # one under the same decision. A different candidate is a new run.
        rejected = next((s for s in track.get("steps") or []
                         if s.get("status") == "rejected"), None) or {}
        who = ((rejected.get("decision") or {}).get("value") or {}).get(
            "decided_by")
        raise op_spec.OpSpecError(
            f"this run was rejected at step {rejected.get('id')!r} by "
            f"{who!r}; a rejection is final for the artifact this run "
            f"produced, so it is not resumed — start a new run for a new "
            f"candidate.")
    if track.get("status") == "planned":
        raise op_spec.OpSpecError(
            "this run is a dry run: it resolved a plan and invoked nothing, "
            "so there is nothing to resume — start a run with --request.")
    _refuse_pre_0_6_6(track)
    renewed = _renewable_budgets(spec, renew_budgets)

    recorded = track.get("authority") or None
    if authority_path is None and recorded:
        authority_path = recorded["path"]
    authority = load_authority(authority_path) if authority_path else None
    if authority_path and recorded and \
            sha256_file(authority_path) != recorded["sha256"]:
        raise op_spec.OpSpecError(
            "the admission file has changed since this run started; a resume "
            "runs under the authority the run was admitted with.")

    # A resume is a RUN: the same load-time refusals apply. A Cog's manifest
    # may have changed while the run was paused, and a run that was never
    # admitted for what its remaining steps require must not reach them.
    problems = (op_spec.declaration_problems(spec, package_root)
                + admission_problems(spec, authority))
    if problems:
        raise op_spec.OpSpecError(problems)

    request_doc = json.loads(Path(track["input_request"]).read_text())
    values = spec.build_inputs(request_doc)
    context = {
        "inputs": values,
        "steps": {},
        "run": {"dir": str(run_dir), "id": track["run_id"]},
        # Relative `$path` operands resolved against the ORIGINAL request
        # directory on the first run, and resolve against it again here
        # older Tracks fall back to where the copy lives.
        "request": {"dir": track.get("request_dir")
                    or str(Path(track["input_request"]).parent)},
    }
    decisions = _restore_context(track, context)

    done = {r["id"]: r for r in track.get("steps") or []
            if r["status"] in ("passed", "passed-with-problems", "skipped",
                               "blocked", "denied", "awaiting-decision")}
    # The step that stopped a FAILED run is the resume point:
    # a Cog that reported unfinished work — a write left uncertain — is
    # invoked again so it can finish it, and the steps after it run for the
    # first time. A `failed` record is not in `done` to begin with; a
    # `denied` one is, so it is taken out here. Nothing that PASSED is ever
    # re-run. Tracks written before 0.5.5 carry no `failed_step`, so the
    # stopping step is read off the records instead.
    if track.get("status") == "failed":
        stopper = track.get("failed_step") or _stopping_step(track)
        if stopper is not None:
            done.pop(stopper, None)

    decision_copy, rejected = None, False
    if decision_path:
        decision = load_decision(decision_path)
        sid = decision.get("step")
        record = done.get(sid)
        if record is None or record["status"] != "awaiting-decision":
            raise op_spec.OpSpecError(
                f"step {sid!r} is not waiting for a decision in this run.")
        pending = json.loads(
            (run_dir / "pending" / f"{sid}.json").read_text())
        remembered = (record.get("gate") or {}).get("payload_sha256")
        if remembered and canonical_sha256(pending.get("payload")) != remembered:
            raise op_spec.OpSpecError(
                f"the pending payload for step {sid!r} is not the one this "
                f"run paused on; the proposals changed on disk since the "
                f"Track recorded them, so no decision about them can be "
                f"applied.")
        remembered_artifact = (record.get("gate") or {}).get("artifact_sha256")
        if remembered_artifact and canonical_sha256(
                pending.get("artifact")) != remembered_artifact:
            raise op_spec.OpSpecError(
                f"the pending artifact for step {sid!r} is not the one this "
                f"run paused on; the artifact changed on disk since the "
                f"Track recorded it, so no decision about it can be "
                f"applied.")
        value = apply_decision(pending, decision)
        decision_copy = run_dir / "decisions" / f"{sid}.json"
        op_track.write_json(decision_copy, decision, base=run_dir)
        digest = sha256_file(decision_copy)
        # The human decided about the proposals; the ENVELOPE Gate's verdict
        # on the step that made them stands.
        envelope_status = (record.get("gate") or {}).get("envelope_status")
        record["status"] = STEP_STATUS.get(envelope_status, "passed")
        rejected = value.get("verdict") == "reject"
        if rejected:
            # The person refused the artifact (0.7.0). The step's Cog passed
            # its envelope Gate; the HUMAN Gate is what failed, and the
            # record says so by name rather than as a step failure a resume
            # would re-run.
            record["status"] = "rejected"
        record["gate"] = {"policy": op_spec.HUMAN_GATE_POLICY,
                          "status": "rejected" if rejected else "pass",
                          "decides": pending.get("decides",
                                                 op_spec.DECIDES_CHANGES),
                          "envelope_status": envelope_status,
                          "asked_at": (record.get("gate") or {}).get("asked_at"),
                          "payload_sha256": remembered,
                          "artifact_sha256": remembered_artifact,
                          "decided_at": op_track.utc_now(),
                          "decision": str(decision_copy.resolve()),
                          "decision_sha256": digest,
                          "reasons": ([f"rejected by {value['decided_by']}: "
                                       f"{value.get('reason')}"]
                                      if rejected else [])
                          + ((record.get("gate") or {}).get("reasons") or []),
                          "guards": []}
        record["decision"] = {"decision": str(decision_copy.resolve()),
                              "decision_sha256": digest, "value": value}
        decisions[sid] = record["decision"]
        payload, envelope = _results_of(record)
        context["steps"][sid] = {"payload": payload, "envelope": envelope,
                                 "decision": value}

    entry = {"at": op_track.utc_now(),
             "decision": str(decision_copy.resolve()) if decision_copy else None,
             # Which Cogs are not the ones that produced this run's kept
             # results (machinery 0.6.2). A step that
             # PASSED is never re-run — fix-and-resume is how a run is
             # finished — so the change is recorded instead, and the evidence
             # says which version produced what.
             "changed_cogs": _changed_cogs(spec, package_root, done),
             # The steps this resume bought a NEW repeat budget for
             # (machinery 0.6.5). Spending is a ledger: a changed Cog or
             # request invalidates the reuse of earlier answers, never the
             # record that they were paid for, so a new budget is bought
             # here by name and recorded here by name.
             "renewed_budgets": renewed}
    track.setdefault("resumes", []).append(entry)
    if decision_copy is not None and rejected:
        # The run ENDS here (0.7.0): the decision and the resume that carried
        # it are recorded, the steps after the Gate stay `not-reached`, and
        # nothing is invoked. Exit 1: the run did not complete, and the Track
        # says why by name.
        track["status"] = "rejected"
        track["failed_step"] = None
        track["ended_at"] = op_track.utc_now()
        track_path = op_track.save(track, run_dir)
        return 1, {"ok": False, "status": "rejected", "step": sid,
                   "decided_by": value["decided_by"],
                   "reason": value.get("reason"),
                   "run_dir": str(run_dir), "track": track_path}
    track["status"] = "running"
    track["ended_at"] = None
    # Durability order: the accepted decision and the resume are
    # on disk BEFORE any grant is issued or any Cog is invoked.
    op_track.save(track, run_dir)
    # What the earlier attempt left for the steps that run again: a repeated
    # step re-runs only the repeats that FAILED, and reads the rest back from
    # the envelopes already on disk.
    previous = {r["id"]: r for r in track.get("steps") or [] if r.get("id")}
    for sid in renewed:
        if previous.get(sid) is not None:
            previous[sid] = _renewed_budget(previous[sid])
    return _execute(spec, track, context, run_dir, package_root, authority,
                    track["run_id"], done=done, decisions=decisions,
                    previous=previous)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run this Op package's spec.")
    parser.add_argument("--request",
                        help="the Op request document (JSON or YAML)")
    parser.add_argument("--dry-run", action="store_true",
                        help="resolve the plan and write a planned Track "
                             "without invoking any Cog")
    parser.add_argument("--runs-dir",
                        help="where run directories are written "
                             "(default: <package>/runs)")
    parser.add_argument("--authority",
                        help="the run's admission (openteams/op-authority "
                             "[0.1]): the owner's authority for this run. "
                             "Without it, a step that requires authority is "
                             "refused before anything runs.")
    parser.add_argument("--resume", metavar="RUN_DIR",
                        help="continue a paused or interrupted run")
    parser.add_argument("--decision",
                        help="with --resume: the human decision "
                             "(openteams/op-decision [0.1]) for the step that "
                             "is waiting")
    parser.add_argument("--renew-budget", metavar="STEP", action="append",
                        dest="renew_budget",
                        help="with --resume: buy a new repeat budget for "
                             "this until-required step, after a fix. "
                             "Repeatable. Spending is a ledger: without "
                             "this, a step whose budget is spent is refused "
                             "rather than quietly given more attempts.")
    args = parser.parse_args(argv)
    if bool(args.resume) == bool(args.request):
        parser.error("pass --request to start a run or --resume to continue "
                     "one, not both")
    if args.decision and not args.resume:
        parser.error("--decision applies to --resume")
    if args.renew_budget and not args.resume:
        parser.error("--renew-budget applies to --resume")
    try:
        if args.resume:
            code, output = resume(ROOT, args.resume,
                                  decision_path=args.decision,
                                  authority_path=args.authority,
                                  renew_budgets=args.renew_budget)
        else:
            code, output = run(ROOT, args.request, dry_run=args.dry_run,
                               runs_dir=args.runs_dir,
                               authority_path=args.authority)
    except op_spec.OpSpecError as exc:
        print(json.dumps({"ok": False, "status": "invalid-input",
                          "problems": exc.problems}, indent=2))
        return 2
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "status": "invalid-input",
                          "problems": [f"{type(exc).__name__}: {exc}"]},
                         indent=2))
        return 2
    print(json.dumps(output, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
