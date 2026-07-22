# widget — the agent-usa chat front, vendored (web/vendor/**) and served by the
# dev proxy (scripts/run_widget_proxy.py). This is the ONLY public service:
# browser talks to this origin, it forwards /v3/* server-side to the concierge
# over Railway's private network (no CORS, concierge stays private).
# Stdlib only — no pip install, no fleet dep, no build secret.
#   BUILD CONTEXT = AgentB2C repo root.
#   docker build -f web/Dockerfile -t b2c-widget .
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Keep the repo layout so run_widget_proxy.py auto-resolves web/vendor as its
# widget dir (it computes <script>/../web/vendor); flags below make it explicit anyway.
COPY web/vendor /app/web/vendor
COPY scripts/run_widget_proxy.py /app/scripts/run_widget_proxy.py

# Railway injects PORT. HOST=:: → dual-stack bind (fleet precedent, IPv6 private net).
# WIDGET_BACKEND points at the concierge's PRIVATE address (overridable by a Railway var).
ENV HOST=:: \
    WIDGET_BACKEND=http://concierge.railway.internal:8100

RUN useradd --create-home --uid 10001 appuser
USER appuser
EXPOSE 8090
# PORT/HOST/WIDGET_BACKEND are read from env by the script (see its main()).
CMD ["python", "-u", "scripts/run_widget_proxy.py", "--agent-usa-dir", "/app/web/vendor"]
