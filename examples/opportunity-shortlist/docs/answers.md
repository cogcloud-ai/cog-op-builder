# Exercise answers

These are expected outcomes for the committed synthetic fixtures. Live answers
may differ; the same policy still applies.

## 1. One Cog

`payload.decision.recommendation` is `pursue`, with score **0.88**.
`payload.answers.scope_match.noul` is **0.92** and
`payload.answers.delivery_capacity.noul` is **0.88**.
`binding.provider_called` is `false`; the fixture model name explicitly says
it is not a model. `fixture_source` says `hand-authored-synthetic`.
No human Gate has run, so nothing has been approved.

## 2. Policy

The strict request raises `pursue_at` to **0.95**. The score remains **0.88**,
so the recommendation changes to `review`. The raw answers stay identical.
The decision explanation changes to reflect the new threshold. A threshold of
**0.88** still recommends `pursue`: comparisons use `>=`.

## 3. Evidence

For the construction company, the dashboard is `pass`, score **0.08**.
The bridge ranks first, `pursue`, score **0.94**. The Op proposes only `OPP-003`.
A changed company profile produces a different prepared question, so the old
fixture cannot answer it. The supplied alternate profile has its own explicitly
authored fixtures. Offline mode demonstrates mechanics; it does not predict
what a live model would think of an arbitrary edit.

## 4. Human authority

Approving `OPP-002` produces an approved list containing that opportunity and
rejects `OPP-001`. The ranked recommendations still show `OPP-001` first.
`--reject-all` produces an empty approved list and completes the run with both
proposals rejected. This is a per-opportunity Gate, not rejection of the whole Op.

## 5. Recovery

The Track remains `paused` after a terminal restart and after `resume` without
a decision. After an explicit decision, it becomes `completed`. Passed prepare
and fit invocation paths and attempt records are reused. A decision is copied
into the run's `decisions/` directory and a resume entry is recorded.

## 6. Refusal

The finding is `duplicate-opportunity` at `prepare`. `fit` and `shortlist` are
`not-reached`. Using a valid request starts a new run with a different id.
An interrupted or paused run can be resumed; changing the input is a new run.

## Optional card Cog

The input schema can use the `opportunity` property from
[the fit input schema](../fit/context/input-schema.json). Require `opportunity`
and reject additional properties. The output schema requires `id` and `card`,
both nonempty strings, and rejects additional properties.

A minimal author-owned implementation:

```python
def check_input(bundle):
    return []


def run(bundle, grant, journal):
    item = bundle['opportunity']
    return {'id': item['id'],
            'card': item['title'] + ': ' + item['description']}, []


def check_output(payload, bundle):
    import cog_core
    expected, _ = run(bundle, None, None)
    if payload != expected:
        return [cog_core.problem('card-grounding',
                                 'Card must preserve the supplied id and text.')]
    return []
```

Test that the exact id, title and description are preserved; an absent description
is refused by the schema; and a wrong output id is caught by the contract check.
Replace the generated starter tests that assume an `items` array.

The extended Op step can be:

```yaml
- id: card
  name: Make readable opportunity cards
  depends_on: [prepare]
  cog:
    id: openteams/card
    version: "0.1.0"
    source: ../card
    task: run
  foreach:
    items: {$from: steps.prepare.payload.opportunities}
    as: opportunity
  input:
    opportunity: {$from: opportunity}
  expected_outcome: One grounded readable card per opportunity.
  gate:
    policy: envelope-ok-no-error-problems
    guards: []
  on_fail: stop
```

Include the new step in the `steps` array, use the actual Cog identity from its
manifest, and add the `cards` output mapping. The original fit and shortlist
steps remain responsible for judgments and the human choice.
