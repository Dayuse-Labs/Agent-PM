# faq-agent — portable OCI image (same image for Cloud Run / k8s / Railway, zero lock-in).
# BUILD CONTEXT = AgentB2C repo root — S3 vendors dayuse_agent_common from libs/ here, same
# layout as the fleet images.
#   docker build -f agents/faq_agent/Dockerfile -t faq-agent .
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY agents/faq_agent/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY agents/faq_agent/ /app/

ENV PORT=8102
EXPOSE 8102
RUN useradd --create-home --uid 10001 appuser
USER appuser
# --host :: — dual-stack bind required by Railway's IPv6 private network (fleet precedent).
# A2A_BEARER_TOKEN has no default on purpose: serve.py fails closed without it (D7).
CMD ["sh", "-c", "uvicorn faq_agent.serve:app --host :: --port ${PORT}"]
