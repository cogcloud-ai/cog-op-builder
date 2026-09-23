# Public preview preparation — 2026-09-23

The suite contains 14 component repositories plus this coordination repository.
The [manifest](../repositories.json) pins component commits for this preview;
[the guide](repositories.md) explains each repository's role.

## Verification

A separate workspace was cloned from committed content, with no local binding,
run, or installation state copied. `bootstrap.py --install` installed the locked
Pixi environments, and `verify.py` completed all component suites on macOS ARM64.
No paid model calls or provider credentials were used.

| Component | Tests | Result |
|---|---:|---|
| cog-smith | 584 | OK |
| cog-op-designer | 11 | OK |
| cog-author | 23 | OK |
| cog-build-evaluator | 21 | OK |
| cog-build-candidate | 3 | OK |
| cog-verify-candidate | 2 | OK |
| op-cog-builder | 9 | OK |
| cog-workbench | 67 | OK (skipped=5) |
| cog-chatgpt | 105 | OK (skipped=6) |
| cog-claude | 105 | OK (skipped=6) |
| cog-openrouter | 30 | OK |
| cog-turn-harness | 105 | OK (skipped=5) |
| op-builder-smoke | 8 | OK |
| cog-merge-findings-candidate | 13 | OK |

Skipped checks require legacy forge/issue-classifier packages outside this
preview, or do not apply to a particular provider composition. GitHub Actions
also exercises Linux and macOS; consult the current workflow runs for results.
Smith package checks completed without errors. Custom providers and Smith itself
correctly report that they do not use Smith's generated runtime machinery.

Gitleaks 8.30.1 reported no findings in the existing repositories' reachable Git
history or the staged preview changes. This is an automated scan, not proof that
all sensitive information has been excluded. Installed credentials, local binding
records, run directories, and private inputs are excluded from publication.

Meaningful machinery history was retained. License-only remote commits were
reconciled with the local implementation without force-pushing or deleting prior
commits. New component packages received focused initial commits.

## Scope

This is a source preview. It supports single-candidate pure-code builds from an
accepted contract. Automatic acceptance, revision orchestration, missing-Cog
builds within Op construction, registry installation, and execution isolation
remain follow-up work. The historical live qualification reports remain summaries
of earlier exact package versions; their raw local records are not distributed.
