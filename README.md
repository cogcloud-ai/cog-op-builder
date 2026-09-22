# Cog / Op Builder

A tool suite for building and evaluating Cogs and Ops. Building an Op can identify missing Cogs, take those Cogs through their own build and evaluation pipeline, and use them to complete the Op.

This repository is the public entry point and coordination home for the suite: its roadmap, cross-repository issues, documentation, examples, and coordinating Ops. Reusable component Cogs retain their own repositories.

## Current state

The suite is under active development. A first single-candidate Cog-builder workflow has been implemented and live-tested locally:

**Author → materialize → plan → verify → review**

It starts from an accepted pure-code contract. Full brief intake, explicit artifact acceptance, automatic revisions, and the integrated Op-building workflow remain planned. The local implementation has not yet been brought into this repository; this is not an installable release.

## Components

- [Cog / Op designer](https://github.com/cogcloud-ai/cog-op-designer)
- [Cog author](https://github.com/cogcloud-ai/cog-author)
- [Cog Smith](https://github.com/cogcloud-ai/cog-smith) — deterministic packaging and shared machinery
- [Build evaluator](https://github.com/cogcloud-ai/cog-build-evaluator)
- [Workbench](https://github.com/cogcloud-ai/cog-workbench) — client and invocation environment

Additional local components include candidate materialization and verification Cogs, and the Cog-builder Op. These will be linked as they are published.

## Tracking work

Use this repository's issues for suite-wide outcomes and work spanning components. Component implementation issues and pull requests should link back to the relevant suite issue.

## License

This repository is licensed under the [Apache License 2.0](LICENSE). Separately maintained components retain their own licenses.
