#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
python3.10 -m venv envs/indict
envs/indict/bin/python -m pip install -r config/indict/requirements.resolved.txt
envs/indict/bin/python -m pip check
