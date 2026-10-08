# Opportunity Shortlist (live admitted-provider)

This Op prepares fictional opportunities, assesses each using the fit Cog,
and pauses on a proposed shortlist for an explicit human decision.

Follow [the learning guide](../README.md) for setup, readable output and decision
helpers. This package owns only `op.yaml` and its documentation, examples and tests;
`src/` is unchanged shared Cog Smith Op machinery.

Raw invocation from this directory:

```sh
pixi install --locked
pixi run op -- --request examples/request.json --dry-run
pixi run op -- --request examples/request.json
```

A human pause exits 3. The saved Track and pending documents survive a restart.
Use the learning guide's explicit decision helper to continue; it calls the same
runtime. This workflow records an approved list and performs no external action.
