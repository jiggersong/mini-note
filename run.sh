#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 激活 venv
if [ -f venv/bin/activate ]; then
    source venv/bin/activate
fi

# 运行 CLI
PYTHONPATH="$SCRIPT_DIR/src" python3 -m mini_note.cli "$@"
