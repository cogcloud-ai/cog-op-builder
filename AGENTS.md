# Public builder workspace

This repository coordinates the public builder suite. Read CONTRIBUTING.md,
docs/getting-started.md, and docs/workspace-boundary.md before changing it.

- repositories.json defines the supported sibling repositories and release pins.
- Required source, fixtures, examples, and instructions must be committed to a
  public suite repository or supplied by a declared, publicly obtainable dependency.
- Private lab history may inform a change, but is not a build prerequisite or
  contributor instruction source. Bring necessary context into public docs.
- Never depend on a maintainer's absolute paths, private planning files, ignored
  run artifacts, installed bindings, or undeclared sibling checkouts.
- Do not copy credentials or private inputs into this workspace.
- Use scripts/check_workspace.py and scripts/verify.py for development checks.
  Release verification uses --strict in a fresh workspace.
- Existing exceptions are a cleanup inventory, not permission to introduce more.
  Do not regenerate the exception ledger to make a failing check pass. Explain
  any individually reviewed exception and remove it when its reference is fixed.
- Component repositories keep their own contributor instructions. Make changes
  on a branch in the owning repository; update suite pins after publication.
