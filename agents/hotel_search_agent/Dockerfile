# hotel-search-agent — portable OCI image (same image for Cloud Run / k8s / Railway, zero
# lock-in). BUILD CONTEXT = AgentB2C repo root (libs/b2c_common is COPY'd in, fleet layout).
# ⚠️ requirements.txt pins dayuse-agent-common from the PRIVATE fleet repo: building this image
# needs read access to Dayuse-Labs/dayuse-agent-fleet (ssh agent forward or a token via git
# insteadOf) — the deploy wiring lands with S10/S11.
#   docker build -f agents/hotel_search_agent/Dockerfile -t hotel-search-agent .
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY libs/b2c_common /app/libs/b2c_common
RUN pip install --no-cache-dir /app/libs/b2c_common
COPY agents/hotel_search_agent/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY agents/hotel_search_agent/ /app/

ENV PORT=8101
EXPOSE 8101
RUN useradd --create-home --uid 10001 appuser
USER appuser
# --host :: — dual-stack bind required by Railway's IPv6 private network (fleet precedent).
# A2A_BEARER_TOKEN has no default on purpose: serve.py fails closed without it (D7).
CMD ["sh", "-c", "uvicorn hotel_search_agent.serve:app --host :: --port ${PORT}"]
