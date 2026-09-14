#!/usr/bin/env bash
# Start mineru-api on the compose network. GPU-only: no CPU fallback.
set -euo pipefail

python - <<'PY'
import sys
import torch

if not torch.cuda.is_available():
    print("CUDA required: torch.cuda.is_available() is False", file=sys.stderr)
    sys.exit(1)
print(f"CUDA ok: {torch.cuda.get_device_name(0)}")
PY

MODELS_DIR="${MINERU_MODELS_DIR:-/models}"
CONFIG_JSON="${MINERU_TOOLS_CONFIG_JSON:-${MODELS_DIR}/mineru.json}"
export MINERU_TOOLS_CONFIG_JSON="${CONFIG_JSON}"
export HF_HOME="${HF_HOME:-${MODELS_DIR}/hf}"
mkdir -p "${MODELS_DIR}" "${HF_HOME}"

if [[ ! -f "${CONFIG_JSON}" ]]; then
  echo "MinerU models missing; downloading (${MINERU_MODELS:-pipeline}) from Hugging Face..."
  mineru-models-download -s huggingface -m "${MINERU_MODELS:-pipeline}"
fi

# Word-split intentional: profile env files may pass multiple API flags.
# shellcheck disable=SC2086
exec mineru-api --host 0.0.0.0 --port 8000 ${MINERU_API_EXTRA_ARGS:-}
