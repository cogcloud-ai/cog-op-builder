"""System One turn contract, openteams/system-one-turn [0.1-draft].

Typed questions go in; typed, probabilistic answers come out. The question and
answer shapes follow TypeSafe's public System One API
(https://docs.typesafe.ai/api): Noul (yes/no probability), Choice (one option
plus a distribution) and Score (an ordered rubric plus a distribution).

A turn task is ``{"state": <text or JSON>, "questions": {id: question}}``.
A turn result is ``{"model", "answer_source", "answers", "usage"}``, where
``answer_source`` says whether a System One model answered
(``system-one-model``) or an LLM was asked for the same typed answers through
an adapter (``llm-adapter``). The two are interchangeable in shape, never in
meaning: LLM-stated probabilities are not calibrated decisions.

Canonical source: cog-smith/templates/decision-cog/src/system_one_contract.py
(decision-Cog machinery, verified by hash). System One providers vendor this
file byte-identically. Standard library plus jsonschema only.

    python src/system_one_contract.py schema             # the turn contract
    python src/system_one_contract.py derive Q.json      # answers schema for Q
"""
import json
import math
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

CONTRACT = "openteams/system-one-turn [0.1-draft]"
CAPABILITY = "system-one/decisions"
QUESTION_TYPES = ("noul", "choice", "score")
ANSWER_SOURCES = ("system-one-model", "llm-adapter")
MAX_QUESTIONS = 64
MAX_CHOICE_OPTIONS = 255
MIN_LEVELS, MAX_LEVELS = 2, 10
MAX_STATE_BYTES = 512 * 1024
# Providers report floats that sum to 1, often rounded to two decimals, so
# the allowed error grows with the number of options (capped); a missing
# mass is never accepted.
def probability_tolerance(n):
    return min(0.01 + 0.005 * n, 0.1) + 1e-9

_RUBRIC = {"anyOf": [{"type": "string", "minLength": 1},
                     {"type": "object", "minProperties": 1},
                     {"type": "array", "minItems": 1}]}
_PROBABILITY = {"type": "number", "minimum": 0, "maximum": 1}

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "urn:openteams:system-one-turn:0.1-draft",
    "title": "System One turn task and result (proposal)",
    "$defs": {
        "rubric": _RUBRIC,
        "noul": {
            "type": "object", "additionalProperties": False,
            "required": ["type", "instructions"],
            "properties": {
                "type": {"const": "noul"},
                "instructions": {"$ref": "#/$defs/rubric"},
                "criteria": {"type": "object", "additionalProperties": False,
                             "properties": {"true": {"$ref": "#/$defs/rubric"},
                                            "false": {"$ref": "#/$defs/rubric"}}}}},
        "choice": {
            "type": "object", "additionalProperties": False,
            "required": ["type", "instructions", "criteria"],
            "properties": {
                "type": {"const": "choice"},
                "instructions": {"$ref": "#/$defs/rubric"},
                "criteria": {"type": "object", "minProperties": 2,
                             "maxProperties": MAX_CHOICE_OPTIONS,
                             "propertyNames": {"minLength": 1, "maxLength": 200},
                             "additionalProperties": {"anyOf": [
                                 {"$ref": "#/$defs/rubric"}, {"type": "null"}]}}}},
        "score": {
            "type": "object", "additionalProperties": False,
            "required": ["type", "instructions", "criteria"],
            "properties": {
                "type": {"const": "score"},
                "instructions": {"$ref": "#/$defs/rubric"},
                "criteria": {"type": "array", "minItems": MIN_LEVELS,
                             "maxItems": MAX_LEVELS,
                             "items": {"$ref": "#/$defs/rubric"}}}},
        "question": {"oneOf": [{"$ref": "#/$defs/noul"},
                               {"$ref": "#/$defs/choice"},
                               {"$ref": "#/$defs/score"}]},
        "questions": {"type": "object", "minProperties": 1,
                      "maxProperties": MAX_QUESTIONS,
                      "propertyNames": {"pattern": "^[A-Za-z][A-Za-z0-9_]{0,63}$"},
                      "additionalProperties": {"$ref": "#/$defs/question"}},
        "state": {"anyOf": [{"type": "string", "minLength": 1},
                            {"type": "object", "minProperties": 1},
                            {"type": "array", "minItems": 1}]},
        "task": {"type": "object", "additionalProperties": False,
                 "required": ["state", "questions"],
                 "properties": {"state": {"$ref": "#/$defs/state"},
                                "questions": {"$ref": "#/$defs/questions"}}},
        "probability": _PROBABILITY,
        "distribution": {"type": "object", "minProperties": 1,
                         "additionalProperties": {"$ref": "#/$defs/probability"}},
        "noul_answer": {
            "type": "object", "additionalProperties": False,
            "required": ["type", "noul"],
            "properties": {"type": {"const": "noul"},
                           "noul": {"$ref": "#/$defs/probability"}}},
        "choice_answer": {
            "type": "object", "additionalProperties": False,
            "required": ["type", "choice", "probabilities", "confidence"],
            "properties": {"type": {"const": "choice"},
                           "choice": {"type": "string", "minLength": 1},
                           "probabilities": {"$ref": "#/$defs/distribution"},
                           "confidence": {"$ref": "#/$defs/probability"}}},
        "score_answer": {
            "type": "object", "additionalProperties": False,
            "required": ["type", "score", "legend", "probabilities", "confidence"],
            "properties": {"type": {"const": "score"},
                           "score": {"type": "number", "minimum": 0},
                           "legend": {"type": "object", "minProperties": 1},
                           "probabilities": {"$ref": "#/$defs/distribution"},
                           "confidence": {"$ref": "#/$defs/probability"}}},
        "answer": {"oneOf": [{"$ref": "#/$defs/noul_answer"},
                             {"$ref": "#/$defs/choice_answer"},
                             {"$ref": "#/$defs/score_answer"}]},
        "usage": {"type": "object", "additionalProperties": False,
                  "required": ["input_tokens", "output_tokens"],
                  "properties": {
                      "input_tokens": {"anyOf": [{"type": "integer", "minimum": 0}, {"type": "null"}]},
                      "output_tokens": {"anyOf": [{"type": "integer", "minimum": 0}, {"type": "null"}]}}},
        "result": {"type": "object", "additionalProperties": False,
                   "required": ["model", "answer_source", "answers", "usage"],
                   "properties": {"model": {"type": "string", "minLength": 1},
                                  "answer_source": {"enum": list(ANSWER_SOURCES)},
                                  "answers": {"type": "object",
                                              "additionalProperties": {"$ref": "#/$defs/answer"}},
                                  "usage": {"$ref": "#/$defs/usage"}}},
    },
}


def _errors(value, definition, echo=True):
    """Schema problems as strings. With echo=False (provider results) the
    message names the rule only: result paths can contain provider-supplied keys."""
    schema = dict(SCHEMA, **{"$ref": "#/$defs/" + definition})
    found = []
    for error in sorted(Draft202012Validator(schema).iter_errors(value),
                        key=lambda e: list(e.absolute_path)):
        where = ("/".join(str(p)[:64] for p in error.absolute_path) or "$") if echo else "$"
        detail = error.message if echo else f"violates {error.validator}"
        found.append(f"{definition} {where}: {detail}"[:300])
    return found


def _finite(value):
    return ((isinstance(value, int) and not isinstance(value, bool))
            or (isinstance(value, float) and math.isfinite(value)))


def _short(value, limit=64):
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "..."


def task_problems(task):
    """Contract problems in a turn task, as strings. Empty means valid."""
    problems = _errors(task, "task")
    if problems:
        return problems
    size = len(json.dumps(task["state"], ensure_ascii=False).encode())
    if size > MAX_STATE_BYTES:
        problems.append(f"task state is {size} bytes; the limit is {MAX_STATE_BYTES}")
    for qid, question in task["questions"].items():
        if question["type"] == "choice" and any(not k.strip() for k in question["criteria"]):
            problems.append(f"question {qid}: choice options must not be blank")
    return problems


def check_task(task):
    problems = task_problems(task)
    if problems:
        raise ValueError("System One task invalid: " + "; ".join(problems[:5]))
    return task


def levels(question):
    """Score level keys, as the API reports them: "0" .. "n-1"."""
    return [str(i) for i in range(len(question["criteria"]))]


def _mass(problems, qid, probabilities):
    total = sum(probabilities.values())
    if abs(total - 1) > probability_tolerance(len(probabilities)):
        problems.append(f"answer {qid}: probabilities do not sum to 1")


def result_problems(result, questions):
    """Contract problems in a turn result against the questions that were
    asked: shape first, then every question answered once, with its own type,
    over exactly the options or levels it declared."""
    problems = _errors(result, "result", echo=False)
    if problems:
        return problems
    answers = result["answers"]
    missing = sorted(set(questions) - set(answers))
    extra = sorted(set(answers) - set(questions))
    if missing:
        problems.append(f"unanswered questions: {missing[:10]}")
    if extra:
        problems.append(f"{len(extra)} answer(s) to questions that were not asked")
    if problems:
        return problems
    # JSON Schema bounds pass NaN (every comparison with NaN is false), so
    # every number a provider returns is checked for finiteness here.
    for qid, answer in answers.items():
        numbers = [answer.get(k) for k in ("noul", "confidence", "score") if k in answer]
        numbers += list((answer.get("probabilities") or {}).values())
        if not all(_finite(v) for v in numbers):
            problems.append(f"answer {_short(qid)}: every number must be finite")
    if problems:
        return problems
    for qid in sorted(set(questions) & set(answers)):
        question, answer = questions[qid], answers[qid]
        if answer["type"] != question["type"]:
            problems.append(f"answer {qid}: type {answer['type']} answers a {question['type']} question")
            continue
        if question["type"] == "choice":
            options = list(question["criteria"])
            probabilities = answer["probabilities"]
            if set(probabilities) != set(options):
                problems.append(f"answer {qid}: probabilities must cover exactly the declared options")
                continue
            if answer["choice"] not in options:
                problems.append(f"answer {qid}: choice is not a declared option")
                continue
            _mass(problems, qid, probabilities)
            if probabilities[answer["choice"]] + 1e-9 < max(probabilities.values()):
                problems.append(f"answer {qid}: choice is not the highest-probability option")
        elif question["type"] == "score":
            keys = levels(question)
            if set(answer["probabilities"]) != set(keys) or set(answer["legend"]) != set(keys):
                problems.append(f"answer {qid}: probabilities and legend must cover levels {keys}")
                continue
            _mass(problems, qid, answer["probabilities"])
            if answer["score"] > len(keys) - 1 + 1e-9:
                problems.append(f"answer {qid}: score exceeds the declared top level")
                continue
            probabilities = answer["probabilities"]
            total = sum(probabilities.values())
            if total > 0:
                expected = sum(i * probabilities[k] for i, k in enumerate(keys)) / total
                # Allow two-decimal rounding of both the probabilities and
                # score. Normalizing avoids treating rounded missing mass as
                # an implicit probability at level zero.
                tolerance = 0.01 + 0.005 * sum(abs(i - expected) for i in range(len(keys)))
                if abs(answer["score"] - expected) > tolerance + 1e-9:
                    problems.append(f"answer {qid}: score disagrees with its probability distribution")
    return problems


def check_result(result, questions):
    problems = result_problems(result, questions)
    if problems:
        raise ValueError("System One result invalid: " + "; ".join(problems[:5]))
    return result


def answers_schema(questions):
    """The strict answers schema implied by a question set. Decision Cogs
    carry it as `$defs.answers` in their output schema, so the output
    contract follows from the questions rather than being restated by hand."""
    properties = {}
    for qid, question in questions.items():
        kind = question["type"]
        if kind == "noul":
            answer = {"type": "object", "additionalProperties": False,
                      "required": ["type", "noul"],
                      "properties": {"type": {"const": "noul"}, "noul": _PROBABILITY}}
        elif kind == "choice":
            options = list(question["criteria"])
            answer = {"type": "object", "additionalProperties": False,
                      "required": ["type", "choice", "probabilities", "confidence"],
                      "properties": {
                          "type": {"const": "choice"},
                          "choice": {"enum": options},
                          "probabilities": {"type": "object", "additionalProperties": False,
                                            "required": options,
                                            "properties": {o: _PROBABILITY for o in options}},
                          "confidence": _PROBABILITY}}
        else:
            keys = levels(question)
            answer = {"type": "object", "additionalProperties": False,
                      "required": ["type", "score", "legend", "probabilities", "confidence"],
                      "properties": {
                          "type": {"const": "score"},
                          "score": {"type": "number", "minimum": 0, "maximum": len(keys) - 1},
                          "legend": {"type": "object", "additionalProperties": False,
                                     "required": keys, "properties": {k: {} for k in keys}},
                          "probabilities": {"type": "object", "additionalProperties": False,
                                            "required": keys,
                                            "properties": {k: _PROBABILITY for k in keys}},
                          "confidence": _PROBABILITY}}
        properties[qid] = answer
    return {"type": "object", "additionalProperties": False,
            "required": list(questions), "properties": properties}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["schema"] and len(argv) == 1:
        print(json.dumps(SCHEMA, indent=2))
        return 0
    if argv[:1] == ["derive"] and len(argv) == 2:
        questions = json.loads(Path(argv[1]).read_text())
        problems = _errors(questions, "questions")
        if problems:
            print("\n".join(problems), file=sys.stderr)
            return 1
        print(json.dumps(answers_schema(questions), indent=2))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
