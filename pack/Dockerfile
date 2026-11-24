# Build the unmodified Hub image from sources.json first. This extension carries
# the public suite and one model-free usage entry point on the Hub worker seam.
ARG HUB_IMAGE=collab-builder/hub:eab8189
FROM ${HUB_IMAGE} AS suite
USER root
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
ENV PIXI_HOME=/root/.pixi PIXI_CACHE_DIR=/root/.cache/pixi
ARG SUITE_REVISION=d6beeba96ffb0767e0f3574a676c94267ee30ba1
WORKDIR /opt/builder-suite
RUN git clone https://github.com/cogcloud-ai/cog-op-builder.git \
    && git -C cog-op-builder checkout --detach ${SUITE_REVISION} \
    && python cog-op-builder/scripts/bootstrap.py --strict --install
# Provider supervisor tests inspect child process state with ps.
RUN apt-get update && apt-get install -y --no-install-recommends procps \
    && rm -rf /var/lib/apt/lists/*
RUN python cog-op-builder/scripts/verify.py --strict
RUN for repository in /opt/builder-suite/*; do \
      git -C "$repository" clean -fdx -e .pixi; \
    done \
    && python cog-op-builder/scripts/check_workspace.py --strict

FROM ${HUB_IMAGE}
USER root
COPY --from=suite --chown=1000:1000 /opt/builder-suite /opt/builder-suite
COPY --chown=1000:1000 worker /opt/collab-hub/cogs/builder-smoke
COPY sources.json /opt/collab-hub/cogs/builder-smoke/sources.json
COPY proof.py /opt/builder-pack/proof.py
COPY check_image.py /opt/builder-pack/check_image.py
ENV PYTHONPATH=/opt/collab-hub/worker/src \
    PIXI_HOME=/opt/builder-pixi-config \
    PIXI_CACHE_DIR=/tmp/builder-pixi-cache
USER 1000:1000
RUN pixi install --locked --manifest-path /opt/collab-hub/cogs/builder-smoke/pixi.toml
