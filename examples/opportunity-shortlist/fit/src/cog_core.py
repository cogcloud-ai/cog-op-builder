"""Shared core for a decision Cog (cog-smith decision-cog machinery, generic).

A decision Cog asks a System One model typed questions about its input —
Noul, Choice and Score, declared in context/questions.json — and turns the
typed, probabilistic answers into a decision its task logic owns. It is a
context Cog whose context is a question set rather than a prompt.

This file never chooses or calls a provider. The answers arrive through a
host-admitted binding for the `system-one/decisions` capability (Workbench
composition): `prepare` renders the turn, `finish` checks what came back and
builds the envelope. Everything task-specific lives in task_logic.py; this
file is byte-identical across created decision Cogs and verified by
`smith check`.

Payload shape (envelope v1 `payload`):
    {"decision": <task_logic.decide(...)>,        # author-owned $defs.decision
     "answers": {question id: typed answer},      # derived $defs.answers
     "answered_by": {"model", "answer_source"}}   # who answered, and how
"""
import copy
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import system_one_contract as contract  # noqa: E402
import task_logic                       # noqa: E402  (the ONLY per-cog module)

from jsonschema import Draft202012Validator  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MACHINERY = "decision-cog 0.1.4"
EXTENSION = "system_one"
EXTENSION_CONTRACT = "openteams/system-one-decision [0.1-draft]"


def load_manifest(root=None):
    """The profile manifest: `[tool.cog]` in pixi.toml (default) or cog.yaml.
    Exactly one — a package whose two manifests could disagree is refused."""
    root = Path(root or ROOT)
    pixi, standalone = root / "pixi.toml", root / "cog.yaml"
    doc = None
    if pixi.exists():
        import tomllib
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
    import yaml
    manifest = yaml.safe_load(standalone.read_text())
    if not isinstance(manifest, dict):
        raise ValueError("cog.yaml is not a mapping")
    return manifest


MANIFEST = load_manifest()
SELF_ID = {"id": MANIFEST.get("id"), "version": str(MANIFEST.get("version"))}
_CONTEXT = MANIFEST.get("context") or {}
_DECLARED = ((MANIFEST.get("extensions") or {}).get(EXTENSION) or {})


def _json(relative):
    return json.loads((ROOT / relative).read_text())


QUESTIONS = _json(_DECLARED.get("questions", "context/questions.json"))
INPUT_SCHEMA = _json(_CONTEXT.get("input_schema", "context/input-schema.json"))
OUTPUT_SCHEMA = _json(_CONTEXT.get("output_schema", "context/output-schema.json"))


def problem(check, detail, severity="error"):
    return {"check": check, "detail": str(detail), "severity": severity}


def task_logic_sha256():
    return hashlib.sha256((ROOT / "src" / "task_logic.py").read_bytes()).hexdigest()


def envelope(task, ok, payload=None, problems=None, error=None, binding=None):
    return {"envelope": 1, "cog": dict(SELF_ID), "task": task, "ok": bool(ok),
            "error": error, "payload": payload, "raw": None,
            "problems": problems or [], "binding": binding,
            "timing": {"latency_s": None}}


def _schema_problems(value, schema, check):
    found = []
    for error in sorted(Draft202012Validator(schema).iter_errors(value),
                        key=lambda e: list(e.absolute_path)):
        where = ".".join(str(p) for p in error.absolute_path) or "$"
        found.append(problem(check, f"{where}: {error.message}"[:300]))
    return found


# ------------------------------------------------------------ question set --

def derived_output_schema(output_schema=None, questions=None):
    """The output schema with `$defs.answers` derived from the questions.
    `pixi run derive-schema` writes it; `check` refuses drift."""
    schema = copy.deepcopy(OUTPUT_SCHEMA if output_schema is None else output_schema)
    schema.setdefault("$defs", {})["answers"] = contract.answers_schema(
        QUESTIONS if questions is None else questions)
    return schema


def questions_for(bundle):
    """The question set for one input. Task logic may rewrite instructions or
    rubric text per input (to point at data, say); it may not change what can
    be answered — ids, types, options and levels are fixed by questions.json,
    because the output schema is derived from them."""
    asked = task_logic.questions(bundle, copy.deepcopy(QUESTIONS))
    problems = contract._errors(asked, "questions")
    if not problems and contract.answers_schema(asked) != contract.answers_schema(QUESTIONS):
        problems.append("task_logic.questions changed question ids, types, "
                        "options or levels; only wording may vary per input")
    if problems:
        raise ValueError("Question set invalid: " + "; ".join(problems[:5]))
    return asked


def self_check():
    """Package self-consistency, model-free. Returns problem dicts."""
    problems = []
    if MANIFEST.get("kind") != "context":
        problems.append(problem("manifest", "a decision Cog is kind: context"))
    if _DECLARED.get("contract") != EXTENSION_CONTRACT:
        problems.append(problem("manifest", f"extensions.{EXTENSION}.contract must be {EXTENSION_CONTRACT!r}"))
    required = [r for r in MANIFEST.get("requires") or [] if r.get("capability") == contract.CAPABILITY]
    if len(required) != 1:
        problems.append(problem("manifest", f"requires exactly one {contract.CAPABILITY} capability"))
    composition = (MANIFEST.get("extensions") or {}).get("workbench_composition") or {}
    if composition.get("capability") != contract.CAPABILITY:
        problems.append(problem("manifest", f"workbench_composition.capability must be {contract.CAPABILITY}"))
    for detail in contract._errors(QUESTIONS, "questions"):
        problems.append(problem("questions", detail))
    if not problems:
        needed = sorted({q["type"] for q in QUESTIONS.values()})
        missing = sorted(set(needed) - set(composition.get("required_features") or []))
        if missing:
            problems.append(problem("manifest", f"workbench_composition.required_features must include the question types used: {missing}"))
        if OUTPUT_SCHEMA != derived_output_schema():
            problems.append(problem("schema", "context/output-schema.json $defs.answers is out of date with "
                                              "context/questions.json; run `pixi run derive-schema`"))
    for key in ("decision", "answers"):
        if key not in (OUTPUT_SCHEMA.get("$defs") or {}):
            problems.append(problem("schema", f"output schema needs $defs.{key}"))
    example = _CONTEXT.get("output_example")
    if example and (ROOT / example).exists():
        problems += _schema_problems(_json(example), OUTPUT_SCHEMA, "output-example")
    sample = ROOT / "examples" / "sample-bundle.json"
    if sample.exists():
        problems += _schema_problems(json.loads(sample.read_text()), INPUT_SCHEMA, "sample-bundle")
    return problems


# ------------------------------------------------------------ the turn -----

def validate_input(bundle):
    if not isinstance(bundle, dict):
        return [problem("input", "input is not an object")]
    return _schema_problems(bundle, INPUT_SCHEMA, "input") + task_logic.check_input(bundle)


def prepare(bundle):
    """Input bundle -> the System One turn a host sends to its admitted
    provider. No provider is named here; the host's binding decides."""
    problems = validate_input(bundle)
    refusing = [p for p in problems if p.get("severity") not in ("warning", "warn")]
    if refusing:
        raise ValueError("Input failed packaged checks: " + json.dumps(refusing[:5]))
    task = {"state": task_logic.state(bundle), "questions": questions_for(bundle)}
    contract.check_task(task)
    return {"consumer": dict(SELF_ID), "context": [], "task": task}


def finish(bundle, result, provenance=None):
    """Turn result -> envelope v1. Malformed answers fail the call; decision
    and output checks are reported as problems for a Gate to weigh."""
    problems = validate_input(bundle)
    refusing = [p for p in problems if p.get("severity") not in ("warning", "warn")]
    if refusing:
        raise ValueError("Input failed packaged checks: " + json.dumps(refusing[:5]))
    asked = questions_for(bundle)
    contract_problems = contract.result_problems(result, asked) if isinstance(result, dict) else ["result is not an object"]
    if contract_problems:
        return envelope("decide", False, error={"code": "answers-invalid", "detail": contract_problems[0]},
                        problems=problems + [problem("answers", p) for p in contract_problems], binding=provenance)
    saved_result = copy.deepcopy(result)
    answers = copy.deepcopy(result["answers"])
    payload = {"decision": task_logic.decide(bundle, answers),
               "answers": answers,
               "answered_by": {"model": result["model"], "answer_source": result["answer_source"]}}
    problems += _schema_problems(payload, OUTPUT_SCHEMA, "schema")
    problems += task_logic.check_output(payload, bundle)
    output = envelope("decide", True, payload=payload, problems=problems, binding=provenance)
    output["provider_result"] = saved_result
    return output
