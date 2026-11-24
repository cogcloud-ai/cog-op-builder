#!/usr/bin/env bash
set -euo pipefail

pack_dir=$(cd "$(dirname "$0")" && pwd)
build_dir=$(mktemp -d)
trap 'rm -rf "$build_dir"' EXIT
hub_url=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["hub"]["url"])' "$pack_dir/sources.json")
hub_revision=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["hub"]["revision"])' "$pack_dir/sources.json")
suite_revision=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["suite"]["revision"])' "$pack_dir/sources.json")
hub_image="${HUB_IMAGE:-collab-builder/hub:$hub_revision}"
builder_image="${BUILDER_IMAGE:-collab-builder/worker:step1}"

git clone "$hub_url" "$build_dir/hub"
git -C "$build_dir/hub" checkout --detach "$hub_revision"
docker buildx build --load --network="${BUILD_NETWORK:-default}" \
    --build-context "projectroot=$build_dir/hub" \
    -f "$build_dir/hub/api/Dockerfile" -t "$hub_image" "$build_dir/hub/api"
docker build --network="${BUILD_NETWORK:-default}" \
    --build-arg "HUB_IMAGE=$hub_image" --build-arg "SUITE_REVISION=$suite_revision" \
    -f "$pack_dir/Dockerfile" -t "$builder_image" "$pack_dir"
docker run --rm --network=none --entrypoint python "$builder_image" /opt/builder-pack/check_image.py
