# Public preview: setup and verification

This preview uses sibling Git checkouts on macOS Apple Silicon or Linux x86-64.
Install Git, Python 3.11 or newer, and [Pixi](https://pixi.sh/latest/installation/).
The repository manifest pins component commits; existing checkouts are never
reset by the setup script. Use a new directory to reproduce the pinned preview.

```sh
mkdir builder-workspace
cd builder-workspace
git clone https://github.com/cogcloud-ai/cog-op-builder.git
python3 cog-op-builder/scripts/bootstrap.py --strict --install
python3 cog-op-builder/scripts/verify.py --strict
```

The bootstrap installs declared, locked package environments. Tests use synthetic
fixtures and local processes, not paid model calls or provider credentials.
All integration fixtures are in the suite. GitHub Actions runs the same entry points.

## First executable example

```sh
cd op-builder-smoke
pixi run op -- --request examples/request.json
```

This calls [cog-word-tally](https://github.com/cogcloud-ai/cog-word-tally), a
Cog the builder itself produced, twice, passing the first tally into the second,
and records a durable Track. It demonstrates code-Cog execution and recovery,
not a model-backed build.

## Build a Cog with a provider

Follow [Workbench's provider setup](https://github.com/cogcloud-ai/cog-workbench/blob/main/docs/tool-suite.md)
to admit a provider, then follow [op-cog-builder](https://github.com/cogcloud-ai/op-cog-builder#install-and-configure)
to activate the author and evaluator compositions and execute a build.
A subscription adapter requires the vendor CLI and your own authorized login;
OpenRouter requires your own API configuration. These are optional for tests.
Live use may incur provider charges.

For local inference, follow [the Qwen provider guide](https://github.com/cogcloud-ai/cog-qwen#readme).
For typed, probabilistic decisions from TypeSafe's Jev or an admitted LLM, see
[decision Cogs and System One providers](system-one-decisions.md).
The context Cogs and new Smith packages default to the public `cog-qwen` sibling.
Weight download is explicit (`pixi run fetch` in that package); normal installation
and tests never fetch model weights. Pair an admitted Qwen model binding with
`cog-turn-harness` for the composed builder, or use the native resolver after
starting the local model with its documented token.

Source and declared tests execute with trusted local authority. Review inputs
and generated code before running them. This preview does not provide a sandbox.
A completed build is a reviewed candidate that a person explicitly accepted at
the Op's candidate Gate, bound to its digests; it is not release acceptance,
publication, or an authenticated approval.

After changing package source or metadata, re-admit affected providers and
reactivate consumer compositions. Binding files and run artifacts are local,
ignored state; never copy another person's credentials or installed bindings.

For development checks and dependency policy, see [workspace boundaries](workspace-boundary.md).
