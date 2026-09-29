# Cog / Op Builder

A tool suite for building and evaluating Cogs and Ops. Building an Op can identify missing Cogs, take those Cogs through their own build and evaluation pipeline, and use them to complete the Op.

This repository is the public entry point and coordination home for the suite: its roadmap, cross-repository issues, documentation, examples, and coordinating Ops. Reusable component Cogs retain their own repositories.

## Public preview

The component implementation is available in the linked repositories. This is
an experimental source distribution, not a production-ready release.

**Design → contract Gate → author → materialize → plan → verify → review →
candidate Gate** starts from a pure-code brief, pauses for an explicit decision
over the exact designed contract, builds and reviews one candidate, and pauses
for an explicit decision over that exact candidate. A rejection ends the run.
Automatic revisions and integrated Op building remain planned. Building an Op
will be able to create the Cogs it needs.

- [Guide to every repository](docs/repositories.md)
- [Fresh-checkout setup and model-free verification](docs/getting-started.md)
- [Roadmap and current capability boundaries](docs/roadmap.md)
- [Public workspace boundary](docs/workspace-boundary.md)
- [Local Qwen provider](https://github.com/cogcloud-ai/cog-qwen)
- [Decision Cogs with TypeSafe's Jev or an LLM (System One)](docs/system-one-decisions.md)
- [Pinned component manifest](repositories.json)

## Tracking work

Start with the [connected builder lifecycle issue](https://github.com/cogcloud-ai/cog-op-builder/issues/1),
which groups the component follow-up issues. Track their status on the
[Collab Cog Builder board](https://github.com/orgs/openteams-ai/projects/46/views/2)
(project access is managed separately from these public repositories).

Use this repository's issues for suite-wide outcomes and work spanning components.
Component implementation issues and pull requests link back to the relevant suite issue.

## License

Copyright 2026 OpenTeams. This repository is licensed under the [Apache License 2.0](LICENSE).

The maintained builder components have also been updated to Apache-2.0; see
the [migration record](docs/licensing-migration.md) for scope and commits.
Third-party dependencies and external services retain their own terms.
