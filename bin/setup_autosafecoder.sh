#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
python3.10 -m venv envs/autosafecoder
envs/autosafecoder/bin/python -m pip install -r config/autosafecoder/requirements.resolved.txt
envs/autosafecoder/bin/python -m pip check
