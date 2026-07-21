# Production baseline

No production result is bundled by default. A baseline must be generated from
the exact deployed commit and approved production or production-like endpoint.

```bash
python -m eval_pack.runner \
  --endpoint https://VERIFIED-ENDPOINT/v3/chat \
  --api-key "$CHAT_API_KEY" \
  --pause-ms 800 \
  --output eval_pack/baselines/current_prod.json
```

The run creates synthetic sessions prefixed with `canonical-eval-`. Exclude
that prefix from product analytics and production-conversation audits.

Record the verified deployed commit in `eval_pack/manifest.json` before sharing
the baseline. Never put the API key, database URL, cookies or raw production
logs in this directory.

Use the exact same pack archive, clock values and endpoint adapter for the
candidate run. Compare the two reports with `python -m eval_pack.compare`;
wording differences alone are not regressions, while a newly failed critical
assertion is.
