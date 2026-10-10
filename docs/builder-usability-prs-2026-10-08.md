# Builder usability PR set — 2026-10-08

This coordinates the linked learning/usability fixes requested for the demo.
Each implementation remains in its owning public repository. Pins identify
published commits so the combined changes can be tested before merging.
All selected component changes are now merged onto their repositories' main
branches, and the component pins identify their actual main-branch merge commits.

| Issue | PR | Learner-visible outcome |
| --- | --- | --- |
| Workbench #1 | [Workbench #5](https://github.com/cogcloud-ai/cog-workbench/pull/5) | Saved native builds, steps, evidence, Gates and resume after reload |
| Workbench #3 | [Workbench #4](https://github.com/cogcloud-ai/cog-workbench/pull/4) | Activate an entire Op once; portable records and concrete repair commands |
| Smith #4 | [Smith #19](https://github.com/cogcloud-ai/cog-smith/pull/19) | Prepare explicit decisions and admission scaffolds without hand-copying hashes |
| Op builder #2 | [Builder #4](https://github.com/cogcloud-ai/op-cog-builder/pull/4), [Smith #21](https://github.com/cogcloud-ai/cog-smith/pull/21) | Bounded repair/evidence rounds retaining every attempt and final acceptance |
| Author #1 | [Author #2](https://github.com/cogcloud-ai/cog-author/pull/2) | A stable revision request bound to accepted contract, candidate and actual review |
| Designer #1 | [Designer #2](https://github.com/cogcloud-ai/cog-op-designer/pull/2) | Stable missing-Cog handoff and validated final Op from accepted children |
| Verifier #1 | [Verifier #3](https://github.com/cogcloud-ai/cog-verify-candidate/pull/3) | Explicit isolated policy, bounded execution and retained failure observations |
| ChatGPT #1 | [ChatGPT #2](https://github.com/cogcloud-ai/cog-chatgpt/pull/2) | Exact CLI and requested-model qualification with opt-in live probes and safe reports |
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

All component prerequisites have merged, including Verifier #3 and
[Workbench #6](https://github.com/cogcloud-ai/cog-workbench/pull/6).
Workbench #5 merged into `feat/op-composition-setup`; #6 landed those reviewed
changes onto `main`. Smith #22 landed the analogous Smith stack on main.
Tutorial #4 is on main; suite integration #5 now targets main and includes it.
The Workbench pin now identifies its actual merge commit, `fc9bb85`, whose tree
matches the verified landing branch exactly. Suite integration #5 is the final
merge in this set. The original dependency order is retained below for context.

1. Workbench #4, then Smith #19 → #20 → #21.
   Land the portable adapter consumers (Author, Evaluator, Brief Router) with
   Workbench: old adapters cannot read the new relative records. Re-admit
   existing providers and reactivate consumers after the fingerprint upgrade.
2. Designer, Candidate and Verifier companions;
   shared qualification source and both subscription copies can be reviewed together.
3. Builder #4 after its companion APIs, then Workbench #5 after Builder #4
   and Smith #21. Tutorial #4 and the suite integration
   layer after the component changes. Refresh integration pins to the final
   merged commits if squash/rebase changes their identities. Also remove the
   preview suite checkout refs in Builder, Smith, Workbench, Brief Router and all three provider workflows
   once coordinated main contains these APIs; retain preview refs until then.

No PR merges or release publication are performed by this change. The broader
suite lifecycle umbrella contains additional roadmap issues outside this selected
usability set; this integration does not claim to close that entire umbrella.

## Demo and exercises

Start with the [Opportunity Shortlist guide](../examples/opportunity-shortlist/README.md):
run one fictional decision Cog, then the offline Op with three opportunities,
inspect the human Gate, save a decision and resume. Its `fixture` task uses synthetic answers tied to the complete question task, so learners do not mistake
replay for live inference. Use its six exercises and facilitator notes first.

Next use [Build a Cog with saved progress](https://github.com/cogcloud-ai/cog-workbench/blob/cea6606833679a180a75dc42543c882644f72608/docs/tool-suite.md)
in Studio for a small pure-code brief. Accept the contract, inspect candidate
source/test observations/review, and separately accept or reject the final package.
Explain round/model-turn budgets before starting; these are invocation caps, not
price estimates. Show restoration after reload and terminal rejection/exhaustion.

Advanced exercises:

- Change the brief's acceptance requirement, then find where contract acceptance
  is bound into Author, packaging, verification and final acceptance. Explain
  why changing a review cannot change the accepted contract.
- Use a deliberately failing authored fixture with the model-free cycle test.
  From an actual saved build, compare both candidate directories and reviews
  (the automated cycle test cleans its temporary run on exit); identify the scoped revision
  receipt and the unchanged contract digest.
- Interrupt a model-free build and resume it. Run the documented model-free interruption fixture in the Builder guide.
  Identify which passed steps were
  reused and which cost reservations survived; explain why a failed Gate retries.
- Follow Designer's public `design-handoff prepare` example. Inspect its stable
  missing IDs and `build_origin`; supply documents from actual accepted child Tracks to finalize
  the Op. Finalize correlates supplied hash receipts; it does not read a terminal
  Track or authenticate a reviewer. Try a rejected decision or wrong proposal ID and explain the refusal. Editing
  only a decision verdict is undetected; explain why these receipts do not
  authenticate a reviewer.
- Replay the decision Cog's saved envelope using `pixi run replay -- --bundle
  BUNDLE --result ENVELOPE`. Use Smith's documented `export-fixtures` task for a
  real decision step after checking all inputs/results for sensitive information.
  Make an ignored practice copy of the decision Cog first, excluding `.pixi`,
  `var`, `runs`, `.op-composition.json`, `model.json` and binding records. Export
  into that copy so learning does not modify the pinned package or invalidate
  active bindings. Do not commit or publish exported personal inputs.
  `replay` re-decides from the supplied result; it does not verify the envelope
  belongs to the bundle. Pair them explicitly, then try a mismatched pair and
  explain why this differs from the tutorial hash-bound `fixture` task.
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

Initial implementation verification: the combined suite and a fresh public checkout each passed 1,334
model-free tests (including the documented skips), plus nine workspace safeguard
tests. The fresh checkout passed strict pin/cleanliness and boundary checks.
The added native connected handoff passed separately; the final qualification
timeout clarification passed in both subscription copies; shared Turn Harness
skips subscription-only tests by design. Supervisor termination runs in all three.
Initial implementation CI passed on Linux and macOS, including real Linux Docker checks.
The review-fix Docker regressions passed on Linux at Verifier d7345d9;
Round-one final integration CI at `1622260` passed Linux and macOS
(1,365 tests plus nine safeguards). This records that earlier head; new review
changes require fresh verification and CI.

## Review follow-up

Review fixes preserve repeated decision flags, enforce cycle-child ownership,
reconcile reservations with child attempts, retain terminal exhaustion and paused
status on refusal, and preserve verification policies in every repair/evidence
phase. Studio binds decisions to the displayed run/step/artifact and refuses a
changed provider revision. Activation validates state before admission and emits
commands selecting the actual Workbench manifest/state. The fingerprint upgrade
requires explicit re-admission and consumer reactivation.

Author retains original supplied materials/feedback and permits unrelated
warning findings; error findings outside immutable repair paths still refuse.
A new build with a reviewed wider scope is required. Criterion IDs guide the
model; file scope and the accepted contract are the mechanical constraints.
Evidence rounds currently repeat the planner question; model variation is their
only source of a different plan. These limitations are stated in the Builder guide.

Qualification reserves output before turns, checks the current behavior digest,
covers all shared sources and README hashes, tests the opt-in CLI boundary, and
uses a deterministic local process timeout. Moving requested-model aliases and
actual model identity remain unverified. No credentialed live inference is run.
Docker tests plant a host-only secret, inspect non-root/cgroup limits, exercise a
0600 input-file mount, and check container removal after timeout. Raw bounded
output is retained in execution observations, check records and the returned
test payload; evidence references its record and repeats bounded stdout/stderr
excerpts per linked criterion for repair review.

First review verification (at `1622260`): the working suite and a clean public checkout passed
full model-free verification; the clean run reports 1,364 tests. After the final
reservation-cost regression, the fresh Smith suite passed 697 tests, the native
Builder passed 18, the tutorial passed all checks and 13 tests, and the Studio
restore regression passed. Nine workspace safeguard tests and strict clean/pin
boundary checks passed. All six modified Cog packages passed Smith checking
with tests. The connected native repair/finalization check passed on those pins.
Linux CI passed the new Docker secret, limits, input-mount and removal checks.

## Second review follow-up

Chained revisions keep the original materials once and replace the superseded
review. Original feedback/materials and criterion IDs remain advisory. Unknown
out-of-scope severities fail closed. Verification restores bounded failure
diagnostics and effective timeouts in review evidence. Docker cleanup checks
actual container absence; its base tag is resolved anew for each CI build.

Cycle machinery 0.9.2 reconciles interrupted status, makes completion with
warnings successful, preserves finished transition Tracks at attempt exhaustion,
and supports declared terminal error codes. The builder stops out-of-scope
revision refusals with a visible reason. Native tests cover evidence-only rounds,
interruption recovery and mid-repair cost exhaustion.

Workbench retains the original binding before child invocation, can revoke
legacy-digest records, reports exact activation commands and explains why a
changed provider package requires a new build. Qualification verifies record
checksums/revocation, removes interrupted reports, distinguishes preflight from
started checks and checks actual supervisor child-process termination.

Component CI preview refs may pin an earlier API snapshot. Final combined
compatibility is established by this coordinator's published pins and fresh
strict verification, rather than by component CI alone.

Second review verification: a clean public checkout at `ec32ca4` passed all
1391 reported model-free tests (including documented skips), tutorial
checks and the connected native repair/finalization handoff. Smith reports 699,
Author 35, Builder 22, Workbench 97, and each provider 119 tests. Nine workspace
safeguard tests and strict clean/pin/boundary checks passed; the inventory remains
40 recorded occurrences. All six changed Cog packages passed Smith checks with
tests and no findings. Verifier Linux and macOS CI passed at `2540bf9`, with all
eight Verifier tests ran unskipped on Linux, including the one real-container
test (secret exclusion, limits, input mount and container absence). Integration
CI at `ec32ca4` and `5058cea` (these pins) passed on Linux and macOS: 1,391 tests
plus nine safeguards. The component PR heads in that review round passed on
both platforms. No paid inference or PR merges.

## Third review follow-up

Op machinery 0.9.3 clears a recoverable failure reason before retrying; successful
paused/completed summaries no longer show an old error. Smith tests cover both
recovery and terminal error codes wrapped by a nonzero process failure. Builder
and tutorial copies remain byte-identical to those masters.

Workbench keeps native steps, Gates and evidence readable when an admission
receipt is lost, reports a separate binding problem and disables continuation.
It checks a returned cycle's original input identity and refuses unsupported
legacy continuation. The linked saved-build guide now includes recovery guidance.

Verification excerpts include truncation flags and retained character counts;
a Verifier-owned test packages and executes a genuinely failing candidate and
checks its diagnostics in review evidence. Output is also retained in check
records and payloads, and excerpts repeat per criterion. Designer tests carry
the public example through finalization with synthetic matching receipts and
check structured CLI errors for invalid package paths.

Qualification handles SIGTERM as well as SIGINT, terminates its supervised
process group on interruption, removes incomplete output and tests actual signal
cleanup with child processes. It cannot refund already spent inference or run
cleanup after SIGKILL/power loss. Tests distinguish a wrong-model preflight
failure from a failure after the first check. Readiness matrices remain dated
records rather than qualifications of newer installed CLI versions.

Third review verification: a clean public checkout at `f540140` passed 1405
reported model-free tests with documented skips, plus tutorial package checks
and connected native repair/finalization. Nine workspace safeguards and strict
clean/pin/boundary checks passed; the inventory remains 40 recorded occurrences.
Smith reports 701 tests, Designer 19, Verifier 9, Builder 22, Workbench 100, and
each provider 121. Changed Designer/Verifier packages pass Smith checking with
tests; the builder passes declaration/machinery checks. Custom provider package
checks pass with the expected warning that Smith machinery validation is skipped.
Verifier CI at `2a2b635` passed on Linux and macOS; all nine tests ran unskipped
on Linux, including the single real-container confinement test. The prior
combined CI result is recorded above at its exact commits; consult GitHub checks
for newer CI results. No paid inference or PR merges.

The Workbench pin and the saved-build guide link were then moved to `cea6606`,
which compares the saved input identity after resolving filesystem aliases.
That change is limited to one condition and its two tests; the counts above
describe the earlier commits named there.

## Merge reconciliation verification

A clean public checkout at `8a672b3` passed full strict verification, including
the 102-test Workbench suite, connected native repair/finalization and the
13-test Opportunity Shortlist tutorial. Nine workspace safeguard tests also
passed. The static boundary inventory remains 40 recorded occurrences with no
new exceptions. Verifier #3 then merged at `22d1367`; its tree is identical to
the verified `2a2b635` source, and the manifest now pins that actual merge.
Workbench #6 preserves the exact reviewed #5 source, includes main as an
ancestor, and passed Linux/macOS CI. It has now merged at `fc9bb85`; the pinned
merge tree is byte-identical to the verified source. No merges were performed
by the coding agent during this reconciliation.
