#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
RUNTIME_DIR="$PROJECT_ROOT/runtime/table2"
mkdir -p "$RUNTIME_DIR"/{tmp,cache}
export TMPDIR="$RUNTIME_DIR/tmp" TMP="$RUNTIME_DIR/tmp" TEMP="$RUNTIME_DIR/tmp" XDG_CACHE_HOME="$RUNTIME_DIR/cache"
export PYTHONPATH="$PROJECT_ROOT/src" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CUDA_VISIBLE_DEVICES=""
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
exec /usr/bin/python3.10 -B -m table2_baselines.cli "$@"
