"""Op spec: load, validate, refuse by name, and evaluate mapping expressions.

Machinery master (cog-smith `templates/op/src/`). An Op package never edits
this file — `smith op check` enforces it by hash, exactly as `smith check`
enforces Cog machinery. If an Op needs behaviour this module does not have,
the answer is a Cog step, never a script in the Op.

The spec is `openteams/op-manifest [0.1]`: identity, declared `inputs`, a
list of Cog `steps` with mapping expressions for their requests, optional
`outputs`, and the `track` records. The vocabulary is CLOSED — anything the
runner subset does not carry is refused BY NAME at load, with the phase that
adds it, so an author never discovers a missing construct mid-run.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import yaml

try:                                                   # pragma: no cover
    import jsonschema
    _SchemaValidator = (getattr(jsonschema, "Draft202012Validator", None)
                        or getattr(jsonschema, "Draft7Validator", None))
except ImportError:                                    # pragma: no cover
    _SchemaValidator = None

SCHEMA_STRING = "openteams/op-manifest [0.1]"
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
            "steps", "outputs", "track", "authority"}
STEP_KEYS = {"id", "name", "depends_on", "cog", "foreach", "input",
             "expected_outcome", "gate", "on_fail", "authority", "repeat"}
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
REQUIREMENT_KEYS = {"resource", "action", "repositories", "changes"}
DEFAULT_TTL_MINUTES = 60

# Refused by name, with the phase that adds the construct. A value of None
# means the construct is never added: there is no tool: step kind —
# deterministic work is a Cog of kind: code, invoked as a cog: step — and no
# human: step kind either: a human Gate is `gate: {policy: human}` on a step.
REFUSED_TOP = {"state": "phase 4"}
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
#: very documents that authorize it.
RESERVED_RUN_SUBPATHS = ("grants", "pending", "decisions", "journal",
                         "run.lock", "track.json")

# A Cog's conventional lifecycle tasks, for steps whose interface declares no
# audience. Kept here (not imported from cog-smith) because this module is
# vendored into every Op package and must run without cog-smith installed.
LIFECYCLE_TASKS = {"resolve", "use", "check", "eval", "test", "bundle", "serve"}


class OpSpecError(Exception):
    """One or more one-sentence problems with a spec, request, or mapping."""

    def __init__(self, problems):
        self.problems = [problems] if isinstance(problems, str) else list(problems)
        super().__init__("\n".join(self.problems))


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


def reserved_run_subpath(subpath):
    """The control entry SUBPATH names or lives under, or None. The subpath
    is NORMALISED first, so no spelling of a reserved name gets through."""
    normalized = normalized_subpath(subpath)
    parts = [p for p in Path(normalized).parts if p not in (".", "/")]
    if parts and parts[0] in RESERVED_RUN_SUBPATHS:
        return parts[0]
    return None


def run_dir_path(subpath, run_dir):
    """`<run dir>/<subpath>`, created — refusing anything that would land
    outside the run, or on one of the runner's own control entries.
    `$run_dir` makes a directory INSIDE this run, so an absolute operand, a
    `..` escape, and a symlink out of the run are all refused BEFORE
    anything is created."""
    if subpath is None:
        subpath = ""
    if not isinstance(subpath, str):
        raise OpSpecError(f"$run_dir takes a relative subpath string, got "
                          f"{subpath!r}.")
    reserved = reserved_run_subpath(subpath)
    if reserved:
        raise OpSpecError(f"$run_dir subpath {subpath!r} names the run's "
                          f"{reserved!r}, which the runner owns; "
                          f"{list(RESERVED_RUN_SUBPATHS)} are reserved.")
    candidate = Path(normalized_subpath(subpath))
    base = Path(run_dir).resolve()
    if Path(subpath).is_absolute():
        raise OpSpecError(f"$run_dir subpath {subpath!r} is absolute; "
                          f"$run_dir names a directory inside this run.")
    target = (base / candidate).resolve()
    if target != base and base not in target.parents:
        raise OpSpecError(f"$run_dir subpath {subpath!r} resolves outside the "
                          f"run directory; $run_dir names a directory inside "
                          f"this run.")
    # No component may be a link, even one pointing back inside the run: an
    # alias is how a step would be handed the runner's own control entries
    # under another name.
    current = base
    for part in candidate.parts:
        current = current / part
        if current.is_symlink():
            raise OpSpecError(
                f"$run_dir subpath {subpath!r} passes through {part!r}, "
                f"which is a symlink; $run_dir names a real directory "
                f"inside this run.")
    target.mkdir(parents=True, exist_ok=True)
    return str(target)


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
                path = Path(str(value)).expanduser()
                if not path.is_absolute():
                    path = Path(ctx["request"]["dir"]) / path
                return str(path.resolve())
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


# ------------------------------------------------------------ validation --

def _expr_problems(expr, where, input_names, step_ids, dep_ids, loop_vars,
                   problems, human_steps=()):
    if isinstance(expr, dict):
        keys = frozenset(expr)
        if keys in OPERATORS:
            if "$literal" in keys:
                return
            if "$from" in keys:
                _path_problems(expr["$from"], where, input_names, step_ids,
                               dep_ids, loop_vars, problems, human_steps)
                if "$default" in keys:
                    _expr_problems(expr["$default"], where, input_names,
                                   step_ids, dep_ids, loop_vars, problems,
                                   human_steps)
                return
            if "$run_dir" in keys and isinstance(expr["$run_dir"], str):
                subpath = expr["$run_dir"]
                if (Path(subpath).is_absolute()
                        or ".." in Path(subpath).parts):
                    problems.append(
                        f"{where} asks $run_dir for {subpath!r}; $run_dir "
                        f"names a directory inside this run, so the subpath "
                        f"is relative and never leaves the run directory.")
                    return
                reserved = reserved_run_subpath(subpath)
                if reserved:
                    problems.append(
                        f"{where} asks $run_dir for {subpath!r}, which names "
                        f"the run's {reserved!r}; "
                        f"{list(RESERVED_RUN_SUBPATHS)} are the runner's own "
                        f"control entries and no step writes into them.")
                    return
            for key in ("$path", "$run_dir", "$stem", "$sha256"):
                if key in keys:
                    _expr_problems(expr[key], where, input_names, step_ids,
                                   dep_ids, loop_vars, problems, human_steps)
            return
        unknown = unknown_dollar_keys(expr)
        if unknown:
            problems.append(
                f"{where} uses unknown mapping operator(s) {unknown}; the "
                f"mapping vocabulary is closed ({OPERATOR_NAMES}).")
            return
        for key, value in expr.items():
            if not isinstance(key, str):
                problems.append(f"{where} has key {key!r}, which is not a "
                                f"string; a request document's keys are "
                                f"strings.")
                continue
            _expr_problems(value, f"{where}.{key}", input_names, step_ids,
                           dep_ids, loop_vars, problems, human_steps)
    elif isinstance(expr, list):
        for index, item in enumerate(expr):
            _expr_problems(item, f"{where}[{index}]", input_names, step_ids,
                           dep_ids, loop_vars, problems, human_steps)


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


def _gate_problems(step, sid, problems):
    """Every problem with one step's `gate:` block. `decides` and
    `artifact` belong to a human Gate (0.7.0): an artifact Gate DECLARES the
    artifact it asks about, as a closed mapping over `kind`, `digests`, and
    the optional `id`, `summary` and `detail`; a changes Gate declares none."""
    gate = step.get("gate")
    if gate is None:
        return
    if not isinstance(gate, dict):
        problems.append(f"Op step {sid!r}'s gate must be an object "
                        f"with a policy.")
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
    if gate.get("guards"):
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


def _repeat_problems(step, sid, problems):
    """Every problem with one step's `repeat:` block.

    Repetition is for steps that only READ and only propose: a step that
    carries `authority`, or whose Gate is a human one, is refused here, and a
    step whose COG declares `reaches` is refused by `cog_step_findings`,
    where the manifest is readable."""
    declared = step.get("repeat")
    if declared is None:
        return
    if not isinstance(declared, dict):
        problems.append(f"Op step {sid!r} declares repeat {declared!r}; a "
                        f"repeat is an object with count and require.")
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
                        artifact_steps=()):
    """Every problem with one step's `authority:` block.

    `artifact_steps` are the human Gates that decide about an ARTIFACT
    (0.7.0): their decision is one verdict, not an approved list, so no
    write grant can be asked for from one."""
    authority = step.get("authority")
    if authority is None:
        return
    if not isinstance(authority, dict):
        problems.append(f"Op step {sid!r}'s authority must be an object with "
                        f"a requires list.")
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
    direct = set(_deps(step))
    gates = set()
    for index, requirement in enumerate(declared):
        where = f"Op step {sid!r} authority.requires[{index}]"
        if not isinstance(requirement, dict):
            problems.append(f"{where} must be an object with resource and "
                            f"action.")
            continue
        for key in sorted(str(k) for k in set(requirement) - REQUIREMENT_KEYS):
            problems.append(f"unknown key {key!r} on {where}; the "
                            f"requirement vocabulary is closed.")
        for field in ("resource", "action"):
            if not isinstance(requirement.get(field), str) or \
                    not requirement[field]:
                problems.append(f"{where} declares {field} "
                                f"{requirement.get(field)!r}; a requirement's "
                                f"{field} is a string.")
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
        elif requirement.get("repositories") is None:
            problems.append(f"{where} declares no repositories; a read "
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


def validate(doc):
    """Every problem with a spec document, as one-sentence strings."""
    problems = []
    if not isinstance(doc, dict):
        raise OpSpecError("an Op spec is a mapping with schema, id, version, "
                          "and steps.")

    for key, phase in REFUSED_TOP.items():
        if key in doc:
            problems.append(f"the Op spec declares {key}:, which the runner "
                            f"subset does not carry — {phase} adds it.")
    for key in sorted(str(k) for k in set(doc) - TOP_KEYS - set(REFUSED_TOP)):
        problems.append(f"unknown top-level Op spec key {key!r}; the Op spec "
                        f"vocabulary is closed.")
    if doc.get("schema") != SCHEMA_STRING:
        problems.append(f"the Op spec schema must be {SCHEMA_STRING!r}, got "
                        f"{doc.get('schema')!r}.")
    for field in ("id", "version", "name"):
        if not doc.get(field):
            problems.append(f"the Op spec is missing required field {field!r}.")

    inputs = doc.get("inputs") or []
    input_names = set()
    if not isinstance(inputs, list):
        problems.append("the Op spec's inputs must be an ordered list of "
                        "input declarations.")
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
    if authority is not None:
        if not isinstance(authority, dict):
            problems.append("the Op spec's authority must be an object with "
                            "ttl_minutes.")
        else:
            for key in sorted(str(k) for k in set(authority)
                              - AUTHORITY_TOP_KEYS):
                problems.append(f"unknown key {key!r} under the Op spec's "
                                f"authority:; the authority vocabulary is "
                                f"closed.")
            ttl = authority.get("ttl_minutes")
            if ttl is not None and (isinstance(ttl, bool)
                                    or not isinstance(ttl, (int, float))
                                    or ttl <= 0):
                problems.append(f"the Op spec declares authority.ttl_minutes "
                                f"{ttl!r}; a grant's life is a positive "
                                f"number of minutes.")

    track = doc.get("track")
    if track is not None:
        if not isinstance(track, dict):
            problems.append("the Op spec's track must be an object with a "
                            "records list.")
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
        for key, phase in REFUSED_STEP.items():
            if key not in step:
                continue
            if phase is None:
                problems.append(f"Op step {sid!r} declares a {key}: step; "
                                f"{REFUSED_STEP_REASON[key]}.")
            else:
                problems.append(f"Op step {sid!r} declares a {key}: step, "
                                f"which the runner subset does not carry — "
                                f"{phase} adds it.")
        for key in sorted(str(k) for k in set(step) - STEP_KEYS
                          - set(REFUSED_STEP)):
            problems.append(f"unknown key {key!r} on Op step {sid!r}; the step "
                            f"vocabulary is closed.")
        declared_deps = step.get("depends_on")
        if declared_deps is not None and not isinstance(declared_deps, list):
            problems.append(f"Op step {sid!r} declares depends_on "
                            f"{declared_deps!r}; depends_on is a list of step "
                            f"ids.")
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

        _gate_problems(step, sid, problems)

        _authority_problems(step, sid, step_ids, human_gate_steps(steps),
                            problems, artifact_gate_steps(steps))
        _repeat_problems(step, sid, problems)

        on_fail = step.get("on_fail", "stop")
        if on_fail not in ON_FAIL:
            problems.append(f"Op step {sid!r} declares on_fail {on_fail!r}; "
                            f"choose one of {list(ON_FAIL)}.")

        foreach = step.get("foreach")
        if foreach is not None:
            if not isinstance(foreach, dict):
                problems.append(f"Op step {sid!r}'s foreach must be an object "
                                f"with items and as.")
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
                           step_ids, dep_ids, set(), problems, human_steps)
        _expr_problems(step.get("input") or {}, f"Op step {sid!r} input",
                       input_names, step_ids, dep_ids, loop_vars, problems,
                       human_steps)
        if sid in artifact_steps and isinstance(gate_artifact(step), dict):
            # The artifact is evaluated AFTER the step's own Cog answered, so
            # it may read this step's payload and envelope as well as its
            # dependencies' — but never its own decision, which does not
            # exist until the person has given it (0.7.0).
            _expr_problems(gate_artifact(step),
                           f"Op step {sid!r} gate.artifact", input_names,
                           step_ids, dep_ids | {sid}, loop_vars, problems,
                           human_steps - {sid})
        for index, requirement in enumerate(requirements(step)):
            if not isinstance(requirement, dict):
                continue
            for field in ("repositories", "changes"):
                if field in requirement:
                    _expr_problems(
                        requirement[field],
                        f"Op step {sid!r} authority.requires[{index}].{field}",
                        input_names, step_ids, dep_ids, loop_vars, problems,
                        human_steps)

    outputs = doc.get("outputs") or {}
    if not isinstance(outputs, dict):
        problems.append("the Op spec's outputs must be an object of mapping "
                        "expressions.")
    else:
        _expr_problems(outputs, "the Op spec's outputs", input_names, step_ids,
                       step_ids, set(), problems, human_steps)

    if problems:
        raise OpSpecError(problems)
    return ordered


class OpSpec:
    """A validated Op spec and the order its steps run in."""

    def __init__(self, doc, path=None):
        self.doc = doc
        self.path = Path(path).resolve() if path else None
        self.ordered = validate(doc)
        self.id = doc["id"]
        self.version = str(doc.get("version", ""))
        self.name = doc.get("name")
        self.description = doc.get("description")
        self.inputs = doc.get("inputs") or []
        self.steps = doc["steps"]
        self.outputs = doc.get("outputs") or {}
        self.track = doc.get("track") or {}
        self.authority = doc.get("authority") or {}
        self.ttl_minutes = ttl_minutes(doc)

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


def cog_step_findings(step, source_dir):
    """[(level, detail)] for one Cog step's declaration, checked against the
    Cog at SOURCE_DIR: it must be that Cog, and the task must be one of its
    declared USAGE interfaces. A source that is simply absent is a warning —
    the declaration could not be verified on this machine."""
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
        findings.append(("warn", f"Op step {sid!r} declares version "
                                 f"{cog['version']!r} but "
                                 f"{cog.get('source')!r} is at "
                                 f"{manifest.get('version')!r}."))
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


def declaration_problems(spec, package_root):
    """Every ERROR a step's Cog declaration carries, across the whole spec —
    what the runner refuses before it invokes anything."""
    problems = []
    for step in spec.ordered:
        source = (Path(package_root)
                  / str((step.get("cog") or {}).get("source"))).resolve()
        problems.extend(detail for level, detail
                        in cog_step_findings(step, source) if level == "error")
    return problems
