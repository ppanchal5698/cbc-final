#!/usr/bin/env bash
# Render LiteLLM config with optional soft max_budget, then start the proxy.
set -euo pipefail
SRC="${LITELLM_CONFIG_SRC:-/app/config.yaml}"
OUT="${LITELLM_CONFIG_OUT:-/tmp/litellm.config.yaml}"
python3 - "$SRC" "$OUT" <<'PY'
import os
import pathlib
import sys

src, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
text = src.read_text(encoding="utf-8")
budget = os.environ.get("LITELLM_MAX_BUDGET", "").strip()
if budget:
    float(budget)  # validate
    needle = "litellm_settings:\n"
    if needle not in text:
        raise SystemExit("litellm_settings block missing from config")
    block = text.split("litellm_settings:", 1)[1].split("\n\n", 1)[0]
    if "max_budget:" not in block:
        text = text.replace(
            needle,
            f"{needle}  # Soft USD budget (gateway). Complement to WORKER_MAX_COST_USD_PER_DAY.\n"
            f"  max_budget: {budget}\n",
            1,
        )
out.write_text(text, encoding="utf-8")
print(f"wrote {out} (max_budget={'set' if budget else 'unlimited'})")
PY
exec litellm --config "$OUT" --port "${PORT:-4000}"
