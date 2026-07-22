# b2c-concierge — portable OCI image (same image for Cloud Run / k8s / Railway, zero lock-in).
# BUILD CONTEXT = AgentB2C repo root (libs/b2c_common is COPY'd in, fleet layout).
# ⚠️ requirements.txt pins dayuse-agent-common from the PRIVATE fleet repo: building this image
# needs read access to Dayuse-Labs/dayuse-agent-fleet — deploy wiring lands with S10/S11.
#   docker build -f agents/b2c_concierge/Dockerfile -t b2c-concierge .
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

# git: pip needs it to resolve the git+ pinned private dep (python:3.12-slim ships none).
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY libs/b2c_common /app/libs/b2c_common
RUN pip install --no-cache-dir /app/libs/b2c_common

# dayuse-agent-common is pinned to the PRIVATE fleet repo (git+ssh in requirements). Provide a
# read PAT via a build ARG so pip can fetch it — Railway populates FLEET_READ_TOKEN from the
# service variable of the same name; locally pass `--build-arg FLEET_READ_TOKEN=…`. Same
# insteadOf rewrite CI uses. Token scrubbed (rm /root/.gitconfig) in the SAME layer, so it never
# lands in a shipped layer (ARG values aren't persisted in the image env). set -eu → a failed
# pip aborts the build. Plain ARG only — no BuildKit secret mount (Railway's builder rejects it).
ARG FLEET_READ_TOKEN=""
COPY agents/b2c_concierge/requirements.txt /app/requirements.txt
RUN set -eu; \
    if [ -n "${FLEET_READ_TOKEN}" ]; then \
      git config --global url."https://x-access-token:${FLEET_READ_TOKEN}@github.com/".insteadOf "ssh://git@github.com/"; \
    fi; \
    pip install --no-cache-dir -r /app/requirements.txt; \
    rm -f /root/.gitconfig
COPY agents/b2c_concierge/ /app/

ENV PORT=8100
EXPOSE 8100
RUN useradd --create-home --uid 10001 appuser
USER appuser
# --host :: — dual-stack bind required by Railway's IPv6 private network (fleet precedent).
# A2A_BEARER_TOKEN has no default on purpose: serve.py fails closed without it (D7).
CMD ["sh", "-c", "uvicorn b2c_concierge.serve:app --host :: --port ${PORT}"]
