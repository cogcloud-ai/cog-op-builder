# Optional live mode

Finish the offline walkthrough first. Live mode uses the **same fit Cog** and
an Op with the same data flow. Only the fit usage task changes from `fixture`
to `ask-composed`. There is no automatic fallback from live inference to fixtures.

This path needs the manifest-listed `cog-workbench` and `cog-typesafe` siblings,
your own TypeSafe account and a locally configured `TYPESAFE_API_KEY`. Use your
usual secret management to put that variable in the shell environment. Never
put a key in an example request or commit it.

## Admit and activate

From `examples/opportunity-shortlist`:

```sh
cd ../../../cog-typesafe
pixi install --locked
pixi run check
# Optional: one small live qualification call, which can incur charges.
pixi run probe -- --model jev-1.13.0
cd ../cog-workbench
pixi install --locked
pixi run suite -- bind --provider cog-typesafe --request ../cog-typesafe/examples/bind-request.json
pixi run suite -- bindings
```

Read the returned admitted binding id and revision. The provider's sample requests
`binding-jev`; an existing binding can receive a later revision. Use the actual
values instead of the placeholders below:

```sh
pixi run suite -- activate-composition --context cog-op-builder/examples/opportunity-shortlist/fit --binding-id YOUR_BINDING_ID --revision YOUR_REVISION
cd ../cog-op-builder/examples/opportunity-shortlist
```

Activation writes the local, ignored `fit/.op-composition.json`. Nothing selects
a provider from opportunity data. The example's nested live adapter uses the
fixed manifest-listed Workbench host and verifies the installed composition.

## Use the live answers

```sh
pixi run single -- --live
pixi run start -- --live
pixi run status
```

If it reaches the human Gate, choose explicitly with `pixi run decide`, as in
the offline guide. The helper identifies whether the saved run used `op/` or
`op-live/`; it resumes that exact specification. `--run PATH` can select an
older run.

A live run uses cloud inference and may incur provider charges. It makes two
judgments for each of the three fictional opportunities. `pursue`, `review` and
`pass` recommendations can differ from the synthetic examples, and the set of
proposed choices can differ too. Read the actual pending review before deciding.
No message, document download or external write is performed by the Op.

## Changes and recovery

Re-activate after changing the fit package. Re-admit the provider when its binding
has become stale or revoked. Start a new run after changing inputs or the Op
specification. A source edit while a run is paused can affect recovery; inspect
the shared runtime's findings instead of treating approval as fresh execution.

The same typed interface can use a separately admitted LLM through
[cog-system-one-adapter](../../../../cog-system-one-adapter/README.md).
Follow that provider's documented binding path, then activate the fit Cog with
the resulting binding. The example itself does not substitute providers. Treat
LLM-stated probability values according to their source; neither the workshop
nor its thresholds establish calibration or reliability.

The live adapter is covered by model-free host-integration tests. No paid live
qualification is part of the example's automated verification.
