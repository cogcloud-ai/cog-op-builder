"""Op spec: load, validate, refuse by name, and evaluate mapping expressions.

Machinery master (cog-smith `templates/op/src/`). An Op package never edits
this file — `smith op check` enforces it by hash, exactly as `smith check`
enforces Cog machinery. If an Op needs behaviour this module does not have,
the answer is a Cog step, never a script in the Op.

The spec is `openteams/op-manifest [0.2]` (the published execution profile)
or `openteams/op-manifest [0.1]` (every Op written before it): identity,
declared `inputs`, a list of Cog `steps` with mapping expressions for their
requests, optional `outputs`, and the `track` records. The vocabulary is
CLOSED — anything the runner subset does not carry is refused BY NAME at
load, with the reason, so an author never discovers a missing construct
mid-run.

A `[0.2]` document is held to the profile's tightenings (machinery 0.11.0):
`title` where `[0.1]` says `name`, typed identity fields, a stated
`cog.version`, `targets` only, `read`/`write` actions only, operator objects
with exactly their operator's keys, no `$path` beginning with `~`, every
present key of the type the profile's schema gives it, no `foreach` artifact
Gate that reads its loop variable, and cycle limits that read inputs only. At
run time it also requires the named Cogs to be present at their stated
versions and every envelope to name the step's Cog, and a proposed change
names what it changes as `target`. A `[0.1]` document keeps the 0.10.0
behaviour, except for the safety fixes both profiles share: a reserved
`$run_dir` entry is refused in any case, and a path no filesystem can name
fails the step.
"""
from __future__ import annotations

import hashlib
import copy
import errno
import json
import os
import re
import stat
import unicodedata
from pathlib import Path

import yaml

try:                                                   # pragma: no cover
    import jsonschema
    _SchemaValidator = (getattr(jsonschema, "Draft202012Validator", None)
                        or getattr(jsonschema, "Draft7Validator", None))
except ImportError:                                    # pragma: no cover
    _SchemaValidator = None

SCHEMA_STRING_0_1 = "openteams/op-manifest [0.1]"
SCHEMA_STRING_0_2 = "openteams/op-manifest [0.2]"
#: Every Op manifest profile this machinery runs (0.11.0), oldest first.
SCHEMA_STRINGS = (SCHEMA_STRING_0_1, SCHEMA_STRING_0_2)
#: The `[0.1]` string, under the name every caller before 0.11.0 imported:
#: those callers build `[0.1]` documents (with `name`), so this constant keeps
#: meaning `[0.1]`. A new document declares `SCHEMA_STRING_0_2`.
SCHEMA_STRING = SCHEMA_STRING_0_1
PROFILE_0_1 = "0.1"
PROFILE_0_2 = "0.2"
#: Where a run context carries its document's profile. `$`-prefixed, so it
#: can never be a mapping-path root an Op reads nor a `foreach` variable.
PROFILE_CONTEXT_KEY = "$profile"
#: The field of a proposed change that names what it changes — the target a
#: write admission must list. `[0.1]` documents name it `repository`.
CHANGE_TARGET_KEYS = {PROFILE_0_1: "repository", PROFILE_0_2: "target"}
GATE_POLICY = "envelope-ok-no-error-problems"
#: A human Gate is a POLICY on a step, never a step of its own: the step
#: runs its Cog, the envelope goes through the ordinary policy, and only a
#: passing envelope reaches the human.
HUMAN_GATE_POLICY = "human"
GATE_POLICIES = (GATE_POLICY, HUMAN_GATE_POLICY)
#: WHAT a human Gate decides about (machinery 0.7.0). `changes` — the
#: default, and every human Gate before 0.7.0 — is a list of proposed
#: changes, each approved, rejected or edited, feeding a write grant.
#: `artifact` is ONE versioned thing the step produced or completed — a
#: contract, a candidate package, a body of evidence — accepted or rejected
#: as a whole, bound to the exact digests the Op names for it.
DECIDES_CHANGES = "changes"
DECIDES_ARTIFACT = "artifact"
GATE_DECIDES = (DECIDES_CHANGES, DECIDES_ARTIFACT)
#: The closed shape of a declared artifact: what KIND of thing it is, the
#: named `digests` that pin it (each a sha256), and optional `id`, `summary`
#: and `detail` for the person deciding. The Op names the digests from its
#: own mappings — `{$sha256: ...}` of a payload it holds, or a digest a
#: deterministic Cog reported — so an acceptance is about bytes, never about
#: a step id.
ARTIFACT_KEYS = {"kind", "id", "summary", "digests", "detail"}
ARTIFACT_REQUIRED = ("kind", "digests")
STEP_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
#: A `foreach` loop variable is a name: it becomes a mapping-path root.
LOOP_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ON_FAIL = ("stop", "skip", "retry-once")

TOP_KEYS = {"schema", "id", "version", "name", "description", "inputs",
            "steps", "outputs", "track", "authority", "cycle"}
STEP_KEYS = {"id", "name", "depends_on", "cog", "foreach", "input",
             "expected_outcome", "gate", "on_fail", "authority", "repeat"}
#: `[0.2]` calls the Op's and each step's human-readable name `title`; `name`
#: is refused by name there (and is the title of a `[0.1]` document).
TOP_KEYS_0_2 = (TOP_KEYS - {"name"}) | {"title"}
STEP_KEYS_0_2 = (STEP_KEYS - {"name"}) | {"title"}
COG_KEYS = {"id", "version", "source", "task"}
INPUT_KEYS = {"name", "description", "required", "default", "schema"}
FOREACH_KEYS = {"items", "as"}
#: `repeat: {count, require, mode}` — the same request invoked `count` times,
#: of which `require` must pass (machinery 0.6.0). The
#: ceiling is small on purpose: repetition is evidence, not a budget.
REPEAT_KEYS = {"count", "require", "mode"}
MAX_REPEAT = 5
#: How many of the `count` repeats actually run (machinery 0.6.4). `all`
#: asks every time and unions the answers — for a step whose RECALL varies
#: run to run. `until-required` stops as soon as
#: `require` repeats have passed — for a step that wants ONE clean answer and
#: must not end a 150-batch run because one answer was rejected.
REPEAT_ALL = "all"
REPEAT_UNTIL_REQUIRED = "until-required"
REPEAT_MODES = (REPEAT_ALL, REPEAT_UNTIL_REQUIRED)
GATE_KEYS = {"policy", "guards", "decides", "artifact"}
TRACK_KEYS = {"records"}
#: Authority vocabulary. Top level: how long a grant
#: this Op issues stays valid. Per step: what the step REQUIRES — a step
#: never grants itself anything.
AUTHORITY_TOP_KEYS = {"ttl_minutes"}
STEP_AUTHORITY_KEYS = {"requires"}
#: What an operation may touch is named `targets`: a repository, a site, a
#: document store, an API — the runner treats each as an opaque string.
#: `repositories` is the name existing documents use for the same list and is
#: read as an alias; a document that states both is refused (0.8.0).
TARGET_KEYS = ("targets", "repositories")
REQUIREMENT_KEYS = {"resource", "action", "changes", *TARGET_KEYS}
#: `[0.2]` names targets `targets` only, and an action is a read or a write.
REQUIREMENT_KEYS_0_2 = {"resource", "action", "changes", "targets"}
ACTIONS_0_2 = ("read", "write")
DEFAULT_TTL_MINUTES = 60

# Refused by name, with the reason it is refused. A value of None means a
# step kind with its own reason below: there is no tool: step kind —
# deterministic work is a Cog of kind: code, invoked as a cog: step — and no
# human: step kind either: a human Gate is `gate: {policy: human}` on a step.
REFUSED_TOP = {"state": "durable state across runs is not part of this Op "
                         "spec; a run reads only its request and its own steps"}
REFUSED_STEP = {"tool": None, "human": None}
REFUSED_STEP_REASON = {
    "tool": ("there is no tool: step kind — deterministic work is a Cog of "
             "kind: code, invoked as a cog: step"),
    "human": ("there is no human: step kind — a human Gate is a policy on "
              "the step that produces what the human decides about, "
              "gate: {policy: human}"),
}

# Mapping-expression operators: an object whose key set is EXACTLY one of
# these is an operator; every other object is walked; scalars are literals.
OPERATORS = (
    frozenset({"$from"}),
    frozenset({"$from", "$default"}),
    frozenset({"$path"}),
    frozenset({"$run_dir"}),
    frozenset({"$stem"}),
    frozenset({"$literal"}),
    frozenset({"$sha256"}),
)
OPERATOR_NAMES = ("$from, $from/$default, $path, $run_dir, $stem, $literal, "
                  "$sha256")
#: Every `$`-prefixed name the closed vocabulary knows. A `$` key that is not
#: one of these is an unknown operator WHEREVER it appears — sibling keys do
#: not turn `$join` into ordinary data.
KNOWN_DOLLAR_KEYS = frozenset({"$from", "$default", "$path", "$run_dir",
                               "$stem", "$literal", "$sha256"})
PATH_ROOTS = ("inputs", "steps", "run", "request")
#: What a step's result exposes to later mappings. `decision` is the human
#: Gate's answer, present only on a step whose gate policy is `human`.
STEP_PATHS = ("payload", "envelope", "decision")
#: Roots refused BY NAME. A grant is trusted invocation context: it never
#: travels inside a request document and no mapping expression can read or
#: build one.
REFUSED_PATH_ROOTS = {
    "grants": ("a grant is never readable from a mapping expression: "
               "authority travels beside the request, never inside it"),
}
#: The run directory's CONTROL entries: the runner owns them, and no mapping
#: expression may name one. `$run_dir` makes a place for a Cog's OUTPUT; a
#: Cog handed `runs/<id>/grants` as an output directory could overwrite the
#: very documents that authorize it. Since 0.10.0 the list is the run
#: directory's whole layout: the step requests a later step's request is
#: built beside, the envelopes that are the run's evidence, and the copy of
#: the input request a resume reads back are the runner's too.
RESERVED_RUN_SUBPATHS = ("grants", "pending", "decisions", "journal",
                         "run.lock", "track.json", "requests", "envelopes",
                         "input-request.json")
#: The reserved FILES, whose atomic rewrites go through a temporary sibling
#: named `<file>.<pid>.tmp`: a directory in that place would make the next
#: rewrite of the Track fail, so `<file>.` names the file too.
RESERVED_RUN_FILES = ("run.lock", "track.json", "input-request.json")

# A Cog's conventional lifecycle tasks, for steps whose interface declares no
# audience. Kept here (not imported from cog-smith) because this module is
# vendored into every Op package and must run without cog-smith installed.
LIFECYCLE_TASKS = {"resolve", "use", "check", "eval", "test", "bundle", "serve"}


class OpSpecError(Exception):
    """One or more one-sentence problems with a spec, request, or mapping."""

    def __init__(self, problems):
        self.problems = [problems] if isinstance(problems, str) else list(problems)
        super().__init__("\n".join(self.problems))


def profile_of(doc):
    """The profile a document declares: `0.2` for `openteams/op-manifest
    [0.2]`, and `0.1` for anything else — a `[0.1]` document, and a document
    whose schema is refused anyway, which is read with the `[0.1]` key sets
    so its other findings stay the ones 0.10.0 reported."""
    if isinstance(doc, dict) and doc.get("schema") == SCHEMA_STRING_0_2:
        return PROFILE_0_2
    return PROFILE_0_1


def step_title(step):
    """A step's human-readable name: `title` in `[0.2]`, `name` in `[0.1]`."""
    if not isinstance(step, dict):
        return None
    return step.get("title", step.get("name"))


def change_target_key(profile):
    """The field a proposed change names what it changes under: `target` in
    `[0.2]`, `repository` in `[0.1]`."""
    return CHANGE_TARGET_KEYS.get(profile, CHANGE_TARGET_KEYS[PROFILE_0_1])


# ---------------------------------------------------------------- lookup --

def lookup(path, ctx):
    """(found, value) for a mapping path. Dotted keys index objects,
    integers index arrays."""
    segments = str(path).split(".")
    root = segments[0]
    if root in PATH_ROOTS or root in ctx:
        current = ctx.get(root)
    else:
        return False, None
    for segment in segments[1:]:
        if isinstance(current, dict):
            if segment not in current:
                return False, None
            current = current[segment]
        elif isinstance(current, list):
            try:
                index = int(segment)
            except ValueError:
                return False, None
            if not -len(current) <= index < len(current):
                return False, None
            current = current[index]
        else:
            return False, None
    return True, current


def dollar_keys(expr):
    """The `$`-prefixed keys of a mapping-expression object."""
    return sorted(k for k in expr if isinstance(k, str) and k.startswith("$"))


def unknown_dollar_keys(expr):
    """The `$`-prefixed keys that name no operator in the closed vocabulary."""
    return sorted(k for k in dollar_keys(expr) if k not in KNOWN_DOLLAR_KEYS)


def operator_keys(expr):
    """The operator key set of a mapping-expression object, or None when the
    object is an ordinary one to walk recursively.

    Only an EXACT recognized key set is an operator. Any other
    object is walked — `{"$from": "literal text", "label": "x"}` and
    `{"$from": "inputs.note", "$stem": "x"}` are both ordinary data — EXCEPT
    that a `$`-prefixed key naming no operator at all (`{"$join": [...]}`,
    with or without siblings) is an unknown operator and is always refused.
    """
    keys = frozenset(expr)
    if keys in OPERATORS:
        return keys
    unknown = unknown_dollar_keys(expr)
    if unknown:
        raise OpSpecError(
            f"mapping expression uses unknown operator(s) {unknown}; the "
            f"mapping vocabulary is closed ({OPERATOR_NAMES}).")
    return None


def normalized_subpath(subpath):
    """SUBPATH with `.` and `..` collapsed — what it actually NAMES.

    The reserved-name check reads this, never the text as written: a
    dynamic operand of `outputs/../grants` names `grants` however it is
    spelled."""
    return os.path.normpath(str(subpath or "."))


def caseless(name):
    """NAME as a reserved entry is compared (0.11.0): Unicode canonical
    caseless matching (D145) — NFD, full case folding, NFD again.

    A filesystem that folds case (APFS and NTFS by default) opens the
    runner's `requests` for a step handed `Requests`, so a case-sensitive
    comparison let `$run_dir: Requests` — or `GRANTS`, or `Track.json.1.tmp`
    — give a Cog the very control entries the rule reserves. Folding here
    makes the verdict the same on every filesystem, whether or not it folds:
    the reserved names are lowercase ASCII, so each is its own caseless form,
    and a spelling such as `trac\u212a.json` (a Kelvin sign, which folds to
    `k`) is caught too."""
    return unicodedata.normalize(
        "NFD", unicodedata.normalize("NFD", str(name)).casefold())


def reserved_run_subpath(subpath):
    """The control entry SUBPATH names or lives under, or None. The subpath
    is NORMALISED first, and its first component compared CASELESSLY
    (`caseless`, 0.11.0), so no spelling of a reserved name gets through —
    and everything under one is reserved with it."""
    normalized = normalized_subpath(subpath)
    parts = [p for p in Path(normalized).parts if p not in (".", "/")]
    if not parts:
        return None
    first = caseless(parts[0])
    if first in RESERVED_RUN_SUBPATHS:
        return first
    for name in RESERVED_RUN_FILES:
        if first.startswith(name + "."):
            return name
    return None


def reserved_identities(run_dir):
    """{(st_dev, st_ino): name} for the run directory and each control entry
    present in it (0.11.0). What `run_dir_path` compares an existing
    component with: a filesystem may alias an entry under a spelling no
    rule lists — Unicode compatibility folding (ZFS `normalization=formKC`),
    a hard link to a control file — and the IDENTITY of the entry is what a
    Cog would be handed. The run directory itself is listed because a
    directory that is the run root holds every entry."""
    found = {}
    for name in (".",) + RESERVED_RUN_SUBPATHS:
        try:
            info = os.lstat(Path(run_dir) / name)
        except OSError:
            continue                     # not created yet: the name rule holds
        found[(info.st_dev, info.st_ino)] = name
    return found


def names_run_root(subpath):
    """True when SUBPATH, normalised, names the run directory ITSELF — `""`,
    `"."`, `"out/.."` (machinery 0.10.0). The run root holds every control
    entry, so handing it to a Cog as an output directory hands it all of
    them."""
    parts = [p for p in Path(normalized_subpath(subpath)).parts
             if p not in (".", "/")]
    return not parts


def run_dir_path(subpath, run_dir):
    """`<run dir>/<subpath>`, created — refusing anything that would land
    outside the run, or on one of the runner's own control entries.
    `$run_dir` makes a directory INSIDE this run, so an absolute operand, a
    `..` escape, and a symlink out of the run are all refused BEFORE
    anything is created."""
    if not isinstance(subpath, str):
        raise OpSpecError(f"$run_dir takes a relative subpath string, got "
                          f"{subpath!r}.")
    if Path(subpath).is_absolute():
        raise OpSpecError(f"$run_dir subpath {subpath!r} is absolute; "
                          f"$run_dir names a directory inside this run.")
    if names_run_root(subpath):
        # Machinery 0.10.0: an empty, `.` or null operand used to hand the
        # Cog the run root itself, and every control entry with it.
        raise OpSpecError(f"$run_dir subpath {subpath!r} names the run "
                          f"directory itself, which the runner owns; "
                          f"$run_dir names a directory inside this run.")
    reserved = reserved_run_subpath(subpath)
    if reserved:
        raise OpSpecError(f"$run_dir subpath {subpath!r} names the run's "
                          f"{reserved!r}, which the runner owns; "
                          f"{list(RESERVED_RUN_SUBPATHS)} are reserved.")
    candidate = Path(normalized_subpath(subpath))
    base = Path(run_dir).resolve()
    try:
        target = (base / candidate).resolve()
    except (ValueError, OSError, RuntimeError) as exc:
        # An operand no filesystem can name — an embedded NUL (ValueError),
        # or a link loop, which Python 3.12's resolve raises as RuntimeError
        # (3.13 returns the path, and the walk below refuses the link) — is
        # the operand's fault and recurs on every resume: an evaluation
        # failure (0.11.0), exactly as for `$path`, never an exception that
        # leaves the run and the step `running`.
        raise OpSpecError(invalid_path_problem(
            "$run_dir", subpath, subpath, exc)) from exc
    if target != base and base not in target.parents:
        raise OpSpecError(f"$run_dir subpath {subpath!r} resolves outside the "
                          f"run directory; $run_dir names a directory inside "
                          f"this run.")
    # No component may be a link, even one pointing back inside the run: an
    # alias is how a step would be handed the runner's own control entries
    # under another name. Nor may an existing component BE one of them, or
    # the run root, under a name the caseless rule does not list (0.11.0):
    # with links refused, only the filesystem itself can alias an entry
    # (`reserved_identities`), and comparing what each component IS closes
    # that whatever the filesystem folds.
    identities = reserved_identities(base)
    current = base
    for part in candidate.parts:
        current = current / part
        try:
            info = os.lstat(current)
        except (FileNotFoundError, NotADirectoryError):
            break                        # nothing exists below here
        except OSError as exc:
            # A component too long to name raised out of the walk before
            # `mkdir` could classify it: the same rule as there applies.
            if exc.errno not in INVALID_NAME_ERRNOS:
                raise
            raise OpSpecError(invalid_path_problem(
                "$run_dir", subpath, subpath, exc)) from exc
        if stat.S_ISLNK(info.st_mode):
            raise OpSpecError(
                f"$run_dir subpath {subpath!r} passes through {part!r}, "
                f"which is a symlink; $run_dir names a real directory "
                f"inside this run.")
        alias = identities.get((info.st_dev, info.st_ino))
        if alias == ".":
            raise OpSpecError(
                f"$run_dir subpath {subpath!r} reaches the run directory "
                f"itself under another name, and the runner owns it; "
                f"$run_dir names a directory inside this run.")
        if alias:
            raise OpSpecError(
                f"$run_dir subpath {subpath!r} reaches the run's {alias!r} "
                f"under another name, and the runner owns it; "
                f"{list(RESERVED_RUN_SUBPATHS)} are reserved.")
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # A name the filesystem refuses (too long, not representable) is the
        # operand's fault and an evaluation failure (0.11.0). So is a path
        # the run already holds as something other than a directory — an
        # earlier step's FILE at `work`, for `work` or `work/sub` — which
        # would refuse every resume the same way. Anything else — a full
        # disk, a permission the machine took away — is the machine's, an
        # interruption like a crash: raised, and the `running` Track a
        # resume picks up stays true.
        if exc.errno in NOT_A_DIRECTORY_ERRNOS:
            raise OpSpecError(
                f"$run_dir subpath {subpath!r} names a path this run already "
                f"holds as something other than a directory; $run_dir names "
                f"a directory inside this run.") from exc
        if exc.errno not in INVALID_NAME_ERRNOS:
            raise
        raise OpSpecError(invalid_path_problem(
            "$run_dir", subpath, subpath, exc)) from exc
    return str(target)


#: The errors that say a NAME is impossible rather than that the machine
#: failed (0.11.0): the operand of `$run_dir` is at fault, not the run.
INVALID_NAME_ERRNOS = frozenset(
    code for code in (getattr(errno, name, None)
                      for name in ("ENAMETOOLONG", "EINVAL", "EILSEQ"))
    if code is not None)


#: The errors `mkdir` gives when a component already exists and is not a
#: directory (0.11.0): the run's own contents refuse the operand.
NOT_A_DIRECTORY_ERRNOS = frozenset({errno.EEXIST, errno.ENOTDIR})


def invalid_path_problem(operator, operand, value, exc):
    """The reason an operator's value names no path, in a full sentence."""
    return (f"{operator} of {operand!r} evaluates to {value!r}, which is not "
            f"a path this machine can name ({type(exc).__name__}: {exc}).")


def step_input(step, context):
    """The mapping expression a step's request is evaluated from.

    `[0.2]` reads `input` as written whenever it is present: `false`, `0`,
    `""`, `null`, and `[]` are requests a Cog may be sent, exactly as their
    `$literal` forms are, and only an omitted `input` means `{}` (0.11.0).
    `[0.1]` keeps the 0.10.0 reading, where any falsy `input` became `{}`."""
    if isinstance(context, dict) and \
            context.get(PROFILE_CONTEXT_KEY) == PROFILE_0_2:
        return step.get("input", {})
    return step.get("input") or {}


def evaluate(expr, ctx):
    """Resolve a mapping expression against a run context
    {inputs, steps, run, request, <loop variables>}."""
    if isinstance(expr, dict):
        keys = operator_keys(expr)
        if keys is not None:
            if "$literal" in keys:
                return expr["$literal"]
            if "$from" in keys:
                found, value = lookup(expr["$from"], ctx)
                if found and value is not None:
                    return value
                if "$default" in keys:
                    return evaluate(expr["$default"], ctx)
                if not found:
                    raise OpSpecError(
                        f"mapping path {expr['$from']!r} is not available in "
                        f"this run and the expression declares no $default.")
                return None
            if "$path" in keys:
                value = evaluate(expr["$path"], ctx)
                if value is None:
                    return None
                if (ctx.get(PROFILE_CONTEXT_KEY) == PROFILE_0_2
                        and str(value).startswith("~")):
                    # [0.2] (0.11.0): a computed `~` path is refused here,
                    # as a literal one is at load. [0.1] expands it.
                    raise OpSpecError(
                        f"$path of {expr['$path']!r} evaluates to "
                        f"{value!r}, which begins with ~; an Op's paths "
                        f"never depend on whose machine runs it (rule "
                        f"path-no-home).")
                try:
                    path = Path(str(value)).expanduser()
                    if not path.is_absolute():
                        path = Path(ctx["request"]["dir"]) / path
                    return str(path.resolve())
                except (ValueError, OSError, RuntimeError) as exc:
                    # A value no filesystem can name — an embedded NUL, a
                    # `~user` with no home (RuntimeError), a name too long
                    # or a link loop (OSError) — is the VALUE's fault and
                    # recurs on every resume: an evaluation failure, which
                    # fails the step with the reason (0.11.0), never an
                    # exception that leaves the Track `running`. A resolve
                    # that is not `strict` tolerates a missing or unreadable
                    # file, so what reaches here is about the value.
                    raise OpSpecError(invalid_path_problem(
                        "$path", expr["$path"], value, exc)) from exc
            if "$run_dir" in keys:
                value = evaluate(expr["$run_dir"], ctx)
                return run_dir_path(value, ctx["run"]["dir"])
            if "$stem" in keys:
                value = evaluate(expr["$stem"], ctx)
                return None if value is None else Path(str(value)).stem
            if "$sha256" in keys:
                # The canonical digest of a JSON value (machinery 0.7.0):
                # sorted keys, compact separators, UTF-8, Unicode unescaped —
                # the same bytes cog-author, Workbench and the runner's own
                # `canonical_sha256` hash. A digest of NOTHING is refused:
                # an artifact Gate that read a null contract would otherwise
                # ask a person to accept the hash of `null`.
                value = evaluate(expr["$sha256"], ctx)
                if value is None:
                    raise OpSpecError(
                        f"$sha256 of {expr['$sha256']!r} has nothing to "
                        f"digest: the value is null or not available in "
                        f"this run.")
                return canonical_sha256(value)
        return {k: evaluate(v, ctx) for k, v in expr.items()}
    if isinstance(expr, list):
        return [evaluate(item, ctx) for item in expr]
    return expr


def canonical_sha256(value):
    """The hash of a JSON value, canonically serialized — the same bytes for
    the same document however it was written. Mirrored in op_runner (which
    imports this module) so one definition serves the `$sha256` operator,
    the pending document and the decision check."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def reads_steps(expr):
    """True when an expression reads any earlier step's result — the runner
    uses this to list a step's request as null in a dry run."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            keys = frozenset(node)
            if keys in OPERATORS and "$literal" in keys:
                return
            if (keys in OPERATORS and "$from" in keys
                    and str(node["$from"]).split(".")[0] == "steps"):
                found.append(True)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(expr)
    return bool(found)


def expression_reads(expr):
    """Every read EXPR makes, in document order (0.11.0): `("$from", PATH)`
    for each `$from` — one nested in a `$default` or another operator's
    operand included — and `("$run_dir", OPERAND)` and `("$path", OPERAND)`
    for the operators that read the run's or the request's directory. A
    `$literal` is data and reads nothing."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            keys = operator_keys(node)
            if keys is not None and "$literal" in keys:
                return
            if keys is not None and "$from" in keys:
                found.append(("$from", node["$from"]))
            elif keys is not None:
                found.extend((key, node[key]) for key in ("$run_dir", "$path")
                             if key in keys)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(expr)
    return found


def path_root(path):
    """The root segment of a mapping PATH, or None when it is not a string."""
    return path.split(".")[0] if isinstance(path, str) else None


# ------------------------------------------------------------ validation --

def _expr_problems(expr, where, input_names, step_ids, dep_ids, loop_vars,
                   problems, human_steps=(), strict=False):
    """Every problem with one mapping expression. STRICT is a `[0.2]`
    document (0.11.0): an object holding an operator key has exactly that
    operator's key set, and a literal `$path` never begins with `~`."""
    def walk(node, at):
        _expr_problems(node, at, input_names, step_ids, dep_ids, loop_vars,
                       problems, human_steps, strict)

    if isinstance(expr, dict):
        keys = frozenset(expr)
        if keys in OPERATORS:
            if "$literal" in keys:
                return
            if "$from" in keys:
                _path_problems(expr["$from"], where, input_names, step_ids,
                               dep_ids, loop_vars, problems, human_steps)
                if "$default" in keys:
                    walk(expr["$default"], where)
                return
            if "$run_dir" in keys:
                problem = _literal_run_dir_problem(expr["$run_dir"], where)
                if problem:
                    problems.append(problem)
                    return
            if "$path" in keys and strict:
                problem = _literal_path_problem(expr["$path"], where)
                if problem:
                    problems.append(problem)
                    return
            for key in ("$path", "$run_dir", "$stem", "$sha256"):
                if key in keys:
                    walk(expr[key], where)
            return
        unknown = unknown_dollar_keys(expr)
        if unknown:
            problems.append(
                f"{where} uses unknown mapping operator(s) {unknown}; the "
                f"mapping vocabulary is closed ({OPERATOR_NAMES}).")
            return
        if strict and dollar_keys(expr):
            # [0.2]: `{$from: x, label: y}` and a `$default` without `$from`
            # were ordinary data in [0.1], so a misspelled sibling silently
            # changed what the step was sent.
            operators = dollar_keys(expr)
            others = sorted(str(k) for k in expr if k not in operators)
            held = (f"operator key(s) {operators} beside {others}" if others
                    else f"operator keys {operators}, which are no "
                         f"operator's key set")
            problems.append(
                f"{where} holds {held}; an object holding an operator key "
                f"has exactly that operator's keys ({OPERATOR_NAMES}), and "
                f"data that needs $-prefixed keys is written with $literal "
                f"(rule operator-exact-keyset).")
            return
        for key, value in expr.items():
            if not isinstance(key, str):
                problems.append(f"{where} has key {key!r}, which is not a "
                                f"string; a request document's keys are "
                                f"strings.")
                continue
            walk(value, f"{where}.{key}")
    elif isinstance(expr, list):
        for index, item in enumerate(expr):
            walk(item, f"{where}[{index}]")


def _literal_path_problem(operand, where):
    """Why a `$path` operand is refused AT LOAD in a `[0.2]` document, or
    None: a literal (a string, or a `$literal` of one) that begins with `~`.
    A computed operand is checked when it is evaluated."""
    if isinstance(operand, dict) and frozenset(operand) == frozenset({"$literal"}):
        operand = operand["$literal"]
    if isinstance(operand, str) and operand.startswith("~"):
        return (f"{where} asks $path for {operand!r}, which begins with ~; an "
                f"Op's paths never depend on whose machine runs it (rule "
                f"path-no-home).")
    return None


def _literal_run_dir_problem(operand, where):
    """Why a `$run_dir` operand is refused AT LOAD, or None. Only what the
    operand's text already settles is checked here — a string, or a
    `$literal` of one; an expression operand is checked when it is evaluated
    (`run_dir_path`). An operand that can never evaluate to a string (null,
    a number, a list, a plain object) is refused here too (0.10.0)."""
    if isinstance(operand, dict) and frozenset(operand) == frozenset({"$literal"}):
        operand = operand["$literal"]
    elif isinstance(operand, dict) and frozenset(operand) in OPERATORS:
        return None                      # evaluated, then checked
    if isinstance(operand, dict) and unknown_dollar_keys(operand):
        return None                      # refused by name by the walk
    if not isinstance(operand, str):
        return (f"{where} asks $run_dir for {operand!r}; $run_dir takes a "
                f"relative subpath string naming a directory inside this "
                f"run.")
    if Path(operand).is_absolute() or ".." in Path(operand).parts:
        return (f"{where} asks $run_dir for {operand!r}; $run_dir names a "
                f"directory inside this run, so the subpath is relative and "
                f"never leaves the run directory.")
    if names_run_root(operand):
        return (f"{where} asks $run_dir for {operand!r}, which names the run "
                f"directory itself; $run_dir names a directory inside this "
                f"run, never the run root that holds the runner's own control "
                f"entries.")
    reserved = reserved_run_subpath(operand)
    if reserved:
        return (f"{where} asks $run_dir for {operand!r}, which names the "
                f"run's {reserved!r}; {list(RESERVED_RUN_SUBPATHS)} are the "
                f"runner's own control entries and no step writes into them.")
    return None


def _path_problems(path, where, input_names, step_ids, dep_ids, loop_vars,
                   problems, human_steps=()):
    if not isinstance(path, str) or not path:
        problems.append(f"{where}: $from takes a dotted path string, got "
                        f"{path!r}.")
        return
    segments = path.split(".")
    root = segments[0]
    if root == "inputs":
        if len(segments) < 2 or segments[1] not in input_names:
            problems.append(f"{where} reads input {'.'.join(segments[1:2]) or '?'!r}, "
                            f"which the Op spec does not declare.")
    elif root == "steps":
        if len(segments) < 3 or segments[2] not in STEP_PATHS:
            problems.append(f"{where} reads {path!r}; a step path is "
                            f"steps.<id>.payload, steps.<id>.envelope or "
                            f"steps.<id>.decision.")
            return
        target = segments[1]
        if target not in step_ids:
            problems.append(f"{where} reads step {target!r}, which the Op "
                            f"spec does not declare.")
        elif target not in dep_ids:
            problems.append(f"{where} reads {path!r} without depending on "
                            f"{target!r}; add it to that step's depends_on.")
        elif segments[2] == "decision" and target not in human_steps:
            problems.append(f"{where} reads {path!r}, but step {target!r} "
                            f"has no human Gate; only a step with "
                            f"gate.policy: human produces a decision.")
    elif root == "run":
        if len(segments) < 2 or segments[1] not in ("dir", "id"):
            problems.append(f"{where} reads {path!r}; the run paths are "
                            f"run.dir and run.id.")
    elif root == "request":
        if len(segments) < 2 or segments[1] != "dir":
            problems.append(f"{where} reads {path!r}; the only request path "
                            f"is request.dir.")
    elif root in REFUSED_PATH_ROOTS:
        problems.append(f"{where} reads {path!r}: "
                        f"{REFUSED_PATH_ROOTS[root]}.")
    elif root not in loop_vars:
        problems.append(f"{where} reads {path!r}, whose root is neither a "
                        f"declared input, a step, run/request, nor this "
                        f"step's foreach variable.")


def gate_policy(step):
    """The step's Gate policy (the envelope policy when it declares none)."""
    gate = step.get("gate")
    if not isinstance(gate, dict):
        return GATE_POLICY
    return gate.get("policy", GATE_POLICY)


def human_gate_steps(steps):
    """The ids of the steps whose Gate is a human one."""
    return {s["id"] for s in steps
            if _has_id(s) and gate_policy(s) == HUMAN_GATE_POLICY}


def gate_decides(step):
    """What the step's human Gate decides about: `changes` (the default) or
    `artifact` (machinery 0.7.0). Meaningful only when the policy is human."""
    gate = step.get("gate")
    if not isinstance(gate, dict):
        return DECIDES_CHANGES
    return gate.get("decides", DECIDES_CHANGES)


def artifact_gate_steps(steps):
    """The ids of the human-gated steps that decide about an ARTIFACT."""
    return {s["id"] for s in steps
            if _has_id(s) and gate_policy(s) == HUMAN_GATE_POLICY
            and gate_decides(s) == DECIDES_ARTIFACT}


def gate_artifact(step):
    """The declared artifact mapping of an artifact-deciding human Gate."""
    return (step.get("gate") or {}).get("artifact")


def _typed(message, strict, rule="present-key-typed"):
    """MESSAGE, naming the profile's RULE when STRICT (a `[0.2]` document,
    0.11.0): a present key of the wrong type is refused there by rule, as
    the profile's other tightenings are. `[0.1]` messages are unchanged."""
    return message[:-1] + f" (rule {rule})." if strict else message


def _gate_problems(step, sid, problems, strict=False):
    """Every problem with one step's `gate:` block. `decides` and
    `artifact` belong to a human Gate (0.7.0): an artifact Gate DECLARES the
    artifact it asks about, as a closed mapping over `kind`, `digests`, and
    the optional `id`, `summary` and `detail`; a changes Gate declares none.
    STRICT is a `[0.2]` document (0.11.0): a `gate:` that is present is an
    object, and `guards`, when present, a list (accepted only empty)."""
    gate = step.get("gate")
    if gate is None and not (strict and "gate" in step):
        return
    if not isinstance(gate, dict):
        problems.append(_typed(f"Op step {sid!r}'s gate must be an object "
                               f"with a policy.", strict))
        return
    for key in sorted(str(k) for k in set(gate) - GATE_KEYS):
        problems.append(f"unknown key {key!r} under Op step "
                        f"{sid!r}'s gate:; the Gate vocabulary is "
                        f"closed.")
    policy = gate.get("policy", GATE_POLICY)
    if policy not in GATE_POLICIES:
        problems.append(f"Op step {sid!r} declares gate.policy "
                        f"{policy!r}; the Gate policies are "
                        f"{list(GATE_POLICIES)}.")
    if strict and "guards" in gate and not isinstance(gate["guards"], list):
        # [0.1] read a falsy `guards` (false, null, {}) as none at all.
        problems.append(f"Op step {sid!r} declares gate.guards "
                        f"{gate['guards']!r}; gate.guards is deprecated and "
                        f"accepted only as an empty list (rule no-guards).")
    elif gate.get("guards"):
        problems.append(f"Op step {sid!r} declares gate.guards, "
                        f"which are not in the runner subset; "
                        f"Guards are system-side verifiers a "
                        f"hosting environment supplies.")
    decides = gate.get("decides", DECIDES_CHANGES)
    if decides not in GATE_DECIDES:
        problems.append(f"Op step {sid!r} declares gate.decides "
                        f"{decides!r}; a human Gate decides about one of "
                        f"{list(GATE_DECIDES)}.")
        return
    if policy != HUMAN_GATE_POLICY:
        for key in ("decides", "artifact"):
            if key in gate:
                problems.append(f"Op step {sid!r} declares gate.{key} with "
                                f"gate.policy {policy!r}; only a human Gate "
                                f"decides about something.")
        return
    artifact = gate.get("artifact")
    if decides == DECIDES_CHANGES:
        if "artifact" in gate:
            problems.append(f"Op step {sid!r} declares gate.artifact but "
                            f"decides about changes; an artifact is what a "
                            f"gate with decides: artifact asks about.")
        return
    if not isinstance(artifact, dict):
        problems.append(f"Op step {sid!r} declares gate.decides: artifact "
                        f"with no gate.artifact object; an artifact Gate "
                        f"declares the artifact it asks about — its kind and "
                        f"the digests that pin it.")
        return
    for key in sorted(str(k) for k in set(artifact) - ARTIFACT_KEYS):
        problems.append(f"unknown key {key!r} under Op step {sid!r}'s "
                        f"gate.artifact; an artifact is "
                        f"{sorted(ARTIFACT_KEYS)}.")
    for key in ARTIFACT_REQUIRED:
        if key not in artifact:
            problems.append(f"Op step {sid!r}'s gate.artifact declares no "
                            f"{key}; an artifact Gate says what kind of "
                            f"thing it asks about and the digests that pin "
                            f"it.")
    digests = artifact.get("digests")
    if "digests" in artifact and (not isinstance(digests, dict)
                                  or not digests
                                  or operator_keys(digests) is not None):
        problems.append(f"Op step {sid!r}'s gate.artifact.digests must be a "
                        f"non-empty object of named digest expressions, one "
                        f"per thing the acceptance is bound to.")


def repeat_spec(step):
    """The normalized `{count, require, mode}` of a step that repeats, or None
    when it runs once (machinery 0.6.0; `mode` since 0.6.4).

    `require` defaults to `count`: a step that states no tolerance requires
    EVERY repeat to pass. Silence never loosens a Gate. `mode` defaults to
    `all`, today's behaviour: an absent `mode` is the step that unions every
    answer. A malformed `repeat` reads as None here — `validate` refuses it by
    name at load, so the runner never sees one.

    The normalized record ALWAYS carries `mode`, so a step that declared none
    is the SAME EXECUTION WITH ONE ADDED FIELD, not a byte-for-byte identical
    artifact: the Track record and the `--dry-run` plan now read
    `{count: 3, require: 1, mode: "all"}` where they read
    `{count: 3, require: 1}`. A golden comparison
    against a pre-0.6.4 Track sees that one key."""
    declared = (step or {}).get("repeat")
    if not isinstance(declared, dict):
        return None
    count = declared.get("count")
    if isinstance(count, bool) or not isinstance(count, int):
        return None
    require = declared.get("require", count)
    if isinstance(require, bool) or not isinstance(require, int):
        require = count
    mode = declared.get("mode", REPEAT_ALL)
    if mode not in REPEAT_MODES:
        mode = REPEAT_ALL
    return {"count": count, "require": require, "mode": mode}


def _repeat_problems(step, sid, problems, strict=False):
    """Every problem with one step's `repeat:` block.

    Repetition is for steps that only READ and only propose: a step that
    carries `authority`, or whose Gate is a human one, is refused here, and a
    step whose COG declares `reaches` is refused by `cog_step_findings`,
    where the manifest is readable. STRICT is a `[0.2]` document (0.11.0):
    `repeat: null` is a malformed declaration, not a step that runs once."""
    declared = step.get("repeat")
    if declared is None and not (strict and "repeat" in step):
        return
    if not isinstance(declared, dict):
        problems.append(_typed(f"Op step {sid!r} declares repeat "
                               f"{declared!r}; a repeat is an object with "
                               f"count and require.", strict))
        return
    for key in sorted(str(k) for k in set(declared) - REPEAT_KEYS):
        problems.append(f"unknown key {key!r} under Op step {sid!r}'s "
                        f"repeat:; the step vocabulary is closed.")
    count = declared.get("count")
    counted = isinstance(count, int) and not isinstance(count, bool)
    if count is None:
        problems.append(f"Op step {sid!r}'s repeat declares no count; a "
                        f"repeated step says how many times it runs.")
    elif not counted:
        problems.append(f"Op step {sid!r} declares repeat.count {count!r}; a "
                        f"repeat count is an integer.")
    elif not 1 <= count <= MAX_REPEAT:
        problems.append(f"Op step {sid!r} declares repeat.count {count!r}; a "
                        f"step repeats between 1 and {MAX_REPEAT} times.")
    # Only OMISSION defaults (`require` reads as `count`). A declared
    # `require` is an integer or it is refused — `require: null` is a
    # malformed declaration, not a way to spell "all of them".
    require = declared.get("require", count)
    required = isinstance(require, int) and not isinstance(require, bool)
    if "require" in declared and not required:
        problems.append(f"Op step {sid!r} declares repeat.require {require!r}; "
                        f"a repeat requirement is an integer.")
    elif counted and required and not 1 <= require <= count:
        problems.append(f"Op step {sid!r} declares repeat.require {require!r} "
                        f"with repeat.count {count!r}; a step requires between "
                        f"1 and count passing repeats.")
    # `mode` says how many of the `count` repeats actually run (0.6.4). Only
    # OMISSION defaults (`all`): a misspelled mode is refused by name rather
    # than read as the default, because the two modes cost differently.
    if "mode" in declared and declared.get("mode") not in REPEAT_MODES:
        problems.append(f"Op step {sid!r} declares repeat.mode "
                        f"{declared.get('mode')!r}; a repeat mode is "
                        f"{' or '.join(repr(m) for m in REPEAT_MODES)}.")
    if step.get("authority") is not None:
        problems.append(f"Op step {sid!r} declares repeat and authority; an "
                        f"effectful step is never repeated.")
    if gate_policy(step) == HUMAN_GATE_POLICY:
        problems.append(f"Op step {sid!r} declares repeat and gate.policy: "
                        f"human; a human decides about ONE set of proposals, "
                        f"so a gated step is never repeated.")


def requirements(step):
    """What a step DECLARES it requires. A step never grants itself
    anything: the runner issues the grant, or the step is denied."""
    authority = step.get("authority")
    if not isinstance(authority, dict):
        return []
    declared = authority.get("requires")
    return list(declared) if isinstance(declared, list) else []


def ttl_minutes(doc):
    """How long a grant this Op issues stays valid, in minutes."""
    authority = doc.get("authority")
    if isinstance(authority, dict) and authority.get("ttl_minutes") is not None:
        return authority["ttl_minutes"]
    return DEFAULT_TTL_MINUTES


#: What a write requirement's `changes` must read, exactly.
#: Only the APPROVED list can produce a grant, so only the approved list may
#: be asked for: any other expression is refused at LOAD, by name, rather
#: than becoming a denial at issuance time.
APPROVED_PATH = "steps.{step}.decision.approved"


def target_key(operation):
    """The key OPERATION names its targets under — `targets`, or
    `repositories` in an existing document — or None when it names neither.
    Stating both is refused wherever a document is validated."""
    for key in TARGET_KEYS:
        if key in (operation or {}):
            return key
    return None


def decision_step(requirement):
    """The step whose human decision a write requirement's `changes` reads,
    or None when the expression is not `{$from: steps.<id>.decision.approved}`.
    """
    changes = (requirement or {}).get("changes")
    if not isinstance(changes, dict) or frozenset(changes) != frozenset({"$from"}):
        return None
    segments = str(changes["$from"]).split(".")
    if (len(segments) == 4 and segments[0] == "steps"
            and segments[2] == "decision" and segments[3] == "approved"):
        return segments[1]
    return None


def _authority_problems(step, sid, step_ids, human_steps, problems,
                        artifact_steps=(), strict=False):
    """Every problem with one step's `authority:` block.

    `artifact_steps` are the human Gates that decide about an ARTIFACT
    (0.7.0): their decision is one verdict, not an approved list, so no
    write grant can be asked for from one. STRICT is a `[0.2]` document
    (0.11.0): `repositories` is refused, and an action is `read` or
    `write`."""
    authority = step.get("authority")
    if authority is None and not (strict and "authority" in step):
        # [0.2] (0.11.0): `authority: null` is present, and refused below.
        return
    if not isinstance(authority, dict):
        problems.append(_typed(f"Op step {sid!r}'s authority must be an "
                               f"object with a requires list.", strict))
        return
    for key in sorted(str(k) for k in set(authority) - STEP_AUTHORITY_KEYS):
        problems.append(f"unknown key {key!r} under Op step {sid!r}'s "
                        f"authority:; the authority vocabulary is closed.")
    if step.get("foreach") is not None:
        # The runner issues one grant per step, not one per element.
        problems.append(f"Op step {sid!r} declares authority on a foreach "
                        f"step; the runner issues no per-element grants.")
    declared = authority.get("requires")
    if not isinstance(declared, list) or not declared:
        problems.append(f"Op step {sid!r} declares authority with no requires "
                        f"list; a step states what it requires, and the "
                        f"runner issues the grant.")
        return
    if step.get("on_fail") == "retry-once":
        # An effectful step recovers by RESUME plus journal
        # reconciliation, never by re-invoking a Cog that may already have
        # acted. Refused at load, not discovered after a double write.
        problems.append(
            f"Op step {sid!r} declares authority and on_fail: retry-once; a "
            f"step that reaches outside the run is never re-invoked on a "
            f"failure — it recovers by resume and journal reconciliation.")
    # Only the string entries: a list or object among them is refused by
    # `validate`, and is not hashable.
    direct = {dep for dep in _deps(step) if isinstance(dep, str)}
    gates = set()
    for index, requirement in enumerate(declared):
        where = f"Op step {sid!r} authority.requires[{index}]"
        if not isinstance(requirement, dict):
            problems.append(f"{where} must be an object with resource and "
                            f"action.")
            continue
        if strict and "repositories" in requirement:
            problems.append(f"{where} declares repositories, the former name "
                            f"of targets; a requirement names what it "
                            f"touches as targets (rule targets-only).")
        known = REQUIREMENT_KEYS_0_2 if strict else REQUIREMENT_KEYS
        for key in sorted(str(k) for k in set(requirement) - known
                          - ({"repositories"} if strict else set())):
            problems.append(f"unknown key {key!r} on {where}; the "
                            f"requirement vocabulary is closed.")
        for field in ("resource", "action"):
            if not isinstance(requirement.get(field), str) or \
                    not requirement[field]:
                problems.append(f"{where} declares {field} "
                                f"{requirement.get(field)!r}; a requirement's "
                                f"{field} is a string.")
        if (strict and isinstance(requirement.get("action"), str)
                and requirement["action"]
                and requirement["action"] not in ACTIONS_0_2):
            problems.append(f"{where} declares action "
                            f"{requirement['action']!r}; an action is read or "
                            f"write, and other effects are not in this Op "
                            f"spec (rule read-or-write).")
            continue
        # Whatever the action: a write's lists are not what the grant is
        # issued from, so a conflict there would otherwise pass unread.
        both = all(key in requirement for key in TARGET_KEYS)
        if both:
            problems.append(f"{where} declares both targets and "
                            f"repositories; repositories is the earlier "
                            f"name for targets, and a requirement states "
                            f"one of them.")
        if requirement.get("action") == "write":
            target = decision_step(requirement)
            if target is None:
                problems.append(
                    f"{where} requires a write whose changes is not "
                    f"{{$from: {APPROVED_PATH.format(step='<id>')}}}; only "
                    f"the approved list of a human-gated step can produce a "
                    f"write grant, so only it may be asked for.")
                continue
            gates.add(target)
            if len(gates) > 1:
                problems.append(
                    f"{where} reads the decision of step {target!r} while "
                    f"another requirement on this step reads "
                    f"{sorted(gates - {target})[0]!r}; the runner issues "
                    f"one grant per step, from ONE human gate.")
            if target not in step_ids:
                problems.append(f"{where} reads the decision of step "
                                f"{target!r}, which the Op spec does not "
                                f"declare.")
                continue
            if target not in human_steps:
                problems.append(f"{where} reads the decision of step "
                                f"{target!r}, which has no human Gate; a "
                                f"write is authorized by a human decision.")
            elif target in artifact_steps:
                problems.append(f"{where} reads the approved list of step "
                                f"{target!r}, whose human Gate decides about "
                                f"an artifact; an artifact decision is one "
                                f"verdict and carries no approved changes, "
                                f"so it authorizes no write.")
            if target not in direct:
                problems.append(f"{where} reads the decision of step "
                                f"{target!r} without depending on it; add it "
                                f"to this step's depends_on.")
        elif "changes" in requirement:
            problems.append(f"{where} declares changes on a "
                            f"{requirement.get('action')!r} requirement; "
                            f"changes belong to a write.")
        elif not both and requirement.get(target_key(requirement)) is None:
            problems.append(f"{where} declares no targets; a read "
                            f"requirement names what it reads.")


def _has_id(step):
    """True when a step is an object with a string id — checked before the id
    is hashed, matched, or used in a message."""
    return isinstance(step, dict) and isinstance(step.get("id"), str) \
        and bool(step["id"])


def _deps(step):
    """A step's declared depends_on, as a list (malformed values are reported
    by `validate`, which runs before any ordering)."""
    declared = step.get("depends_on")
    return list(declared) if isinstance(declared, list) else []


def _order(steps, problems):
    """Topological order, ties broken by spec order. Records a cycle as a
    problem and returns the steps unordered.

    ONE step at a time: the earliest ready step in spec order runs next, so a
    step that becomes ready mid-batch still runs before a later independent
    step ("ties break by spec order")."""
    ids = [s.get("id") for s in steps]
    pending = list(steps)
    done, ordered = set(), []
    while pending:
        index = next((i for i, s in enumerate(pending)
                      if all(d in done for d in _deps(s))), None)
        if index is None:
            stuck = sorted(str(s.get("id")) for s in pending)
            problems.append(f"the Op spec's steps form a dependency cycle "
                            f"among {stuck}; depends_on must be acyclic.")
            return list(steps)
        step = pending.pop(index)
        ordered.append(step)
        done.add(step.get("id"))
    assert len(ordered) == len(ids)
    return ordered


def _transitive(steps):
    direct = {s.get("id"): _deps(s) for s in steps}
    out = {}

    def collect(sid, seen):
        result = set()
        for dep in direct.get(sid) or []:
            if dep in seen:
                continue
            seen.add(dep)
            result.add(dep)
            result |= collect(dep, seen)
        return result

    for sid in direct:
        out[sid] = collect(sid, set())
    return out


def schema_problems(schema, name):
    """Why a declared input `schema:` is not a usable JSON Schema. Checked at
    LOAD, so a bad schema is a named problem rather than a surprise
    jsonschema error at request time."""
    if _SchemaValidator is None:                       # pragma: no cover
        return []
    try:
        _SchemaValidator.check_schema(schema)
    except Exception as exc:                           # jsonschema.SchemaError
        detail = " ".join(str(exc).split())[:160]
        return [f"Op input {name!r} declares a schema that is not valid JSON "
                f"Schema: {detail}."]
    return []


def _strict_problems(doc):
    """The top-level tightenings a `[0.2]` document is held to (machinery
    0.11.0; profile `op-manifest [0.2]`, "Tightenings"): typed identity,
    description, `inputs[].required` and `track.records`."""
    problems = []
    for field in ("id", "version", "title"):
        if field not in doc or doc[field] in ("", None):
            problems.append(f"the Op spec is missing required field "
                            f"{field!r}.")
        elif not isinstance(doc[field], str):
            problems.append(f"the Op spec declares {field} {doc[field]!r}, "
                            f"which is not a string; quote it (rule "
                            f"required-identity).")
    if "description" in doc and not isinstance(doc["description"], str):
        problems.append(f"the Op spec declares description "
                        f"{doc['description']!r}, which is not a string.")
    inputs = doc.get("inputs")
    for declared in inputs if isinstance(inputs, list) else []:
        if not isinstance(declared, dict):
            continue
        name = declared.get("name")
        if "required" in declared and not isinstance(declared["required"],
                                                     bool):
            problems.append(f"Op input {name!r} declares required "
                            f"{declared['required']!r}; required is true or "
                            f"false.")
        if "description" in declared and not isinstance(
                declared["description"], str):
            problems.append(f"Op input {name!r} declares description "
                            f"{declared['description']!r}, which is not a "
                            f"string.")
    track = doc.get("track")
    if isinstance(track, dict) and "records" in track:
        records = track["records"]
        if not isinstance(records, list) or any(not isinstance(r, str)
                                                for r in records):
            problems.append(f"the Op spec declares track.records "
                            f"{records!r}; track.records is a list of "
                            f"strings (and is ignored).")
    return problems


def _artifact_loop_problems(step, sid, loop_vars):
    """Why a `foreach` step's artifact Gate is refused for reading its loop
    variable (`[0.2]`, 0.11.0; rule artifact-not-per-element). Each element
    has its own envelope Gate, but a human artifact Gate is ONE decision over
    the whole step, evaluated after the loop, when no element is current: a
    digest of `item.x` has nothing to read, so the Gate could only fail.
    `[0.1]` keeps loading it — a read with a `$default` evaluates there."""
    return [f"Op step {sid!r} gate.artifact reads {path!r}, the foreach "
            f"variable; a human artifact Gate on a foreach step is one "
            f"decision over the whole step, made after the loop, when no "
            f"element is current. Read the step's payload, the list of "
            f"element payloads, instead (rule artifact-not-per-element)."
            for kind, path in expression_reads(gate_artifact(step))
            if kind == "$from" and path_root(path) in loop_vars]


def _cycle_limit_problems(expr, where):
    """Why a cycle limit is refused for reading something other than an
    input (`[0.2]`, 0.11.0; rule cycle-limits-read-inputs). The limits are
    evaluated once, when the cycle starts and before any run exists, from
    the request's inputs alone: `run.*`, `request.dir`, `$run_dir` and
    `$path` would read a run or a request directory — nested in a `$default`
    as much as at the top. A step or an undeclared root is refused by
    `_expr_problems` already."""
    problems = []
    for kind, value in expression_reads(expr):
        if kind == "$from" and path_root(value) in ("run", "request"):
            problems.append(f"{where} reads {value!r}; a cycle's limits read "
                            f"inputs only, evaluated once when the cycle "
                            f"starts, before any run exists (rule "
                            f"cycle-limits-read-inputs).")
        elif kind in ("$run_dir", "$path"):
            problems.append(f"{where} uses {kind}, which reads a run or "
                            f"request directory; a cycle's limits read "
                            f"inputs only, evaluated once when the cycle "
                            f"starts (rule cycle-limits-read-inputs).")
    return problems


def _strict_step_problems(step, sid):
    """The step tightenings a `[0.2]` document is held to (0.11.0): `title`,
    never `name`; typed `title` and `expected_outcome`; a stated
    `cog.version`."""
    problems = []
    if "name" in step:
        problems.append(f"Op step {sid!r} declares name:; a step's "
                        f"human-readable name is title, as the Op's is (rule "
                        f"step-title).")
    for field in ("title", "expected_outcome"):
        if field in step and not isinstance(step[field], str):
            problems.append(f"Op step {sid!r} declares {field} "
                            f"{step[field]!r}, which is not a string"
                            + (" (rule step-title)." if field == "title"
                               else "."))
    cog = step.get("cog")
    if isinstance(cog, dict) and cog.get("version") in (None, ""):
        problems.append(f"Op step {sid!r} is missing cog.version; a step "
                        f"states the version of the Cog it was written "
                        f"against, and the run checks it (rule "
                        f"cog-version-required).")
    return problems


def validate(doc):
    """Every problem with a spec document, as one-sentence strings.

    The document's `schema` picks the rules: a `[0.2]` document is held to
    the profile's tightenings (`_strict_problems` and the STRICT branches
    below, machinery 0.11.0); a `[0.1]` document is validated exactly as
    0.10.0 validated it."""
    problems = []
    if not isinstance(doc, dict):
        raise OpSpecError("an Op spec is a mapping with schema, id, version, "
                          "and steps.")
    strict = profile_of(doc) == PROFILE_0_2
    top_keys = TOP_KEYS_0_2 if strict else TOP_KEYS
    step_keys = STEP_KEYS_0_2 if strict else STEP_KEYS

    for key, phase in REFUSED_TOP.items():
        if key in doc:
            problems.append(f"the Op spec declares {key}:, which the runner "
                            f"subset does not carry — {phase}.")
    if strict and "name" in doc:
        problems.append("the Op spec declares name:; the Op's human-readable "
                        "name is title (rule required-identity).")
    for key in sorted(str(k) for k in set(doc) - top_keys - set(REFUSED_TOP)
                      - ({"name"} if strict else set())):
        problems.append(f"unknown top-level Op spec key {key!r}; the Op spec "
                        f"vocabulary is closed.")
    if doc.get("schema") not in SCHEMA_STRINGS:
        problems.append(f"the Op spec schema must be one of "
                        f"{list(SCHEMA_STRINGS)}, got {doc.get('schema')!r}.")
    if strict:
        problems.extend(_strict_problems(doc))
    else:
        for field in ("id", "version", "name"):
            if not doc.get(field):
                problems.append(f"the Op spec is missing required field "
                                f"{field!r}.")

    inputs = doc.get("inputs") or []
    if strict and "inputs" in doc:
        # [0.2] (0.11.0): a key that is present has its type. `inputs: {}`,
        # `null` or `""` used to read as no inputs at all (rule
        # present-key-typed); the same holds for every optional key below.
        inputs = doc["inputs"]
    input_names = set()
    if not isinstance(inputs, list):
        problems.append(_typed("the Op spec's inputs must be an ordered list "
                               "of input declarations.", strict))
        inputs = []
    for index, declared in enumerate(inputs):
        if not isinstance(declared, dict) or not isinstance(
                declared.get("name"), str) or not declared["name"]:
            problems.append(f"Op input #{index} must be an object with a "
                            f"name (a string).")
            continue
        for key in sorted(str(k) for k in set(declared) - INPUT_KEYS):
            problems.append(f"unknown key {key!r} on Op input "
                            f"{declared['name']!r}; the input vocabulary is "
                            f"closed.")
        if declared["name"] in input_names:
            problems.append(f"Op input {declared['name']!r} is declared twice.")
        input_names.add(declared["name"])
        if "schema" in declared:
            problems.extend(schema_problems(declared["schema"],
                                            declared["name"]))

    authority = doc.get("authority")
    if authority is not None or (strict and "authority" in doc):
        if not isinstance(authority, dict):
            problems.append(_typed("the Op spec's authority must be an "
                                   "object with ttl_minutes.", strict))
        else:
            for key in sorted(str(k) for k in set(authority)
                              - AUTHORITY_TOP_KEYS):
                problems.append(f"unknown key {key!r} under the Op spec's "
                                f"authority:; the authority vocabulary is "
                                f"closed.")
            ttl = authority.get("ttl_minutes")
            # [0.2]: `ttl_minutes: null` is refused, never the default 60.
            if ((ttl is not None or (strict and "ttl_minutes" in authority))
                    and (isinstance(ttl, bool)
                         or not isinstance(ttl, (int, float)) or ttl <= 0)):
                problems.append(_typed(
                    f"the Op spec declares authority.ttl_minutes {ttl!r}; a "
                    f"grant's life is a positive number of minutes.",
                    strict, "ttl-positive"))

    track = doc.get("track")
    if track is not None or (strict and "track" in doc):
        if not isinstance(track, dict):
            problems.append(_typed("the Op spec's track must be an object "
                                   "with a records list.", strict))
        else:
            for key in sorted(str(k) for k in set(track) - TRACK_KEYS):
                problems.append(f"unknown key {key!r} under track:; the Track "
                                f"vocabulary is closed.")

    steps = doc.get("steps")
    if not isinstance(steps, list) or not steps:
        problems.append("the Op spec must declare a non-empty steps list.")
        raise OpSpecError(problems)

    step_ids = set()
    for index, step in enumerate(steps):
        if not _has_id(step):
            problems.append(f"Op step #{index} must be an object with an id "
                            f"(a string).")
            continue
        sid = step["id"]
        if sid in step_ids:
            problems.append(f"Op step id {sid!r} is declared twice; step ids "
                            f"are unique.")
        step_ids.add(sid)
        if not STEP_ID_RE.match(str(sid)):
            problems.append(f"Op step id {sid!r} must be lowercase "
                            f"alphanumerics and single hyphens.")

    for step in steps:
        if not _has_id(step):
            continue
        sid = step["id"]
        if strict:
            problems.extend(_strict_step_problems(step, sid))
        for key, phase in REFUSED_STEP.items():
            if key not in step:
                continue
            if phase is None:
                problems.append(f"Op step {sid!r} declares a {key}: step; "
                                f"{REFUSED_STEP_REASON[key]}.")
            else:
                problems.append(f"Op step {sid!r} declares a {key}: step, "
                                f"which the runner subset does not carry — "
                                f"{phase}.")
        for key in sorted(str(k) for k in set(step) - step_keys
                          - set(REFUSED_STEP)
                          - ({"name"} if strict else set())):
            problems.append(f"unknown key {key!r} on Op step {sid!r}; the step "
                            f"vocabulary is closed.")
        declared_deps = step.get("depends_on")
        if (declared_deps is not None or (strict and "depends_on" in step)) \
                and not isinstance(declared_deps, list):
            problems.append(_typed(f"Op step {sid!r} declares depends_on "
                                   f"{declared_deps!r}; depends_on is a list "
                                   f"of step ids.", strict))
            declared_deps = []
        for dep in declared_deps or []:
            if not isinstance(dep, str):
                problems.append(f"Op step {sid!r} depends on {dep!r}, which is "
                                f"not a step id.")
                continue
            if dep not in step_ids:
                problems.append(f"Op step {sid!r} depends on {dep!r}, which "
                                f"the Op spec does not declare.")
            if dep == sid:
                problems.append(f"Op step {sid!r} depends on itself.")

        cog = step.get("cog")
        if not isinstance(cog, dict):
            if "tool" not in step and "human" not in step:
                problems.append(f"Op step {sid!r} declares no cog:; a Cog step "
                                f"is the only step kind in the runner subset.")
        else:
            for key in sorted(str(k) for k in set(cog) - COG_KEYS):
                problems.append(f"unknown key {key!r} under Op step {sid!r}'s "
                                f"cog:; the step vocabulary is closed.")
            for field in ("id", "source", "task"):
                if not cog.get(field):
                    problems.append(f"Op step {sid!r} is missing cog.{field}.")
            # A Cog's identity, source and task are STRINGS: a list-valued
            # source is an invalid spec at load, not a path-construction
            # crash when the step is about to run.
            for field in ("id", "version", "source", "task"):
                if field in cog and cog[field] is not None \
                        and not isinstance(cog[field], str):
                    problems.append(f"Op step {sid!r} declares cog.{field} "
                                    f"{cog[field]!r}; cog.{field} is a "
                                    f"string.")

        _gate_problems(step, sid, problems, strict=strict)

        _authority_problems(step, sid, step_ids, human_gate_steps(steps),
                            problems, artifact_gate_steps(steps),
                            strict=strict)
        _repeat_problems(step, sid, problems, strict=strict)

        on_fail = step.get("on_fail", "stop")
        if on_fail not in ON_FAIL:
            problems.append(f"Op step {sid!r} declares on_fail {on_fail!r}; "
                            f"choose one of {list(ON_FAIL)}.")

        foreach = step.get("foreach")
        if (foreach is not None and isinstance(step.get("gate"), dict)
                and gate_policy(step) == HUMAN_GATE_POLICY
                and gate_decides(step) == DECIDES_CHANGES):
            # Machinery 0.10.0. A human Gate over changes reads ONE `changes`
            # list from the step's payload, and a foreach step's payload is
            # the LIST of element payloads: the pause could never be asked.
            # It used to load and fail when the run reached the pause.
            problems.append(f"Op step {sid!r} declares foreach and a human "
                            f"Gate over changes; the Gate reads one changes "
                            f"list from the step's payload, but a foreach "
                            f"step's payload is the list of its element "
                            f"payloads. Gate a later step that gathers the "
                            f"proposals instead.")
        if foreach is not None or (strict and "foreach" in step):
            if not isinstance(foreach, dict):
                problems.append(_typed(f"Op step {sid!r}'s foreach must be "
                                       f"an object with items and as.",
                                       strict))
            else:
                for key in sorted(str(k) for k in set(foreach) - FOREACH_KEYS):
                    problems.append(f"unknown key {key!r} under Op step "
                                    f"{sid!r}'s foreach:; the step vocabulary "
                                    f"is closed.")
                if "items" not in foreach:
                    problems.append(f"Op step {sid!r}'s foreach declares no "
                                    f"items expression.")
                loop_var = foreach.get("as")
                if not loop_var:
                    problems.append(f"Op step {sid!r}'s foreach declares no "
                                    f"loop variable (as:).")
                elif not (isinstance(loop_var, str)
                          and LOOP_VAR_RE.match(loop_var)):
                    # Checked before it is ever hashed or used as a context
                    # key: a list-valued `as` used to raise a bare TypeError.
                    problems.append(f"Op step {sid!r} declares foreach.as "
                                    f"{loop_var!r}; a loop variable is a name "
                                    f"(letters, digits and underscores, not "
                                    f"starting with a digit).")
                elif loop_var in PATH_ROOTS:
                    # A loop variable becomes a context key for the element.
                    # `as: run` would replace the run context and redirect
                    # every `$run_dir` in the step to the element's own
                    # `dir` — containment is enforced at LOAD, by refusing
                    # the collision, not at write time.
                    problems.append(f"Op step {sid!r} declares foreach.as "
                                    f"{loop_var!r}; {list(PATH_ROOTS)} name "
                                    f"the run context and cannot be loop "
                                    f"variables.")

    if problems:
        raise OpSpecError(problems)

    ordered = _order(steps, problems)
    if problems:
        raise OpSpecError(problems)
    deps = _transitive(steps)
    human_steps = human_gate_steps(steps)
    artifact_steps = artifact_gate_steps(steps)

    for step in steps:
        sid = step["id"]
        dep_ids = deps.get(sid, set())
        loop_vars = {(step.get("foreach") or {}).get("as")} - {None}
        if step.get("foreach") is not None:
            _expr_problems((step["foreach"] or {}).get("items"),
                           f"Op step {sid!r} foreach.items", input_names,
                           step_ids, dep_ids, set(), problems, human_steps,
                           strict)
        _expr_problems(step.get("input") or {}, f"Op step {sid!r} input",
                       input_names, step_ids, dep_ids, loop_vars, problems,
                       human_steps, strict)
        if sid in artifact_steps and isinstance(gate_artifact(step), dict):
            # The artifact is evaluated AFTER the step's own Cog answered, so
            # it may read this step's payload and envelope as well as its
            # dependencies' — but never its own decision, which does not
            # exist until the person has given it (0.7.0).
            _expr_problems(gate_artifact(step),
                           f"Op step {sid!r} gate.artifact", input_names,
                           step_ids, dep_ids | {sid}, loop_vars, problems,
                           human_steps - {sid}, strict)
            if strict and loop_vars:
                problems.extend(_artifact_loop_problems(step, sid, loop_vars))
        for index, requirement in enumerate(requirements(step)):
            if not isinstance(requirement, dict):
                continue
            for field in (*TARGET_KEYS, "changes"):
                if field in requirement:
                    _expr_problems(
                        requirement[field],
                        f"Op step {sid!r} authority.requires[{index}].{field}",
                        input_names, step_ids, dep_ids, loop_vars, problems,
                        human_steps, strict)

    outputs = doc.get("outputs") or {}
    if strict and "outputs" in doc:
        outputs = doc["outputs"]        # [0.2]: `outputs: []` is refused
    if not isinstance(outputs, dict):
        problems.append(_typed("the Op spec's outputs must be an object of "
                               "mapping expressions.", strict))
    else:
        _expr_problems(outputs, "the Op spec's outputs", input_names, step_ids,
                       step_ids, set(), problems, human_steps, strict)

    if not problems and 'cycle' in doc:
        try:
            cycle_phases(doc)
        except (OpSpecError, KeyError, TypeError, ValueError) as exc:
            problems.extend(exc.problems if isinstance(exc, OpSpecError) else [str(exc)])
    if problems:
        raise OpSpecError(problems)
    return ordered


def cycle_phases(doc):
    """Validate declarative bounded transitions and every expanded phase spec."""
    cycle = doc.get('cycle')
    required = {'outcome_step', 'outcome_field', 'max_attempts', 'max_cost_units', 'costs', 'transitions'}
    if not isinstance(cycle, dict) or not required <= set(cycle) or set(cycle) - required - {'terminal_errors'}:
        raise OpSpecError('cycle must declare required fields (and optional terminal_errors): ' + ', '.join(sorted(required)))
    base = copy.deepcopy(doc); base.pop('cycle')
    ordered = validate(base)
    base['steps'] = ordered
    ids = [step['id'] for step in ordered]
    if cycle['outcome_step'] not in ids or not isinstance(cycle['outcome_field'], str) or not cycle['outcome_field']:
        raise OpSpecError('cycle must name a declared outcome step and payload field.')
    # [0.2] (0.11.0): ANY top-level authority beside a cycle, `{}` included.
    declares_authority = ('authority' in base if profile_of(doc) == PROFILE_0_2
                          else base.get('authority'))
    if any(requirements(step) for step in ordered) or declares_authority:
        raise OpSpecError('The bounded cycle profile supports pure steps without authority only.')
    if any(value['name'] == 'cycle_previous' for value in base.get('inputs', [])):
        raise OpSpecError('cycle_previous is reserved for durable phase input.')
    transitions = cycle['transitions']
    if not isinstance(transitions, dict) or not transitions:
        raise OpSpecError('cycle needs explicit outcome transitions.')
    phases = {'initial': base}
    all_ids = set(ids)
    for outcome, transition in transitions.items():
        if not isinstance(outcome, str) or not outcome or outcome == 'initial' or not isinstance(transition, dict) or set(transition) - {'restart', 'prepare', 'replace'} or 'restart' not in transition:
            raise OpSpecError('Each cycle outcome needs restart and optional prepare/replace declarations.')
        if transition['restart'] not in ids:
            raise OpSpecError('cycle restart must name a declared step.')
        if ids.index(transition['restart']) > ids.index(cycle['outcome_step']):
            raise OpSpecError('cycle restart must precede its outcome step.')
        phase = copy.deepcopy(base)
        prefix = ids[:ids.index(transition['restart'])]
        preparation = transition.get('prepare', [])
        replacements = transition.get('replace', {})
        if not isinstance(preparation, list) or not isinstance(replacements, dict) or not set(replacements) <= set(ids) - set(prefix):
            raise OpSpecError('cycle preparation is a step list; replacements may change only restarted steps.')
        phase['inputs'] = list(phase.get('inputs') or []) + [{'name': 'cycle_previous', 'required': True, 'schema': {'type': 'object'}}]
        for step in phase['steps']:
            if step['id'] in replacements:
                replacement = replacements[step['id']]
                if not isinstance(replacement, dict) or set(replacement) - {'input', 'depends_on'}:
                    raise OpSpecError('cycle replacements change input mappings/dependencies only.')
                step.update(copy.deepcopy(replacement))
        phase['steps'] = phase['steps'][:len(prefix)] + copy.deepcopy(preparation) + phase['steps'][len(prefix):]
        validate(phase)
        if any(requirements(step) for step in phase['steps']):
            raise OpSpecError('cycle preparation cannot require authority.')
        all_ids.update(step['id'] for step in phase['steps'])
        phases[outcome] = phase
    costs = cycle['costs']
    if not isinstance(costs, dict) or set(costs) != all_ids or any(type(value) is not int or value < 0 for value in costs.values()):
        raise OpSpecError('cycle costs must declare nonnegative integer reservation units for every phase step.')
    terminal_errors = cycle.get('terminal_errors', {})
    if not isinstance(terminal_errors, dict) or not set(terminal_errors) <= all_ids or any(not isinstance(codes, list) or not codes or any(not isinstance(code, str) or not code for code in codes) or len(set(codes)) != len(codes) for codes in terminal_errors.values()):
        raise OpSpecError('cycle terminal_errors maps declared steps to distinct nonempty envelope error codes.')
    for key in ('max_attempts', 'max_cost_units'):
        problems = []
        _expr_problems(cycle[key], 'cycle.' + key, {value['name'] for value in base.get('inputs', [])}, set(), set(), set(), problems, set(), profile_of(doc) == PROFILE_0_2)
        if profile_of(doc) == PROFILE_0_2:
            problems.extend(_cycle_limit_problems(cycle[key], 'cycle.' + key))
        if problems:
            raise OpSpecError(problems)
    return phases


class OpSpec:
    """A validated Op spec and the order its steps run in."""

    def __init__(self, doc, path=None):
        self.doc = doc
        self.path = Path(path).resolve() if path else None
        self.ordered = validate(doc)
        self.schema = doc["schema"]
        #: `0.1` or `0.2`: which profile's run-time rules apply (0.11.0).
        self.profile = profile_of(doc)
        self.id = doc["id"]
        self.version = str(doc.get("version", ""))
        #: The human-readable name: `title` in `[0.2]`, `name` in `[0.1]`.
        #: `name` stays as the same value for callers written before 0.11.0.
        self.title = doc.get("title" if self.profile == PROFILE_0_2
                             else "name")
        self.name = self.title
        self.description = doc.get("description")
        self.inputs = doc.get("inputs") or []
        self.steps = doc["steps"]
        self.outputs = doc.get("outputs") or {}
        self.track = doc.get("track") or {}
        self.authority = doc.get("authority") or {}
        self.ttl_minutes = ttl_minutes(doc)

    @property
    def change_target_key(self):
        """The field a proposed change names its target under."""
        return change_target_key(self.profile)

    def step(self, sid):
        for step in self.steps:
            if step["id"] == sid:
                return step
        raise OpSpecError(f"the Op spec declares no step {sid!r}.")

    def dependents(self):
        """step id -> the ids that transitively depend on it."""
        deps = _transitive(self.steps)
        out = {s["id"]: set() for s in self.steps}
        for sid, upstream in deps.items():
            for up in upstream:
                out.setdefault(up, set()).add(sid)
        return out

    def sha256(self):
        if not self.path or not self.path.exists():
            return None
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def build_inputs(self, request):
        """Declared input values for a request document: required present,
        defaults applied, declared schemas validated, unknown keys refused.

        ABSENCE is not a value. An optional input the request omits and whose
        declaration carries no `default` key is simply not in the built
        inputs: a `$from` on it takes its `$default` or is the named "not
        available in this run" error. Only SUPPLIED values and DECLARED
        defaults (including `default: null`) are schema-validated — a
        declaration may say `type: string` without forcing every request to
        carry the input."""
        if not isinstance(request, dict):
            raise OpSpecError("an Op request is a JSON object of declared "
                              "inputs.")
        declared = {i["name"]: i for i in self.inputs}
        problems, values = [], {}
        for key in sorted(str(k) for k in set(request) - set(declared)):
            problems.append(f"the Op request carries undeclared input "
                            f"{key!r}; declare it in op.yaml or remove it.")
        for name, spec in declared.items():
            # Presence, not truthiness: an explicit null is a supplied value,
            # a declared `default: null` satisfies an omitted input, and a
            # default never replaces a value the request actually carries.
            if name in request:
                values[name] = request[name]
            elif "default" in spec:
                values[name] = spec["default"]
            elif spec.get("required", True):
                problems.append(f"the Op request is missing required input "
                                f"{name!r}.")
                continue
            else:
                continue         # absent, not null: nothing to validate
            if "schema" in spec and _SchemaValidator is not None:
                try:
                    validator = _SchemaValidator(spec["schema"])
                    errors = list(validator.iter_errors(values[name]))[:3]
                except Exception as exc:               # jsonschema complaints
                    detail = " ".join(str(exc).split())[:160]
                    problems.append(f"Op input {name!r} declares a schema this "
                                    f"runner cannot apply: {detail}.")
                    continue
                for error in errors:
                    where = ".".join(str(x) for x in error.absolute_path) or "$"
                    problems.append(f"Op input {name!r} violates its declared "
                                    f"schema at {where}: {error.message}.")
        if problems:
            raise OpSpecError(problems)
        return values


def load_document(path):
    """The spec document from JSON or YAML, unvalidated."""
    path = Path(path)
    text = path.read_text()
    try:
        if path.suffix == ".json":
            return json.loads(text)
        return yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise OpSpecError(f"{path.name} is not readable as "
                          f"{'JSON' if path.suffix == '.json' else 'YAML'}: "
                          f"{exc}") from exc


def load(path):
    """Load and validate an Op spec file."""
    return OpSpec(load_document(path), path=path)


# ------------------------------------------------- the Cogs a step names --
#
# Shared by the runner (which checks EVERY step before invoking any of them)
# and by `smith op check`. It lives here, in the vendored machinery, so an Op
# package validates its own declarations without cog-smith installed: a Cog's
# profile manifest is read straight from `pixi.toml [tool.cog]` or `cog.yaml`.

def read_cog_manifest(source):
    """(manifest, problem) for the Cog package at SOURCE. Exactly one profile
    manifest is expected: `[tool.cog]` in pixi.toml, or cog.yaml."""
    source = Path(source)
    pixi, standalone = source / "pixi.toml", source / "cog.yaml"
    doc = None
    if pixi.exists():
        try:
            import tomllib
            with open(pixi, "rb") as handle:
                doc = tomllib.load(handle)
        except Exception as exc:
            return None, f"pixi.toml is not readable ({exc})"
    in_pixi = bool(doc and isinstance(doc.get("tool"), dict)
                   and isinstance(doc["tool"].get("cog"), dict))
    if in_pixi and standalone.exists():
        return None, ("both pixi.toml [tool.cog] and cog.yaml are present — a "
                      "package carries exactly one profile manifest")
    if in_pixi:
        manifest = dict(doc["tool"]["cog"])
        workspace = doc.get("workspace") or doc.get("project") or {}
        for key, source_key in (("version", "version"),
                                ("summary", "description")):
            if key not in manifest and workspace.get(source_key) is not None:
                manifest[key] = workspace[source_key]
        return manifest, None
    if standalone.exists():
        try:
            manifest = yaml.safe_load(standalone.read_text())
        except yaml.YAMLError as exc:
            return None, f"cog.yaml is not readable ({exc})"
        if not isinstance(manifest, dict):
            return None, "cog.yaml is not a manifest mapping"
        return manifest, None
    return None, ("it carries no profile manifest: neither pixi.toml with a "
                  "[tool.cog] table nor cog.yaml")


def _authority_findings(step, sid, cog, manifest):
    """[(level, detail)] for a step's authority against the Cog it names —
    the checks that need the Cog's MANIFEST: authority is for code Cogs, a
    requirement must be covered by the Cog's declared `reaches`, and a step
    that invokes a reaching Cog must declare what it requires.

    A DECLARATION check. Nothing here enforces anything at run time: the
    code Cog checks its own grant before every external call."""
    findings = []
    declared = requirements(step)
    reaches = manifest.get("reaches") or []
    if reaches and step.get("on_fail") == "retry-once":
        # The same rule as the authority check in `_authority_problems`, from
        # the other side: the Cog's OWN declaration says it reaches outside
        # the run, so re-invoking it after a failure could repeat an effect.
        findings.append(("error", f"Op step {sid!r} names "
                                  f"{manifest.get('id')!r}, which reaches "
                                  f"outside the run, and declares on_fail: "
                                  f"retry-once; a reaching Cog is never "
                                  f"re-invoked on a failure — it recovers by "
                                  f"resume and journal reconciliation."))
    if declared and manifest.get("kind") != "code":
        findings.append(("error", f"Op step {sid!r} declares authority on "
                                  f"{manifest.get('id')!r}, which is kind "
                                  f"{manifest.get('kind')!r} — the runner "
                                  f"supports authority on code Cogs only."))
        return findings
    covered = {(entry.get("resource"), action)
               for entry in reaches if isinstance(entry, dict)
               for action in entry.get("actions") or []}
    for requirement in declared:
        if not isinstance(requirement, dict):
            continue
        pair = (requirement.get("resource"), requirement.get("action"))
        if pair not in covered:
            findings.append(("error", f"Op step {sid!r} requires "
                                      f"{pair[0]} {pair[1]}, which "
                                      f"{manifest.get('id')!r} does not "
                                      f"declare in its reaches."))
    if not declared and reaches:
        resources = sorted({str(e.get("resource")) for e in reaches
                            if isinstance(e, dict)})
        findings.append(("error", f"Op step {sid!r} names "
                                  f"{manifest.get('id')!r}, which reaches "
                                  f"{resources} outside the run, and declares "
                                  f"no authority.requires — a reaching Cog "
                                  f"runs only under a grant."))
    return findings


def cog_step_findings(step, source_dir, profile=PROFILE_0_1):
    """[(level, detail)] for one Cog step's declaration, checked against the
    Cog at SOURCE_DIR: it must be that Cog, and the task must be one of its
    declared USAGE interfaces. A source that is simply absent is a warning —
    the declaration could not be verified on this machine (a RUN of a `[0.2]`
    document refuses it: `declaration_problems`).

    PROFILE `0.2` (0.11.0): a stated `cog.version` other than the Cog's is an
    error, where `[0.1]` warns."""
    cog = step.get("cog") or {}
    sid = step.get("id")
    source = Path(source_dir)
    if not source.is_dir():
        return [("warn", f"Op step {sid!r} names cog source "
                         f"{cog.get('source')!r}, which is not present here — "
                         f"the task declaration could not be verified on this "
                         f"machine.")]
    manifest, problem = read_cog_manifest(source)
    if manifest is None:
        return [("error", f"Op step {sid!r} names {cog.get('source')!r}, whose "
                          f"manifest is unreadable: {problem}.")]
    findings = []
    if cog.get("id") and manifest.get("id") != cog["id"]:
        findings.append(("error", f"Op step {sid!r} declares cog id "
                                  f"{cog['id']!r} but {cog.get('source')!r} "
                                  f"identifies as {manifest.get('id')!r}."))
    if cog.get("version") and manifest.get("version") != cog["version"]:
        strict = profile == PROFILE_0_2
        findings.append(("error" if strict else "warn",
                         f"Op step {sid!r} declares version "
                         f"{cog['version']!r} but {cog.get('source')!r} is at "
                         f"{manifest.get('version')!r}"
                         + ("; a step names the Cog version it runs."
                            if strict else ".")))
    findings.extend(_authority_findings(step, sid, cog, manifest))
    if step.get("repeat") is not None and (manifest.get("reaches") or []):
        # The same rule as the `authority` refusal in `_repeat_problems`,
        # from the other side: the Cog's OWN declaration says it reaches
        # outside the run, so running it k times could repeat an effect.
        findings.append(("error", f"Op step {sid!r} names "
                                  f"{manifest.get('id')!r}, which reaches "
                                  f"outside the run, and declares repeat; an "
                                  f"effectful step is never repeated."))
    interfaces = [i for i in manifest.get("interfaces") or []
                  if isinstance(i, dict) and i.get("task") == cog.get("task")]
    if not interfaces:
        findings.append(("error", f"Op step {sid!r} names task "
                                  f"{cog.get('task')!r}, which "
                                  f"{manifest.get('id')!r} does not declare as "
                                  f"an interface."))
        return findings
    audiences = {i.get("audience")
                 or ("lifecycle" if i.get("task") in LIFECYCLE_TASKS
                     else "usage")
                 for i in interfaces}
    if "usage" not in audiences:
        findings.append(("error", f"Op step {sid!r} names task "
                                  f"{cog.get('task')!r}, which "
                                  f"{manifest.get('id')!r} declares for the "
                                  f"{sorted(audiences)[0]} audience — Op steps "
                                  f"use a Cog's usage interfaces."))
    return findings


def cog_source_dir(package_root, step):
    """The resolved directory STEP's `cog.source` names (0.11.0).

    Every run-time reader of a source — the run start's and a resume's
    declaration check, the step loop, a resume's changed-Cog record, a
    cycle's preflight and phases — goes through this, so a source no
    filesystem can name (an embedded NUL, or a link loop, which Python
    3.12's resolve raises as RuntimeError) is an OpSpecError naming the
    step: a refusal with its reason, or a failed step once the run has
    started, never an exception past the runner's handlers."""
    source = (step.get("cog") or {}).get("source")
    try:
        return (Path(package_root) / str(source)).resolve()
    except (ValueError, OSError, RuntimeError) as exc:
        raise OpSpecError(
            f"Op step {step.get('id')!r} names cog source {source!r}, which "
            f"is not a path this machine can name ({type(exc).__name__}: "
            f"{exc}).") from exc


def declaration_problems(spec, package_root):
    """Every ERROR a step's Cog declaration carries, across the whole spec —
    what the runner refuses before it invokes anything.

    For a `[0.2]` document (0.11.0) a named Cog that is not present when the
    run starts is an error too, and so is a stated version that differs from
    the Cog's."""
    problems = []
    profile = getattr(spec, "profile", PROFILE_0_1)
    for step in spec.ordered:
        try:
            source = cog_source_dir(package_root, step)
        except OpSpecError as exc:
            problems.extend(exc.problems)
            continue
        if profile == PROFILE_0_2 and not source.is_dir():
            problems.append(f"Op step {step.get('id')!r} names cog source "
                            f"{(step.get('cog') or {}).get('source')!r}, "
                            f"which is not present; every Cog a run names "
                            f"is present when it starts.")
            continue
        problems.extend(detail for level, detail
                        in cog_step_findings(step, source, profile)
                        if level == "error")
    return problems
