# Repository guide

The Cog / Op Builder is one suite. Start with [setup](getting-started.md), then
[the roadmap](roadmap.md). All repositories below live in `cogcloud-ai`.

| Repository | Role | Responsibility |
|---|---|---|
| [cog-op-builder](https://github.com/cogcloud-ai/cog-op-builder) | Suite | Entry point, pinned checkout manifest, setup, CI, roadmap, and cross-repository issues. |
| [cog-smith](https://github.com/cogcloud-ai/cog-smith) | core | Deterministic Cog/Op packaging, validation, and shared execution machinery. |
| [cog-op-designer](https://github.com/cogcloud-ai/cog-op-designer) | core | Propose Ops, reuse existing Cogs, and describe missing Cogs. |
| [cog-author](https://github.com/cogcloud-ai/cog-author) | core | Turn briefs into contracts and author or revise Cog source. |
| [cog-build-evaluator](https://github.com/cogcloud-ai/cog-build-evaluator) | core | Plan acceptance cases and review candidate-bound evidence. |
| [cog-build-candidate](https://github.com/cogcloud-ai/cog-build-candidate) | core | Materialize validated authored source as a checked package. |
| [cog-verify-candidate](https://github.com/cogcloud-ai/cog-verify-candidate) | core | Run declared tests and cases; collect evidence without accepting a candidate. |
| [op-cog-builder](https://github.com/cogcloud-ai/op-cog-builder) | core | Compose author → materialize → plan → verify → review. |
| [cog-workbench](https://github.com/cogcloud-ai/cog-workbench) | core | Local client, provider admission, composed invocation, and build UI. |
| [cog-chatgpt](https://github.com/cogcloud-ai/cog-chatgpt) | provider | Use a separately installed Codex CLI and the user’s ChatGPT login. |
| [cog-claude](https://github.com/cogcloud-ai/cog-claude) | provider | Use a separately installed Claude Code CLI and the user’s Claude login. |
| [cog-openrouter](https://github.com/cogcloud-ai/cog-openrouter) | provider | Admit and invoke a direct OpenRouter model through a local gateway. |
| [cog-turn-harness](https://github.com/cogcloud-ai/cog-turn-harness) | provider | Provide a JSON interaction using a separately admitted model. |
| [op-builder-smoke](https://github.com/cogcloud-ai/op-builder-smoke) | example | Exercise real code-Cog handoffs, stopping, and durable resume. |
| [cog-merge-findings-candidate](https://github.com/cogcloud-ai/cog-merge-findings-candidate) | example | Preserved pipeline-built merge example used by the smoke Op. |

## Relationships

`op-cog-builder` invokes `cog-author`, `cog-build-candidate`,
`cog-build-evaluator`, and `cog-verify-candidate`. The deterministic workers
use Workbench's local services and Smith's packaging/checking machinery.
Workbench connects the context Cogs to the chosen provider. `cog-op-designer`
produces proposals and missing-Cog briefs; automatically building those missing
Cogs and completing the Op remains planned.

`cog-chatgpt` and `cog-claude` each include their vendor CLI interaction.
`cog-openrouter` supplies model access, paired with `cog-turn-harness` for
structured turns. Their own code is open source; external services, accounts,
CLIs, and model weights retain their own terms.

The merge candidate is a preserved example, not the canonical merge
implementation or a newly accepted release. The builder components and this
example use Apache-2.0. Historical qualification artifacts are not included.

Other projects developed alongside the suite (a governed harness, earlier
frozen clients, model demonstrations, triage and transcription Cogs, and
CogCloud applications) are separate and not distributed. They are not required
for the documented preview. Vendored contract schemas carry their recorded
provenance; the packages they came from are not required to run the suite.
