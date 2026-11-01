#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
RUNTIME_DIR="$PROJECT_ROOT/runtime/autosafecoder"
mkdir -p "$RUNTIME_DIR"/{tmp,cache,hf}
export TMPDIR="$RUNTIME_DIR/tmp" TMP="$RUNTIME_DIR/tmp" TEMP="$RUNTIME_DIR/tmp" XDG_CACHE_HOME="$RUNTIME_DIR/cache" HF_HOME="$RUNTIME_DIR/hf"
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CUDA_VISIBLE_DEVICES=""
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
exec "$PROJECT_ROOT/envs/autosafecoder/bin/python" -B "$PROJECT_ROOT/services/autosafecoder/cli.py" "$@"
