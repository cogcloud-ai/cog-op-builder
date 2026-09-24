# Keep the public suite self-contained

Use a dedicated directory containing this repository and only the components
listed in repositories.json. Preserve any existing research workspace separately.
Fresh HTTPS clones avoid inheriting unpublished commits, local Git object
alternates, bindings, and working files from that workspace.

Required code, fixtures, examples, and documentation belong in public suite
repositories or declared publicly obtainable dependencies. Relative paths to
manifest-listed siblings are supported. Private lab notes can inform work;
necessary information must be adapted into public documentation before a change
is considered complete. Credentials and provider logins remain local configuration.

## Development

Bootstrap preserves existing checkouts. Components initially use detached HEADs
at the published pins. Before editing a component, create a branch in that
component. Make related changes in their owning repositories, publish them through
the normal review process, then update repositories.json to published commits.
Do not substitute unpushed local commits for reproducible release pins.

```sh
python3 cog-op-builder/scripts/check_workspace.py
python3 cog-op-builder/scripts/verify.py
```

The scan includes tracked files and non-ignored untracked files across every
component. It detects machine-specific home paths, undeclared Cog/Op sibling
references, missing or escaping inline Markdown links, escaping or broken
symlinks, and missing or escaping TOML path dependencies. It skips binary files,
ignored local state, and the exception ledger itself. It does not parse every
programming language or prove that dynamically constructed paths are portable.
Reference-style Markdown links and remote URLs require review separately.
Fresh-checkout tests complement the static scan.

## Reproducible verification

In a fresh directory, clone the public suite and run:

```sh
python3 cog-op-builder/scripts/bootstrap.py --strict --install
python3 cog-op-builder/scripts/verify.py --strict
```

Strict mode rejects dirty repositories (including non-ignored untracked files)
and component HEADs that differ from the manifest. Bootstrap checks existing
repositories before installing environments; it never resets or deletes them.
The coordinating repository is checked for cleanliness but is not self-pinned:
CI verifies the checked-out suite commit. CI runs these commands on Linux and macOS
using only public checkouts and locked environments, without paid model calls.

## Existing reference inventory

workspace-exceptions.json records exact file/reference pairs and occurrence
counts in the published component revisions. New occurrences fail the scan;
removed occurrences require removing the corresponding exceptions. These entries
are known limitations, not a claim that every documented path works independently.

The remaining exceptions identify explicitly illustrative package/output paths
and synthetic test data. No private packages are required or excepted. Remove
resolved entries when updating the pins; do not add exceptions for private paths.

`cog-qwen` is a public model provider in the manifest. Its weights are an explicit,
checksum-verified download from the official public model repository; credentials
and admitted bindings are local runtime configuration, never committed content.
