# Builder pack for Collab Hub

This first slice packages the public Builder suite into a Linux image and exposes
the existing `op-builder-smoke` workflow through Collab Hub's worker SDK. Hub owns
the authenticated run API, controller, worker placement and PostgreSQL Track.
The published Builder Op owns its two word-tally invocations and native Track.
The adapter returns all native JSON evidence to the Hub before its worker exits.

`sources.json` pins the public suite coordinator, Hub source and platform charts.
The suite's own `repositories.json` pins all 18 components. Each component's
Pixi lock is installed during image construction. The full model-free suite runs
under strict pin checks before the final image can be produced.

## Build and check the image

Use Linux x86-64, Docker with BuildKit/buildx, Git and Python 3.11 or newer.
Run from this repository.

```sh
bash pack/build.sh
```

`BUILD_NETWORK=host` selects host networking when the build host's Docker DNS
cannot reach package registries. The script builds the unmodified pinned Hub
source, adds the pinned suite and adapter, then runs the packaged smoke Op with
networking disabled. It checks totals of 21 and 31 words, retained native evidence,
and refusal of arbitrary input. CI runs this same command.

The worker uses the upstream SDK for authentication, claims and envelopes. Its
`run` entry point takes `{}` and executes the bundled fixture. The image includes
the remaining Builder components for subsequent lifecycle integration.

## Prepare a private test cluster

Use a disposable Kubernetes cluster with a default StorageClass, Helm 3.17 or
newer, and kubectl. Set `KUBECONFIG` explicitly to that cluster. Install the
platform versions recorded in `sources.json`.

```sh
helm upgrade --install eg oci://docker.io/envoyproxy/gateway-helm \
  --version v1.9.1 -n envoy-gateway-system --create-namespace --wait
helm upgrade --install cert-manager oci://quay.io/jetstack/charts/cert-manager \
  --version v1.19.1 -n cert-manager --create-namespace \
  --set crds.enabled=true \
  --set config.apiVersion=controller.config.cert-manager.io/v1alpha1 \
  --set config.kind=ControllerConfiguration \
  --set config.enableGatewayAPI=true --wait
helm upgrade --install nebari-operator oci://quay.io/nebari/charts/nebari-operator \
  --version 0.2.0 -n nebari-operator-system --create-namespace \
  --set manager.envOverrides.KEYCLOAK_ENABLED=false \
  --set manager.envOverrides.TLS_CLUSTER_ISSUER_NAME=builder-ca --wait

python3 pack/platform.py --hostname YOUR_PRIVATE_HOSTNAME --port 8443 \
  --output hub-values.json
```

The setup creates `collab-builder-infra` and `collab-builder`, PostgreSQL and
Keycloak with persistent volumes, a private certificate authority, a TLS Keycloak
endpoint, a signed-token test client, and gateway routing. Generated credentials
stay in Kubernetes Secrets and are reused on subsequent setup runs. Preserve
Keycloak's volume with its credentials because an existing realm is retained on
restart. The generated Hub values enforce signed bearer authentication against
that realm and scope this test Hub to the `builder-test` organization.

The Nebari operator provisions Hub routing and TLS. API authentication is handled
by Hub. Gateway browser SSO is disabled for this packaging proof. Kind's default
CNI does not enforce the worker NetworkPolicies. This qualification covers the
trusted smoke fixture. Generated-code containment and interactive Builder Gates
require their later qualification steps.

## Deploy Hub and run the proof

Check out the Hub revision from `sources.json` in a separate source directory.
Load the image into the target cluster. For kind, use
`kind load docker-image collab-builder/worker:step1 --name YOUR_CLUSTER`.
The following commands expect that Hub checkout at `$HUB_SOURCE`.

```sh
helm upgrade --install collab-hub "$HUB_SOURCE/helm/collab-hub" \
  -n collab-builder -f hub-values.json --wait --timeout 5m
helm upgrade --install builder pack/chart -n collab-builder --wait --timeout 5m
kubectl -n collab-builder wait --for=condition=complete \
  job/builder-proof-1 --timeout=360s
kubectl -n collab-builder logs job/builder-proof-1
```

Each companion chart revision creates a new proof Job, so use the installed
revision's suffix on subsequent runs. The proof exchanges its client credential
for a signed token, checks that unauthenticated run listing returns 401, submits
the smoke Op to `/v1/runs`, and reads the result, payload and events back through
the authenticated API. It asserts both word totals and the native Track. Reports
are written to the `builder-evidence` PVC. Hub retains the run and payload in
PostgreSQL after its worker is removed.

For kind access, forward the generated Envoy Service's port 443 to port 8443 on
the host's private interface. Use the configured hostname for TLS and trust the
public CA certificate in the `builder-ca` ConfigMap. The private key stays in
cert-manager's namespace. No public ingress or DNS change is needed.

On macOS clients, copy that public CA certificate to `builder-ca.crt` and add
user-level SSL trust scoped to the configured hostname. Set `BUILDER_HOSTNAME`
to the same name passed to `platform.py`.

```sh
security add-trusted-cert -r trustRoot -p ssl -s "$BUILDER_HOSTNAME" \
  -k "$HOME/Library/Keychains/login.keychain-db" builder-ca.crt
```

Reload the browser after adding trust. Each client device needs its own trust
configuration. Command-line clients can use `curl --cacert builder-ca.crt`.
The health endpoint returns an empty HTTP 200 response. Hub's root requires
authentication; this first slice uses the signed API test client described above.

Use immutable image digests in the deployment after loading the built image.
Record the image digest, full source revisions, suite counts/skips, run id and
saved report for each qualification. `proof.py` and `check_image.py` are executable
checks of this first slice. Live model use, isolated generated-code verification,
browser approvals and publication remain subsequent slices.
