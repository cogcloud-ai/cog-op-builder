"""Shared core for a CODE Cog's entry points (cog-smith machinery, generic).

A code Cog (`kind: code`, decided 2026-09-17) is a Cog with no model in the
loop: the same seam as a context Cog — a declared input schema, a declared
output schema, envelope v1 with structured `problems`, contract checks run
in-package — with the model half removed. Everything here is generic:
per-cog work lives in `task_logic.py`, which this machinery calls as

    run(bundle, grant, journal) -> (payload, problems)

`smith check` enforces this file and `cog_cli.py` by hash, exactly as it
enforces the context-cog machinery. Fixes happen in cog-smith's template and
roll out by re-copying (MACHINERY.md).

**Authority, honestly stated.** This process runs as its owner, with the
owner's ambient credentials. A grant is not an enforced sandbox: it is a
document the Op runner issues and THIS CODE checks before it reaches outside
the run. The Cog refuses to act without a valid grant, and reports every
attempted operation. Nothing here may be described as an enforced restricted
environment.
"""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task_logic   # noqa: E402  (the ONLY per-cog module in src/)

try:
    import jsonschema
    _SchemaValidator = (getattr(jsonschema, "Draft202012Validator", None)
                        or getattr(jsonschema, "Draft7Validator", None))
except ImportError:                                    # pragma: no cover
    jsonschema = None
    _SchemaValidator = None

#: The code-cog machinery lineage (cog-smith MACHINERY.md). Reported in
#: every envelope's `binding`, so a saved result names the code that made it.
MACHINERY_VERSION = "0.1.5"

GRANT_SCHEMA = "openteams/op-grant [0.1]"

#: The run this process is serving, set by `invoke` once the grant has been
#: checked against it. The per-call helpers re-read it, so `read_allowed` and
#: `write_allowed` re-check expiry and run binding on EVERY call without the
#: author having to thread the run id through their own code.
_INVOCATION_RUN_ID = None

ROOT = Path(__file__).resolve().parent.parent


def utc_now():
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------- the manifest --

def load_manifest(root=None):
    """The profile manifest: `[tool.cog]` in pixi.toml (default) or cog.yaml.
    Exactly one — a package whose two manifests could disagree is refused."""
    root = Path(root or ROOT)
    pixi, standalone = root / "pixi.toml", root / "cog.yaml"
    doc = None
    if pixi.exists():
        try:
            import tomllib
        except ModuleNotFoundError as exc:              # pragma: no cover
            raise RuntimeError(
                "reading a [tool.cog] manifest needs Python 3.11+ (tomllib); "
                "this Cog declares python >=3.11") from exc
        with open(pixi, "rb") as handle:
            doc = tomllib.load(handle)
    in_pixi = bool(doc and isinstance(doc.get("tool"), dict)
                   and isinstance(doc["tool"].get("cog"), dict))
    if in_pixi and standalone.exists():
        raise ValueError(f"{root} carries both pixi.toml [tool.cog] and "
                         f"cog.yaml — a package has exactly one manifest")
    if in_pixi:
        manifest = dict(doc["tool"]["cog"])
        workspace = doc.get("workspace") or doc.get("project") or {}
        for key, source in (("version", "version"), ("summary", "description")):
            if key not in manifest and workspace.get(source) is not None:
                manifest[key] = workspace[source]
        return manifest
    if standalone.exists():
        import yaml
        manifest = yaml.safe_load(standalone.read_text())
        if not isinstance(manifest, dict):
            raise ValueError(f"{standalone} is not a manifest mapping")
        return manifest
    raise FileNotFoundError(f"{root} carries no profile manifest "
                            f"(pixi.toml [tool.cog] or cog.yaml)")


MANIFEST = load_manifest()
SELF_ID = {"id": MANIFEST.get("id"), "version": MANIFEST.get("version")}
#: What this Cog touches outside the run. DECLARED, never inferred.
REACHES = MANIFEST.get("reaches") or []

_context = MANIFEST.get("context") or {}


def _schema(key):
    rel = _context.get(key)
    if not rel:
        return None
    path = ROOT / rel
    return json.loads(path.read_text()) if path.exists() else None


INPUT_SCHEMA = _schema("input_schema")
OUTPUT_SCHEMA = _schema("output_schema")

#: The default usage task — the entry point `pixi run <task>` names.
DEFAULT_TASK = "run"


def problem(check, detail, severity="error"):
    return {"check": check, "detail": str(detail), "severity": severity}


def task_logic_sha256():
    """The hash of the package-owned module — the code that did the work."""
    return hashlib.sha256(
        (ROOT / "src" / "task_logic.py").read_bytes()).hexdigest()


# ----------------------------------------------------------- the journal --

class JournalCorrupt(Exception):
    """A COMPLETE journal line that is not a JSON object. Never skipped: a
    journal the Cog cannot read in full cannot prove what was already done,
    so the invocation is refused (`journal-corrupt`) instead of risking a
    second external effect."""


class Journal:
    """An append-only JSONL record of what this Cog did outside the run.

    One JSON object per line, flushed and fsynced per line, so a crash after
    an external effect leaves either the line or nothing — never a torn
    record the next run would misread. The runner creates the file and
    passes `--journal`; the Cog reads it FIRST on every invocation, so a
    change whose outcome is already recorded is skipped and a change left
    `applying` is reconciled before anything is attempted again.

    A crash mid-write can leave an UNTERMINATED last line. That fragment is
    torn: `read()` ignores it, and `append()` REPAIRS it first — the
    fragment is cut and a `{"phase": "torn"}` entry records that it was —
    so the next real entry starts on a line of its own and can never be
    swallowed by the fragment.
    """

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _write(self, entry):
        entry = dict(entry)
        entry.setdefault("at", utc_now())
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        return entry

    def repair(self):
        """Terminate a torn last line, if there is one; returns the discarded
        fragment or None. Called before every append."""
        if not self.path.exists():
            return None
        data = self.path.read_bytes()
        if not data or data.endswith(b"\n"):
            return None
        cut = data.rfind(b"\n") + 1
        fragment = data[cut:].decode("utf-8", "replace")
        with open(self.path, "r+b") as handle:
            handle.truncate(cut)
            handle.flush()
            os.fsync(handle.fileno())
        self._write({"phase": "torn", "discarded": fragment})
        return fragment

    def append(self, entry):
        """Write one entry (a dict), stamping `at` when it carries none."""
        if not isinstance(entry, dict):
            raise TypeError("a journal entry is a JSON object")
        self.repair()
        return self._write(entry)

    def read(self):
        """Every entry, in order.

        An unterminated LAST line is a torn write and is ignored — the
        records before it are still true. A malformed COMPLETE line anywhere
        is corruption, not noise: it raises `JournalCorrupt` rather than
        being skipped, because skipping it would hide an effect.

        The tail is cut as BYTES, at the last newline, before anything is
        decoded: a crash halfway through a multibyte character would
        otherwise make decoding the whole file raise `UnicodeDecodeError`
        and lose the records before it. Each
        complete line is then decoded strictly, so a line that is not UTF-8
        is corruption with a name rather than a traceback."""
        if not self.path.exists():
            return []
        data = self.path.read_bytes()
        cut = len(data) if (not data or data.endswith(b"\n")) \
            else data.rfind(b"\n") + 1
        entries = []
        for number, raw in enumerate(data[:cut].split(b"\n"), start=1):
            if not raw.strip():
                continue
            try:
                line = raw.decode("utf-8").strip()
            except UnicodeDecodeError as exc:
                raise JournalCorrupt(
                    f"{self.path.name} line {number} is not valid UTF-8 "
                    f"({exc}); the journal records external effects and is "
                    f"never partly read") from exc
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise JournalCorrupt(
                    f"{self.path.name} line {number} is not readable JSON "
                    f"({exc}); the journal records external effects and is "
                    f"never partly read") from exc
            if not isinstance(value, dict):
                raise JournalCorrupt(
                    f"{self.path.name} line {number} is not a JSON object; "
                    f"a journal entry is an object")
            entries.append(value)
        return entries

    def phases(self):
        """change_id -> the LAST phase recorded for it."""
        out = {}
        for entry in self.read():
            if entry.get("change_id") is not None:
                out[entry["change_id"]] = entry.get("phase")
        return out

    def last(self, change_id):
        """The last entry for one change, or None."""
        found = None
        for entry in self.read():
            if entry.get("change_id") == change_id:
                found = entry
        return found


# ------------------------------------------------------------- the grant --
#
# A grant is issued by the Op's Gate, written by the runner, and read here.
# It carries no credentials, and no bundle, payload, decision or request can
# widen it: this module only ever READS it.

def load_grant(path):
    """The grant document at PATH. Raises ValueError when it is not JSON."""
    try:
        return json.loads(Path(path).read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"grant {Path(path).name} is not JSON: {exc}") from exc


#: The two hash fields a granted change carries. They are EXCLUDED from the
#: change's own content hash: the hash covers what the change says to do,
#: not the hashes stated beside it.
CHANGE_HASHES = ("content_sha256", "target_sha256")


def canonical_sha256(value):
    """The hash of a JSON value, canonically serialized (sorted keys, no
    whitespace) — the same bytes for the same document however it was
    written. The Op runner hashes a change exactly this way."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def change_content_sha256(change):
    """The content hash of a change OBJECT: everything about it except the
    two hash fields.

    Compute this from the change you are ABOUT TO APPLY and pass it to
    `write_allowed`. Never forward the `content_sha256` a bundle carries:
    forwarding it only checks that the bundle agrees with itself, so content
    edited under an approved id would pass."""
    if not isinstance(change, dict):
        raise TypeError("a change is a JSON object")
    return canonical_sha256({k: v for k, v in change.items()
                             if k not in CHANGE_HASHES})


def _expired(grant, now=None):
    expires = ((grant.get("valid") or {}).get("expires_at"))
    if not expires:
        return True, "the grant declares no expiry"
    try:
        deadline = datetime.fromisoformat(str(expires))
    except ValueError:
        return True, f"the grant's expires_at {expires!r} is not a timestamp"
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    moment = now or datetime.now(timezone.utc)
    if moment > deadline:
        return True, f"the grant expired at {expires}"
    return False, None


def check_grant(grant, run_id=None, now=None, cog_id=None,
                require_run_id=True):
    """(code, detail) when this grant may not be used, else (None, None).

    Checked before any external call: a grant for another run, another Cog,
    or a moment that has passed is refused by THIS Cog. Nothing here fails
    open — a grant whose run binding disagrees with itself, or an invocation
    that carries no `--run-id`, is `grant-invalid`."""
    cog_id = cog_id or SELF_ID["id"]
    if not isinstance(grant, dict):
        return "grant-invalid", "the grant is not a JSON object"
    if grant.get("schema") != GRANT_SCHEMA:
        return "grant-invalid", (f"the grant declares schema "
                                 f"{grant.get('schema')!r}, not "
                                 f"{GRANT_SCHEMA!r}")
    if not isinstance(grant.get("operations"), list):
        return "grant-invalid", "the grant declares no operations list"
    valid = grant.get("valid")
    if not isinstance(valid, dict):
        return "grant-invalid", "the grant declares no validity conditions"
    # ONE run binding, stated twice and required to agree: a grant whose
    # top-level run_id and valid.run_id differ is not a document this Cog
    # can act on, whichever of the two an invocation happens to match.
    top, inner = grant.get("run_id"), valid.get("run_id")
    for name, value in (("run_id", top), ("valid.run_id", inner)):
        if not isinstance(value, str) or not value:
            return "grant-invalid", (f"the grant declares {name} {value!r}; a "
                                     f"grant names the run it belongs to")
    if top != inner:
        return "grant-invalid", (f"the grant's run_id {top!r} and valid.run_id "
                                 f"{inner!r} disagree")
    if run_id is None and require_run_id:
        return "grant-invalid", ("this invocation carries no --run-id; a "
                                 "grant is used only in the run it names")
    expired, detail = _expired(grant, now)
    if expired:
        return "grant-expired", detail
    if run_id is not None and str(top) != str(run_id):
        return "grant-wrong-run", (f"the grant is bound to run {top!r}, not "
                                   f"to this run ({run_id!r})")
    recipient = grant.get("recipient")
    recipient = recipient.get("cog") if isinstance(recipient, dict) else None
    recipient = recipient.get("id") if isinstance(recipient, dict) else None
    if recipient != cog_id:
        return "grant-wrong-recipient", (f"the grant names {recipient!r} as "
                                         f"its recipient, not {cog_id!r}")
    return None, None


def _usable(grant, run_id=None, now=None):
    """(ok, detail) — the whole grant, re-checked before ONE external call.

    Validity is not a load-time property: a long invocation can outlive its
    grant, so every per-call helper comes back through here."""
    bound = run_id if run_id is not None else _INVOCATION_RUN_ID
    code, detail = check_grant(grant, run_id=bound, now=now,
                               require_run_id=False)
    if code:
        return False, f"{code}: {detail}"
    return True, None


def operations(grant, resource=None, action=None):
    """The grant's operations, optionally filtered by resource and action."""
    out = []
    for op in (grant or {}).get("operations") or []:
        if not isinstance(op, dict):
            continue
        if resource is not None and op.get("resource") != resource:
            continue
        if action is not None and op.get("action") != action:
            continue
        out.append(op)
    return out


def read_allowed(grant, target, resource="github", run_id=None, now=None):
    """(ok, detail) for reading TARGET (e.g. a repository). The whole grant
    is re-checked first: expiry and run binding hold per CALL, not per
    invocation.

    `repositories` must be a LIST OF STRINGS. A grant that states a bare
    string is refused by name — never membership-tested, which would
    authorize every substring of it — and any other type is refused rather
    than raising."""
    ok, detail = _usable(grant, run_id, now)
    if not ok:
        return False, detail
    if not isinstance(target, str) or not target:
        return False, (f"{resource} read of {target!r}: a read names one "
                       f"target as a string")
    for op in operations(grant, resource, "read"):
        repositories = op.get("repositories")
        if repositories is None:
            continue
        if not isinstance(repositories, list) or any(
                not isinstance(r, str) for r in repositories):
            return False, (f"the grant's {resource} read operation declares "
                           f"repositories {repositories!r}; a granted read "
                           f"names a LIST of repository strings, and this "
                           f"Cog reads no other shape")
        if target in repositories:
            return True, None
    return False, (f"{resource} read of {target!r} is not in this grant")


def approved_change(grant, change_id, resource="github"):
    """The grant's entry for CHANGE_ID, or None. The grant carries exactly
    the changes a human approved: a change that is not in it is denied, and
    that is the whole check — never a trim of what was requested.

    A `changes` that is not a list of objects contributes nothing: it is not
    iterated blindly, so a malformed grant denies rather than raising."""
    for op in operations(grant, resource, "write"):
        changes = op.get("changes")
        if not isinstance(changes, list):
            continue
        for change in changes:
            if isinstance(change, dict) and change.get("change_id") == change_id:
                return change
    return None


def write_allowed(grant, change_id, target_sha256, content_sha256=None,
                  resource="github", run_id=None, now=None):
    """(ok, detail) for writing CHANGE_ID.

    TWO hashes, and neither may be null:

    - `target_sha256` is the content hash of the target item as the Op READ
      it. Pass the hash you just fetched FRESH from the target: if it
      differs, the world moved since the human approved and the change is
      stale. It is required — a caller with nothing to compare has not
      checked staleness, and this helper never fails open.
    - `content_sha256`, when you pass it, is the hash of the change your
      bundle carries: it must equal the one the human approved, so a bundle
      cannot swap a change's content under an approved id.
    """
    ok, detail = _usable(grant, run_id, now)
    if not ok:
        return False, detail
    change = approved_change(grant, change_id, resource)
    if change is None:
        return False, (f"change {change_id!r} is not in this grant; it was "
                       f"never approved")
    for field in ("content_sha256", "target_sha256"):
        if not isinstance(change.get(field), str) or not change[field]:
            return False, (f"the grant's change {change_id!r} carries "
                           f"{field} {change.get(field)!r}; a granted change "
                           f"carries both hashes")
    if not isinstance(target_sha256, str) or not target_sha256:
        return False, (f"writing change {change_id!r} needs the target's "
                       f"freshly fetched content hash, got "
                       f"{target_sha256!r}")
    if change["target_sha256"] != target_sha256:
        return False, (f"change {change_id!r} was approved against target "
                       f"content {change['target_sha256']!r}, but the target "
                       f"is now {target_sha256!r}")
    if content_sha256 is not None and change["content_sha256"] != content_sha256:
        return False, (f"change {change_id!r} was approved as content "
                       f"{change['content_sha256']!r}, but the one to apply "
                       f"is {content_sha256!r}")
    return True, None


def use(operation, resource, target, outcome, detail=None):
    """One entry for a payload's `authority_use` list: what was attempted,
    against what, and how it ended (authorized | denied | failed)."""
    return {"operation": operation, "resource": resource, "target": target,
            "outcome": outcome, "detail": detail}


# ------------------------------------------------------------ validation --

def _schema_problems(value, schema, check):
    problems = []
    if schema is None or _SchemaValidator is None:      # pragma: no cover
        return problems
    validator = _SchemaValidator(schema)
    for err in sorted(validator.iter_errors(value),
                      key=lambda e: list(e.absolute_path)):
        where = ".".join(str(p) for p in err.absolute_path) or "$"
        problems.append(problem(check, f"{where}: {err.message}"))
    return problems


def validate_input(bundle):
    """The declared input schema, then the package's own input checks.

    The package's checker runs ONLY over a bundle the declared schema
    accepted: a `check_input` written against the declared shape may assume
    it, and a bundle that violates the schema is reported as schema problems
    rather than crashing the author's callback."""
    if not isinstance(bundle, dict):
        return [problem("input", "input is not an object")]
    problems = _schema_problems(bundle, INPUT_SCHEMA, "input")
    if problems:
        return problems
    checker = getattr(task_logic, "check_input", None)
    if checker:
        problems.extend(checker(bundle) or [])
    return problems


def validate_output(payload, bundle):
    """The declared output schema, then the package's contract checks."""
    if not isinstance(payload, dict):
        return [problem("schema", "the task returned a payload that is not "
                                  "an object")]
    problems = _schema_problems(payload, OUTPUT_SCHEMA, "schema")
    checker = getattr(task_logic, "check_output", None)
    if checker:
        problems.extend(checker(payload, bundle) or [])
    return problems


# ------------------------------------------------------------------ health --

def health():
    """(ok, detail). A code Cog has no model dependency; `check` reports what
    it reaches and whether its declared shapes are loadable."""
    missing = [key for key in ("input_schema", "output_schema")
               if _context.get(key) and not (ROOT / _context[key]).exists()]
    if missing:
        return False, f"declared context files missing: {missing}"
    if INPUT_SCHEMA is None or OUTPUT_SCHEMA is None:
        return False, "the manifest declares no input/output schema"
    reaches = ", ".join(f"{r.get('resource')}:{'/'.join(r.get('actions') or [])}"
                        for r in REACHES) or "nothing outside the run"
    return True, (f"{SELF_ID['id']} (kind: code, machinery "
                  f"{MACHINERY_VERSION}) reaches {reaches}")


# ------------------------------------------------------------------ invoke --

def binding():
    """The binding identity of a code Cog: which code produced this result.
    `model` is ABSENT, not null — there is no model in the loop."""
    return {"kind": "code", "cog": dict(SELF_ID),
            "task_logic_sha256": task_logic_sha256(),
            "machinery": MACHINERY_VERSION}


def _envelope(task, ok, payload=None, problems=None, error=None, latency=None):
    return {
        "envelope": 1,
        "cog": dict(SELF_ID),
        "task": task,
        "ok": bool(ok),
        "error": error,
        "payload": payload,
        "raw": None,
        "problems": problems or [],
        "binding": binding(),
        "timing": {"latency_s": latency},
    }


def _fail(task, code, detail):
    return _envelope(task, False, error={"code": code, "detail": str(detail)},
                     problems=[problem(code, detail)])


def invoke(bundle, grant=None, journal=None, run_id=None, task=DEFAULT_TASK,
           now=None):
    """Run this Cog over one input bundle. Returns an envelope-v1 dict.

    `grant` is the grant document (a dict) or None; `journal` is a Journal or
    None. Fails CLOSED: a Cog that declares `reaches` and is handed no grant
    refuses before `run` is called, and an invalid grant is refused with the
    reason named."""
    global _INVOCATION_RUN_ID
    import time
    started = time.monotonic()

    problems = validate_input(bundle)
    if problems:
        env = _fail(task, "invalid-input",
                    "; ".join(p["detail"] for p in problems[:5]))
        env["problems"] = problems
        return env

    if REACHES and grant is None:
        return _fail(task, "no-grant",
                     f"{SELF_ID['id']} declares reaches "
                     f"{[r.get('resource') for r in REACHES]} and was invoked "
                     f"with no grant; a code Cog does not reach outside the "
                     f"run without one")
    if grant is not None:
        code, detail = check_grant(grant, run_id=run_id, now=now)
        if code:
            return _fail(task, code, detail)
    _INVOCATION_RUN_ID = run_id

    # The journal is read BEFORE any work: a journal this Cog cannot read in
    # full cannot prove what was already done outside the run.
    #
    # Two different failures, two names. `journal-corrupt` is a journal whose
    # CONTENT cannot be trusted; `journal-unreadable` is one this process
    # cannot read or create at all — a permission, a directory where a file
    # belongs, a vanished mount. Both are structured ok:false envelopes:
    # neither is a traceback.
    if journal is not None:
        try:
            journal.read()
        except JournalCorrupt as exc:
            return _fail(task, "journal-corrupt", str(exc))
        except OSError as exc:
            return _fail(task, "journal-unreadable",
                         f"{journal.path} cannot be read "
                         f"({type(exc).__name__}: {exc}); a Cog that cannot "
                         f"read its journal cannot know what it already did "
                         f"outside the run, and does nothing")

    try:
        result = task_logic.run(bundle, grant, journal)
    except JournalCorrupt as exc:
        return _fail(task, "journal-corrupt", str(exc))
    except Exception as exc:                            # the task's own bug
        return _fail(task, "task-failed", f"{type(exc).__name__}: {exc}")
    if (not isinstance(result, tuple) or len(result) != 2):
        return _fail(task, "task-failed",
                     "task_logic.run must return (payload, problems)")
    payload, task_problems = result
    # The package's output checker runs inside the SAME exception boundary as
    # `run`: a checker that trips over a payload it did not
    # expect is a named ok:false envelope, never a traceback out of the CLI.
    # It gets its own code because "the task is broken" and "the task's
    # self-check is broken" are different repairs.
    try:
        problems = list(task_problems or []) + validate_output(payload, bundle)
    except JournalCorrupt as exc:
        return _fail(task, "journal-corrupt", str(exc))
    except Exception as exc:                    # the package's own checker
        return _fail(task, "output-check-failed",
                     f"{type(exc).__name__}: {exc}")
    return _envelope(task, True, payload=payload, problems=problems,
                     latency=round(time.monotonic() - started, 3))
