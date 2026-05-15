#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 固定 venv Python 路径（不依赖 PATH 中的 python3）
VENV_PYTHON="$SCRIPT_DIR/venv/bin/python3"
if [ ! -x "$VENV_PYTHON" ]; then
    echo "错误: 未找到 venv Python ($VENV_PYTHON)，请先运行 ./install.sh" >&2
    exit 1
fi

# UTF-8 输出 + 无缓冲执行（保证后台日志实时可见）
export PYTHONUNBUFFERED=1
export PYTHONIOENCODING=UTF-8

# 运行 CLI
PYTHONPATH="$SCRIPT_DIR/src" "$VENV_PYTHON" -u -m mini_note.cli "$@"
