---
type: cog [0.1]
name: fit
description: "Decision Cog. Assess one fictional opportunity using typed answers and explicit policy. A System One model answers its typed questions; its code makes the decision."
version: "0.1.0"
license: Apache-2.0
publisher: OpenTeams
manifest: cog.yaml
manifest_schema: openteams/cog-manifest [0.1]
---

# Assess opportunity fit

## Purpose

Make a bounded recommendation about one opportunity, using two typed judgments and explicit caller-supplied policy.

## Supported work

Ask scope_match and delivery_capacity; take their minimum; recommend pursue, review or pass. The fixture task uses exact synthetic examples. The live task requires a separately admitted composition. Neither approves an opportunity.

Inputs and outputs are declared in `context/input-schema.json` and
`context/output-schema.json`. The schemas and `src/task_logic.py` are author-owned.

## Unsupported work

No real opportunity discovery, external messages, document downloads, proposal
submissions or source modifications. This Cog reaches no external resource.
Fictional inputs and synthetic answers are teaching examples, not evidence of
model accuracy. Code runs with the local user's authority.

## Run and verify

```sh
pixi install --locked
pixi run fixture -- --request examples/sample-bundle.json
pixi run check
pixi run test
```

Results use envelope v1: `payload`, structured `problems` and execution `binding`.
A Cog reports; the Op's Gate decides how the result affects progression.

See [the learning guide](../README.md) for how this worker participates in the Op.
Shared runtime files in `src/` are Cog Smith machinery; do not edit them here.
