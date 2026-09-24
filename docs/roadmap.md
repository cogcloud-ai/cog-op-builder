# Builder suite roadmap

The suite is one product with connected workflows: building an Op may identify,
build, evaluate, and then use missing Cogs. Smith owns deterministic packaging
and shared machinery. The designer, author, and evaluator own model judgment.
Workbench is the client and invocation environment; coordinating Ops own the
lifecycle. Package checks are not independent Guards, and Gates decide whether
work may proceed based on evidence and policy.

## Available in this preview

- Propose an Op and produce missing-Cog briefs.
- Author and revise context or pure-code Cogs through separate Cog contracts.
- Design a pure-code contract from a brief and record an explicit, digest-bound
  acceptance decision before anything is authored (2026-09-23).
- Run the accepted contract through one complete candidate review and record an
  explicit, digest-bound acceptance or rejection of that exact candidate;
  review completion is never acceptance (2026-09-23).
- Package source, execute declared tests and cases, and retain fingerprinted evidence.
- Resume failed or paused execution without repeating reusable completed steps;
  a pending decision survives a restart.
- Run model-free integration tests from a fresh sibling checkout.
- One Cog, cog-word-tally, built live from a brief through both Gates and
  published; the builder's smoke Op exercises it (2026-09-23).

## Remaining capabilities

- Authenticate the decider and present pending decisions in Workbench (today
  `decided_by` is what the caller wrote).
- Route review feedback and rejection reasons through bounded, durable revision
  cycles (the 0.1.0 caller-prepared revise entry point is withdrawn until then).
- Build missing Cogs during Op construction and produce a validated final Op.
- Expose build status, evidence, approval, and recovery in Workbench.
- Resolve and install dependencies without relying on a fixed sibling layout.
- Strengthen execution isolation and independent evidence verification.
- Qualify a versioned release on supported platforms and provider versions.

GitHub issues are the work-status source of truth. Cross-repository outcomes
belong in this repository; implementation issues belong with their owning Cog
or Op. The organization project is [Collab Cog Builder](https://github.com/orgs/openteams-ai/projects/46).
Project visibility is controlled separately from the public repositories.

The active [lifecycle roadmap issue](https://github.com/cogcloud-ai/cog-op-builder/issues/1)
contains 17 component sub-issues. The acceptance Gates landed in op-cog-builder
0.2.0 on Op machinery 0.7.0 (see its
[acceptance Gates note](https://github.com/cogcloud-ai/op-cog-builder/blob/main/docs/acceptance-gates-2026-09-23.md));
the missing-Cog handoff, isolated verification, and Workbench lifecycle UI are
in Ready; other work is in Backlog. Consult the issue and board for current
status.
