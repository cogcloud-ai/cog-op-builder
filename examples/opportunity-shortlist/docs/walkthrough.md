# Walkthrough: from one Cog to a workflow

Allow about 20 minutes. Run commands from `examples/opportunity-shortlist` after
following the [setup](../README.md#start-in-five-commands).

## 1. Meet one worker

Open [the single request](../examples/single.json). It contains one opportunity,
a company profile, and two policy thresholds. No provider is selected by that input.

```sh
pixi run single
pixi run single -- --json
```

The first command presents the recommendation. The second shows the full envelope:

- `payload.decision`: the recommendation, score and explanation.
- `payload.answers`: the two typed judgments supplied by the synthetic fixture.
- `payload.answered_by.model`: `synthetic-teaching-fixture-not-a-model`.
- `binding.provider_called`: `false`, with `fixture_source: hand-authored-synthetic`.
- `problems`: in-package contract findings. A valid answer is still not approval.

Read [the Cog's work contract](../fit/COG.md). The Cog answers a bounded fit
question; it does not pursue an opportunity or make your decision for you.

## 2. Separate judgment from policy

Two questions ask whether the stated capabilities match the work and whether
the company can deliver it. In a live run, an admitted model supplies the answers.
In this walkthrough, they are illustrative values authored for teaching.

[The decision code](../fit/src/task_logic.py) takes the **lower** value as the
score. It recommends `pursue` at or above `pursue_at`, `review` at or above
`review_at`, and `pass` below both. These are visible rules, not hidden model policy.

```sh
pixi run single -- --request examples/single-strict.json
```

The answer values stay **0.92** and **0.88**. Raising `pursue_at` from **0.75**
to **0.95** changes the recommendation from `pursue` to `review`. The model
judgment did not change. Only your policy changed.

To inspect what a live model would actually receive:

```sh
cd fit
pixi run prepare -- --bundle examples/sample-bundle.json
cd ..
```

The turn contains the opportunity, company and questions. Policy thresholds
are deliberately withheld from the model.

## 3. Add the other workers

Open [the Op](../op/op.yaml) and [the full request](../examples/request.json).
The Op specifies three steps:

1. `prepare` validates ids, required data and threshold order.
2. `fit` runs once per opportunity through `foreach`.
3. `shortlist` joins by opportunity id, ranks results, and proposes the pursue/review items.

`depends_on` states the dependencies. `$from` maps an input or an earlier result
into a worker's request. `foreach` passes one opportunity at a time to the same
fit Cog you already used. This Op has no custom workflow Python.

```sh
pixi run start -- --dry-run
pixi run start
```

The dry run validates the input shapes and resolves a plan without calling Cogs.
The real run pauses after ranking. It records all three fit results, but only
`OPP-001` and `OPP-002` are proposed for a human choice. `pass` items remain visible
in the ranking; this policy does not offer them for approval.

## 4. Make the human choice

Read the printed `pending/shortlist.md`. You can investigate the dashboard,
investigate the security-audit portal, both, or neither. The example below is
one possible decision, not a default imposed by the tool:

```sh
pixi run decide -- --approve OPP-001 --reject-rest --by learner
```

The helper copies the exact pending payload digest into a decision document,
records who you say decided and when, and asks the shared runtime to resume.
The runtime validates the decision and saves it. An old decision cannot approve
changed pending content. The result is an approved list, not an external action.

## 5. Follow the evidence

```sh
pixi run status
```

Open the `track.json` path printed by the command. Find:

- `input_request`: the run's saved original request.
- `steps`: each worker's status, mapped request, envelope and code fingerprint.
- `steps[1].elements`: one fit invocation per opportunity, in input order.
- `steps[2].decision`: the human decision and its recorded document.
- `resumes`: the saved history of continuing the run.
- `outputs.approved`: the selected change objects; `outputs.rejected`: rejected ids.

A Cog reports its result and contract findings. The Op's Gate decides how those
findings affect progression. The shortlist recommendation and the human decision
are distinct records. This example declares no independent Guards.

## 6. Close the terminal and return

Start another run and leave it paused:

```sh
pixi run start
```

Close your terminal, open a new one, return to the example directory, then run:

```sh
pixi run status
pixi run resume
```

The pending choice is still there. `resume` without a decision remains paused;
it does not approve anything. Use `decide` to finish. To inspect an older run,
pass `--run` followed by its directory to `status`, `resume` or `decide`.

## 7. Try a failure

```sh
pixi run start -- --request examples/request-duplicate.json
```

Preparation refuses the repeated id. The fit and shortlist steps are
`not-reached`. Inspect the Track and the prepare envelope. Run the valid request
to start a new, independent run:

```sh
pixi run start -- --request examples/request.json
```

If you edit an opportunity, company profile or question in offline mode, a saved
answer for the old question is refused. Use a supplied matching example, explicitly
author new synthetic fixtures, or use [live mode](live.md). Editing a threshold
can reuse the answers because thresholds do not change the question.
