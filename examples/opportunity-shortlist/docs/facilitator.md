# Facilitator guide

## Prepare before the session

Use a fresh public builder workspace on a supported platform. Install the locked
environments and run `pixi run setup`, `pixi run check`, and `pixi run test` in
the learning example. No live provider is needed for the main session.

Keep the single request, fit task logic, Op specification and a Track open in an
editor. Test both profiles. Start a fresh run during the session so your earlier
validation decision is not confused with a participant's choice.

Explain the offline label immediately: “These are invented answers for invented
opportunities. We are learning how workers, policy and decisions connect. Later
we can replace the supplied answers with a model.” Do not describe the fixtures
as actual Jev results or measured probabilities.

## A 15-minute demo

| Time | Action | Point to make |
|---|---|---|
| 0–2 min | Show the three opportunities and the company profile | Start with the useful outcome. |
| 2–5 min | Run `pixi run single`, then the strict single request | One bounded worker; judgment versus policy. |
| 5–8 min | Show `op/op.yaml`, run `pixi run start` | Same fit Cog, now repeated and composed with code workers. |
| 8–11 min | Read the shortlist, let someone choose, use `decide` | A recommendation is separate from authority to proceed. |
| 11–13 min | Show the completed Track | Inputs, worker results and the human choice remain inspectable. |
| 13–15 min | Start another run, then `status` and `resume` | A pause survives reopening; no implicit approval. |

Ask participants to predict results before revealing them. Use plain terms first:
“worker,” “workflow,” “choice,” and “execution record.” Introduce Cog, Op, Gate
and Track as the names for things participants have already seen.

## A 45-minute workshop

Spend 10 minutes on the demo, 30 minutes on the six core
[exercises](exercises.md), and 5 minutes discussing where a worker boundary would
help in their own work. Offer the optional card-Cog exercise as a follow-up.

Participants should run their own examples. If several people share a checkout,
use `--run PATH` to select their run explicitly; the default “latest” pointer
belongs to that checkout, not to a user session. Give each learner a separate
checkout for independent edits.

## Success criteria

By the end, a participant should be able to:

- Run one Cog and identify its input and output.
- Change a threshold and explain the difference from changing the evidence.
- Find where the Op passes data between workers.
- Approve or reject proposed opportunities explicitly.
- Recover a pending choice after reopening the terminal.
- Locate a named error and show that later work was not performed.

Record where people need help and whether the error names the next useful action.
These observations are more informative than a presenter completing the demo.

## Introducing live inference

Only after the offline exercise, follow [live setup](live.md) on your own
account. Use the same fictional inputs. Explain that live judgments may differ
from the teaching fixtures. The synthetic thresholds were chosen for illustration;
this workshop does not calibrate them for a provider or establish decision accuracy.

## Relating this to a larger application

After the small example, discuss how listing real opportunities, retrieving
documents, checking compliance, and drafting volumes could each add workers.
Human review should remain explicit before consequential actions. An MCP tool
server packaged for distribution is a different interface from a Cog used as
an Op step. This example teaches the latter and has no private workspace dependency.
