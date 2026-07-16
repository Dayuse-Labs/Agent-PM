#!/usr/bin/env bash
# Dayuse static guardrail — fails if the code introduces a forbidden dependency.
# Copied from dayuse-agent-fleet/scripts/dayuse_guardrails.sh; single adaptation:
# exclude vendored deps (.venv*) and .git — site-packages of google-adk/litellm
# legitimately contain vertexai imports and must not trip the check.
# Run in CI + locally (pre-commit hook, see .githooks/).
set -euo pipefail
root="${1:-.}"
fail=0

excludes=(--exclude-dir='.venv*' --exclude-dir='.git' --exclude-dir='__pycache__')

# 1) gcp_agent_identity imported outside the get_identity_provider factory
if grep -rn --include='*.py' "${excludes[@]}" 'gcp_agent_identity' "$root" \
   | grep -v 'provider.py' | grep -v 'gcp_agent_identity.py'; then
  echo "ERROR: hard GCP dependency detected (gcp_agent_identity outside factory)."; fail=1
fi

# 2) cloud model SDK imported hardcoded instead of LiteLLM
if grep -rn --include='*.py' "${excludes[@]}" -E 'import vertexai|from vertexai|import boto3.*bedrock' "$root"; then
  echo "ERROR: hardcoded cloud model SDK — use LiteLLM instead."; fail=1
fi

# 3) the code must use LiteLlm
if ! grep -rqn --include='*.py' "${excludes[@]}" 'LiteLlm' "$root"; then
  echo "WARNING: no LiteLlm usage found — check the model provider."
fi

[ "$fail" -eq 0 ] && echo "Dayuse guardrails: OK"
exit "$fail"
