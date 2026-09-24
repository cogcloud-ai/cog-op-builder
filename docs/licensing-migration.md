# Apache 2.0 migration — 2026-09-22

OpenTeams authorized Apache-2.0 for the Cog / Op Builder suite and its
maintained components. Copyright remains with OpenTeams; this change does
not withdraw permissions granted for previously published BSD versions.
External dependencies, vendor services, and separately licensed material
retain their applicable terms.

## Published components

The following isolated licensing commits update license text, package
metadata, and documentation without publishing unrelated local development:

- [cog-author](https://github.com/cogcloud-ai/cog-author/commit/8ef747bf239c009a0ea6686ceb1f8cd73336be94)
- [cog-build-evaluator](https://github.com/cogcloud-ai/cog-build-evaluator/commit/ce767f51ba9d463ecd6232cc0d996a64f0c32655)
- [cog-chatgpt](https://github.com/cogcloud-ai/cog-chatgpt/commit/7b46b6f2491f3956afdf6de9ba0d311cbf0f645c)
- [cog-claude](https://github.com/cogcloud-ai/cog-claude/commit/db5d598a6895785706fa4d823e9b2d2ad3c3c138)
- [cog-op-designer](https://github.com/cogcloud-ai/cog-op-designer/commit/ebdc2f976033346d7e822d87d8bd113e2067e72a)
- [cog-openrouter](https://github.com/cogcloud-ai/cog-openrouter/commit/55957a4dff105d681fcaf9bb39f777a5573fa105)
- [cog-smith](https://github.com/cogcloud-ai/cog-smith/commit/66c446762db41e0a25bba1c3a8c287b9fa35b4c3)
- [cog-turn-harness](https://github.com/cogcloud-ai/cog-turn-harness/commit/d5af99bc44e981a737e5007ccfbbb7f31610a0c1)
- [cog-workbench](https://github.com/cogcloud-ai/cog-workbench/commit/f477af34de7caa6dd035f7199a41f6fd3fa8b822)

The suite repository itself already carries Apache-2.0.

## Local packages awaiting publication

Apache-2.0 license text, metadata, and documentation are also present locally
in `cog-build-candidate`, `cog-verify-candidate`, `op-cog-builder`, and
`op-builder-smoke`. These packages do not yet have their own GitHub repositories.
Generated reference candidates and historical run artifacts were preserved.
Repositories outside the suite were outside this migration's scope.

## Generated packages

Smith defaults new Cog metadata to Apache-2.0. Caller-selected licenses remain
supported for independently authored material. New packages include
`LICENSE.smith`, `NOTICE.smith`, and `LICENSING.md` identifying the license of
Smith-supplied source, templates, and machinery. Authors must include the
applicable license text for their own additions. No machinery source bytes
or machinery versions changed in this migration.

## Verification and operational impact

- Local Smith: 582 existing tests passed, plus two new licensing tests.
- Published Smith baseline: all 274 tests passed, including licensing tests.
- Changed TOML files parsed successfully; whitespace checks passed.
- Each published commit was verified against its remote branch.

Licensing and metadata changes affect package fingerprints. Existing pinned
provider bindings and activated compositions may need renewed admission and
activation. Historical evidence continues to describe the exact earlier
packages; it should not be rewritten to match the newly licensed versions.

## Publication update (2026-09-23)

The four packages listed above now have repositories and are included in the
public preview. The preserved merge candidate is also published as a runnable
example, with Apache-2.0 text matching its original manifest declaration.
See the [current repository guide](repositories.md) and [component manifest](../repositories.json).
