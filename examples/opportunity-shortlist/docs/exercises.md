# Exercises

Work from `examples/opportunity-shortlist`. Complete the [setup](../README.md)
first. The core exercises need no account or provider. Use your own name or
`learner` for `--by`; it is a recorded label, not an authenticated identity.

Put edited request copies under the ignored `var/` directory (`mkdir -p var`).
Use paths such as `var/my-request.json` when invoking them.

Try to predict each result before running it. [Answers](answers.md) are available
for checking your reasoning.

## 1. Explain one Cog (5 minutes)

```sh
pixi run single -- --json
```

Find the recommendation, both answer values, and the field proving no provider
was called. Explain why `pursue` does not mean an opportunity has been approved.

**Done when:** you can identify the input, the judgments, the policy decision,
and the provenance without reading the workflow.

## 2. Change policy without changing judgment (5 minutes)

```sh
pixi run single -- --request examples/single-strict.json --json
```

Compare this with Exercise 1. Which fields changed? Why is the recommendation now
`review`? Make a copy of `examples/single.json`, set `pursue_at` to **0.88**, and
run it with `pixi run single -- --request YOUR_COPY.json`. Is equality sufficient?

**Done when:** you can explain why the two judgments stay the same, and why
threshold policy belongs in code rather than in the model's instructions.

## 3. Change the evidence (5 minutes)

```sh
pixi run single -- --request examples/single-construction.json
pixi run start -- --request examples/request-construction.json
```

The opportunity in the single example is still the dashboard; the company is
now a construction cooperative. Predict the single result and which opportunity
ranks first in the Op. Finish the construction run with an explicit choice.

Then copy `examples/single.json`, add a new capability to the company, and run
the copy. Why does offline mode refuse it instead of using the earlier answer?

**Done when:** you can distinguish changed evidence from changed policy, and
explain the limits of replay fixtures.

## 4. Override the recommendation deliberately (5 minutes)

```sh
pixi run start
pixi run decide -- --approve OPP-002 --reject-rest --by learner
pixi run status
```

Which opportunity is approved now? Why can a person choose an item recommended
for `review`? Inspect the Track's ranking and its human decision separately.
Start a fresh run and use `--reject-all` instead.

**Done when:** you can show that human choice is recorded independently of the
recommendation, including the choice to pursue nothing.

## 5. Return to a paused run (5 minutes)

Start a run, close the terminal, reopen it in the example directory, and inspect
with `pixi run status`. Run `pixi run resume` without a decision. Finish with an
explicit decision. Inspect `track.json` before and after: do the passed prepare
and fit steps point to the same invocation artifacts?

**Done when:** you can show durable pause/resume and explain why a resumed
approval does not need to repeat the earlier work.

## 6. Diagnose an input mistake (5 minutes)

```sh
pixi run start -- --request examples/request-duplicate.json
```

Identify the failing step and its named finding. Did any fit invocation happen?
Make a corrected copy with unique ids from the original request and start a
new run. What should the tool tell a beginner about this mistake?

**Done when:** you can trace a refusal to the worker that produced it and show
that later steps were not reached. Run `pixi run check` and `pixi run test` to
verify the untouched reference example.

## 7. Build a small new Cog (optional, 15–20 minutes)

Create a code Cog that summarizes one opportunity as a readable card. The
bounded job is: take an `opportunity` object and return its id and a string
containing its title and description. It reaches nothing and makes no fit judgment.

From the example directory:

```sh
cd ../../../cog-smith
pixi run new -- --dir ../cog-op-builder/examples/opportunity-shortlist/practice/card --kind code --manifest yaml --yes --owner learner@example.invalid
cd ../cog-op-builder/examples/opportunity-shortlist/practice/card
pixi install
```

Replace the starter work contract, input/output schemas, sample input,
`src/task_logic.py` and tests. Leave `src/cog_core.py` and `src/cog_cli.py` intact.
Use [the answer guide](answers.md#optional-card-cog) if you need a starting point.
Run its native checks, invocation and tests:

```sh
pixi run check
pixi run run -- --bundle examples/sample-bundle.json
pixi run test
```

Return from `practice/card` to the learning example directory, then verify
the package with Smith:

```sh
cd ../..
cd ../../../cog-smith
pixi run check -- ../cog-op-builder/examples/opportunity-shortlist/practice/card --tests
cd ../cog-op-builder/examples/opportunity-shortlist
```

For an extension, create a copy of `op/` called `practice/extended-op` (copy only
source files, excluding `.pixi/`, `runs/` and caches). Update the existing source
paths to `../../prepare`, `../../fit`, and `../../shortlist`. Add a `card` step
with `source: ../card`, `task: run`, `depends_on: [prepare]`, and `foreach` over
`steps.prepare.payload.opportunities`. Map its `opportunity` input from the loop
variable. Add `cards: {$from: steps.card.payload}` to outputs. Check it with
Smith and run it with the original fictional request. Keep the human Gate.

**Done when:** a new independently tested worker can be added by editing the
Op specification without editing shared runtime code.
