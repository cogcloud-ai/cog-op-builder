# Public preview: setup and verification

This preview uses sibling Git checkouts on macOS Apple Silicon or Linux x86-64.
Install Git, Python 3.11 or newer, and [Pixi](https://pixi.sh/latest/installation/).
The repository manifest pins component commits; existing checkouts are never
reset by the setup script. Use a new directory to reproduce the pinned preview.

```sh
mkdir builder-workspace
cd builder-workspace
git clone https://github.com/cogcloud-ai/cog-op-builder.git
python3 cog-op-builder/scripts/bootstrap.py --install
python3 cog-op-builder/scripts/verify.py
```

The bootstrap installs declared, locked package environments. Tests use synthetic
fixtures and local processes, not paid model calls or provider credentials.
Some optional legacy integration tests skip when packages outside this
preview are absent. GitHub Actions runs the same entry points.

## First executable example

```sh
cd op-builder-smoke
pixi run op -- --request examples/request.json
```

This calls the preserved [cog-merge-findings-candidate](https://github.com/cogcloud-ai/cog-merge-findings-candidate)
Cog twice and records a durable Track.
It demonstrates code-Cog execution and recovery, not a model-backed build.

## Build a Cog with a provider

Follow [Workbench's provider setup](https://github.com/cogcloud-ai/cog-workbench/blob/main/docs/tool-suite.md)
to admit a provider, then follow [op-cog-builder](https://github.com/cogcloud-ai/op-cog-builder#install-and-configure)
to activate the author and evaluator compositions and execute a build.
A subscription adapter requires the vendor CLI and your own authorized login;
OpenRouter requires your own API configuration. These are optional for tests.
Live use may incur provider charges.

The context Cogs retain a legacy native model reference to `cog-demo/cog-qwen3b`.
That private demonstration is not part of this distribution. Use the documented
`ask-composed` binding route for the builder; the native `resolve` demo is not a
fresh-checkout prerequisite. No missing model is silently downloaded or selected.

Source and declared tests execute with trusted local authority. Review inputs
and generated code before running them. This preview does not provide a sandbox.
A completed build is a reviewed candidate that a person explicitly accepted at
the Op's candidate Gate, bound to its digests; it is not release acceptance,
publication, or an authenticated approval.

After changing package source or metadata, re-admit affected providers and
reactivate consumer compositions. Binding files and run artifacts are local,
ignored state; never copy another person's credentials or installed bindings.
