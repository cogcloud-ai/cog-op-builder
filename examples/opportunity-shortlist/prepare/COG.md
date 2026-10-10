---
type: cog [0.1]
name: prepare
description: "Code Cog. Validate fictional opportunities for a learning workflow. No model in the loop; what it reaches outside the run is declared in the manifest."
version: "0.1.0"
license: Apache-2.0
publisher: OpenTeams
manifest: cog.yaml
manifest_schema: openteams/cog-manifest [0.1]
---

# Prepare opportunities

## Purpose

Validate a small supplied list of fictional opportunities, company capabilities and policy thresholds before downstream judgment.

## Supported work

Preserve all supplied data; refuse duplicate ids, missing required values and invalid threshold order. Return opportunities, company, policy and an empty authority-use list.

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
pixi run run -- --bundle examples/sample-bundle.json
pixi run check
pixi run test
```

Results use envelope v1: `payload`, structured `problems` and execution `binding`.
A Cog reports; the Op's Gate decides how the result affects progression.

See [the learning guide](../README.md) for how this worker participates in the Op.
Shared runtime files in `src/` are Cog Smith machinery; do not edit them here.
