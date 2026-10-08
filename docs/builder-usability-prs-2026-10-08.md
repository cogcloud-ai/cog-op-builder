# Builder usability PR set — 2026-10-08

This coordinates the linked learning/usability fixes requested for the demo.
Each implementation remains in its owning public repository. Pins identify
published PR commits so the combined changes can be tested before merging;
these are preview integration pins, not a claim that the PRs have merged.

| Issue | PR | Learner-visible outcome |
| --- | --- | --- |
| Workbench #1 | [Workbench #5](https://github.com/cogcloud-ai/cog-workbench/pull/5) | Saved native builds, steps, evidence, Gates and resume after reload |
| Workbench #3 | [Workbench #4](https://github.com/cogcloud-ai/cog-workbench/pull/4) | Activate an entire Op once; portable records and concrete repair commands |
| Smith #4 | [Smith #19](https://github.com/cogcloud-ai/cog-smith/pull/19) | Prepare explicit decisions and admission scaffolds without hand-copying hashes |
| Op builder #2 | [Builder #4](https://github.com/cogcloud-ai/op-cog-builder/pull/4), [Smith #21](https://github.com/cogcloud-ai/cog-smith/pull/21) | Bounded repair/evidence rounds retaining every attempt and final acceptance |
| Author #1 | [Author #2](https://github.com/cogcloud-ai/cog-author/pull/2) | A stable revision request bound to accepted contract, candidate and actual review |
| Designer #1 | [Designer #2](https://github.com/cogcloud-ai/cog-op-designer/pull/2) | Stable missing-Cog handoff and validated final Op from accepted children |
| Verifier #1 | [Verifier #3](https://github.com/cogcloud-ai/cog-verify-candidate/pull/3) | Explicit isolated policy, bounded execution and retained failure observations |
| ChatGPT #1 | [ChatGPT #2](https://github.com/cogcloud-ai/cog-chatgpt/pull/2) | Exact CLI/model qualification with opt-in live probes and safe reports |
| Claude #1 | [Claude #2](https://github.com/cogcloud-ai/cog-claude/pull/2) | The same qualification procedure for Claude Code |
| Smith #7 | [Smith #17](https://github.com/cogcloud-ai/cog-smith/pull/17), already merged | Saved provider results, envelope replay and fixture export |

Companions: [Smith #20](https://github.com/cogcloud-ai/cog-smith/pull/20)
updates behavior fingerprints and generated decision adapters;
[Candidate #2](https://github.com/cogcloud-ai/cog-build-candidate/pull/2)
accepts bound revision receipts;
[Evaluator #2](https://github.com/cogcloud-ai/cog-build-evaluator/pull/2) and
[Brief Router #2](https://github.com/cogcloud-ai/cog-brief-router/pull/2)
consume portable activation records;
[Turn Harness #2](https://github.com/cogcloud-ai/cog-turn-harness/pull/2)
owns the shared qualification source.
[Tutorial #4](https://github.com/cogcloud-ai/cog-op-builder/pull/4) provides the
small independent Opportunity Shortlist example, documentation and exercises.

## Review and merge order

1. Smith #19 → #20 → #21 (stacked bases); Workbench #4 → #5 (stacked bases).
2. Author, Designer, Candidate, Verifier, Evaluator and Brief Router companions;
   shared qualification source and both subscription copies can be reviewed together.
3. Builder #4 after its companion APIs; tutorial #4 and the suite integration
   layer after the component changes. Refresh integration pins to the final
   merged commits if squash/rebase changes their identities.

No PR merges or release publication are performed by this change. The broader
suite lifecycle umbrella contains additional roadmap issues outside this selected
usability set; this integration does not claim to close that entire umbrella.

## Demo and exercises

Start with the [Opportunity Shortlist guide](../examples/opportunity-shortlist/README.md):
run one fictional decision Cog, then the offline Op with three opportunities,
inspect the human Gate, save a decision and resume. Its fixtures are explicitly
synthetic and tied to the complete question task, so learners do not mistake
replay for live inference. Use its six exercises and facilitator notes first.

Next use [Saved Cog builds](https://github.com/cogcloud-ai/cog-workbench/blob/feat/durable-builder-studio/docs/tool-suite.md)
in Studio for a small pure-code brief. Accept the contract, inspect candidate
source/test observations/review, and separately accept or reject the final package.
Explain round/model-turn budgets before starting; these are invocation caps, not
price estimates. Show restoration after reload and terminal rejection/exhaustion.

Advanced exercises:

- Change the brief's acceptance requirement, then find where contract acceptance
  is bound into Author, packaging, verification and final acceptance. Explain
  why changing a review cannot change the accepted contract.
- Use a deliberately failing authored fixture with the model-free cycle test.
  Compare both candidate directories and reviews; identify the scoped revision
  receipt and the unchanged contract digest.
- Interrupt a model-free build and resume it. Identify which passed steps were
  reused and which cost reservations survived; explain why a failed Gate retries.
- Follow Designer's public `design-handoff prepare` example. Inspect its stable
  missing IDs and `build_origin`; use actual accepted child Tracks to finalize
  the Op. Try a rejected child or wrong proposal ID and explain the refusal.
- Replay the decision Cog's saved envelope using `pixi run replay -- --bundle
  BUNDLE --result ENVELOPE`. Use Smith's documented `export-fixtures` task for a
  real decision step after checking all inputs/results for sensitive information.
- Opt into Docker verification with a pinned image. Compare its policy receipt
  with trusted-local evidence, and inspect a retained timeout/output-limit result.
- Run provider qualification only with an independently admitted binding and
  explicit model. Distinguish readiness, synthetic tests, credentialed live
  qualification, and composed-system evidence from bare-model evaluation.

## Validation limits

All inference fixtures in the new integration tests are synthetic. The native
builder tests actually package, execute and verify candidate code, prepare a
revision request, review the repaired candidate and require final acceptance.
Docker confinement passed in Linux CI; the local macOS machine has no daemon.
Provider readiness passed on macOS arm64 for Codex 0.161.0 and Claude Code
2.1.293. Credentialed live model qualification remains an explicit opt-in
procedure and was not run for these PRs. The static public boundary scan retains
40 individually recorded legacy occurrences and adds none.

The full suite also runs `scripts/check_connected_handoff.py`: it repairs a failing
public synthetic candidate through native packaging/verification, accepts that
exact child, then passes its real saved documents through Designer finalization
and validates the resulting executable Op. No fixture source is private or
read from a previous ignored run.
