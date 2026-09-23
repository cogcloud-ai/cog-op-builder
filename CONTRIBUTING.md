# Contributing

Read [the repository guide](docs/repositories.md), use the documented
[setup and verification](docs/getting-started.md), and open focused PRs with
behavior changes and test evidence. Implementation issues live in their owning
repositories; suite-wide issues link the component work. Contributions to this
repository are under Apache-2.0. Preserve component and third-party notices.

Never commit credentials, installed binding records, private inputs, or raw
provider execution records. Fix shared machinery upstream in Smith and vendor
it byte-identically. CI must not require paid model calls or user credentials.
