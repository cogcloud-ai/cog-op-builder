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
- Run an accepted pure-code contract through one complete candidate review.
- Package source, execute declared tests and cases, and retain fingerprinted evidence.
- Resume failed execution without repeating reusable completed steps.
- Run model-free integration tests from a fresh sibling checkout.

## Remaining capabilities

- Connect brief intake to explicit contract and candidate acceptance decisions.
- Route review feedback through bounded, durable revision cycles.
- Build missing Cogs during Op construction and produce a validated final Op.
- Expose build status, evidence, approval, and recovery in Workbench.
- Resolve and install dependencies without relying on a fixed sibling layout.
- Strengthen execution isolation and independent evidence verification.
- Qualify a versioned release on supported platforms and provider versions.

GitHub issues are the work-status source of truth. Cross-repository outcomes
belong in this repository; implementation issues belong with their owning Cog
or Op. The organization project is [Collab Cog Builder](https://github.com/orgs/openteams-ai/projects/46).
Project visibility is controlled separately from the public repositories.
