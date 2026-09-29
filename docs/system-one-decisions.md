# Decision Cogs and System One providers

Some work in an Op is a bounded judgment: route this ticket, is this brief a
code Cog, how risky is this change, does this output satisfy that rule. An
open-ended chat model can do it, but slowly, and without saying how sure it
is. A **System One model** — TypeSafe's
[Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev) is the
first public one — answers typed questions directly: a Noul (probability a
statement is true), a Choice (one of your declared options, with a
distribution) or a Score (a position on your ordered rubric, with a
distribution). Choice and Score answers also carry a confidence derived from
their distribution, and Jev is trained for calibration. Answers arrive in tens
to hundreds of milliseconds.

The suite supports this as a class of Cogs, a capability, and two providers.

| Piece | Repository | What it is |
|---|---|---|
| Decision class | [cog-smith](https://github.com/cogcloud-ai/cog-smith) | `smith new --class decision`: a context Cog whose context is a typed question set; `decide` in task logic turns answers into the decision. |
| Capability | — | `system-one/decisions`, with the turn contract `openteams/system-one-turn [0.1-draft]` (Smith's `system_one_contract.py`). |
| Jev provider | [cog-typesafe](https://github.com/cogcloud-ai/cog-typesafe) | `model+harness`; TypeSafe's API with a versioned Jev ID and `TYPESAFE_API_KEY`; `answer_source: system-one-model`. |
| LLM provider | [cog-system-one-adapter](https://github.com/cogcloud-ai/cog-system-one-adapter) | `harness` over an admitted OpenAI-compatible model (cog-qwen, cog-openrouter), using TypeSafe's MIT System One adapter; `answer_source: llm-adapter`. |
| Host | [cog-workbench](https://github.com/cogcloud-ai/cog-workbench) | Admits either binding and composes it with a decision Cog; the Cog never chooses its provider. |
| Example | [cog-brief-router](https://github.com/cogcloud-ai/cog-brief-router) | Recommends a code, context or decision Cog for a missing-Cog brief. |

## How it fits

A decision Cog is `kind: context`. Its manifest requires
`system-one/decisions`, names no default satisfier, and declares the class
with `extensions.system_one`. Its `workbench_composition` names the same
capability. Workbench admits a provider binding and composes it with the Cog;
each call is a harness turn whose task is `{state, questions}` and whose
result is `{model, answer_source, answers, usage}`. The Cog's machinery checks
every answer against the questions asked, then task logic decides. The payload
is always `{decision, answers, answered_by}`.

The two providers return the same shape with different meaning. Jev's
confidence is trained for calibration; the adapter's comes from probabilities
an LLM stated. Every result records `answer_source`, and the envelope binding
carries the full composition provenance, so Gates can weigh them differently.

## Try it without a key

```sh
cd cog-brief-router
pixi install
pixi run prepare -- --bundle examples/sample-bundle.json   # the turn it would send
pixi run replay -- --bundle examples/sample-bundle.json --result examples/sample-result.json
pixi run test
```

## Live with Jev

Set `TYPESAFE_API_KEY` (from the [TypeSafe console](https://console.typesafe.ai/keys))
in your environment, then:

```sh
(cd cog-typesafe && pixi install && pixi run models && pixi run probe -- --model jev-1.13.0)
(cd cog-workbench && pixi run suite -- bind --provider cog-typesafe \
  --request ../cog-typesafe/examples/bind-request.json)
(cd cog-workbench && pixi run suite -- activate-composition \
  --context cog-brief-router --binding-id binding-jev --revision 1)
(cd cog-brief-router && pixi run ask-composed -- --request examples/sample-bundle.json)
```

State leaves your machine for TypeSafe's cloud; TypeSafe's data terms apply.
Output tokens are free and input tokens are billed; the probe costs a
fraction of a cent.

## Live and local with Qwen

Admit cog-qwen as described in [its guide](https://github.com/cogcloud-ai/cog-qwen#readme),
keep its gateway running with `COG_QWEN_TOKEN` set, then bind the adapter over
that model binding (`cog-system-one-adapter/examples/bind-request.json`
expects cog-qwen's example `qwen-local`, revision 1, local) and activate it for the decision
Cog the same way. Nothing leaves the machine; answers are LLM-elicited.

## Build your own

```sh
cd cog-smith
pixi run new -- --dir <destination>/cog-my-router --class decision --yes
```

Edit `context/questions.json`, `context/input-schema.json`, `$defs.decision`
in the output schema, and `src/task_logic.py`; run `pixi run derive-schema`
and `pixi run test`. See cog-smith's BUILDING_COGS.md §7c.

## Not yet

- cog-author and cog-op-designer do not propose or author decision Cogs; the
  builder pipeline's author contract still offers `context` and `code` only.
  cog-brief-router is the first step toward routing briefs to the class.
- The satisfier-binding draft ties the `model` composition to chat
  completions, so Jev is admitted as `model+harness` with declaration
  evidence, and its results count as composed-system evidence only.
- Thresholds in decision Cogs are author policy; there is no calibration
  harness yet for comparing Jev and adapter answers on recorded cases.
