#!/bin/bash
set -e

# ============================================================
# mini-note 安装验证脚本
# 用法: ./verify.sh [--quick]
#   --quick  仅运行 CLI 冒烟测试，跳过完整 pytest 测试套件
# ============================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

PASS=0
FAIL=0
SKIP=0

pass() { echo -e "  ${GREEN}✓${NC} $1"; PASS=$((PASS + 1)); }
fail() { echo -e "  ${RED}✗${NC} $1 — $2"; FAIL=$((FAIL + 1)); }
skip() { echo -e "  ${YELLOW}○${NC} $1 (跳过)"; SKIP=$((SKIP + 1)); }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 激活 venv
if [ -f venv/bin/activate ]; then
    source venv/bin/activate
else
    echo -e "${RED}❌ venv 未找到，请先运行 ./install.sh${NC}"
    exit 1
fi

export PYTHONPATH="$SCRIPT_DIR/src"

echo "============================================"
echo "  mini-note 安装验证"
echo "============================================"
echo ""

# ----------------------------------------------------------
# 1. 基础检查
# ----------------------------------------------------------
echo "[1] 基础环境检查"

python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null && \
    pass "Python >= 3.10" || fail "Python >= 3.10" "需要 Python 3.10+"

python3 -c "import yaml; import dotenv" 2>/dev/null && \
    pass "核心依赖 (pyyaml, python-dotenv)" || fail "核心依赖" "pyyaml 或 python-dotenv 未安装"

echo ""

# ----------------------------------------------------------
# 2. CLI 冒烟测试
# ----------------------------------------------------------
echo "[2] CLI 命令冒烟测试"

TMP_WS=$(mktemp -d)
trap "rm -rf $TMP_WS" EXIT

# init
RESULT=$(python3 -m mini_note.cli init --workspace "$TMP_WS" 2>&1) || true
echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('ok') else 1)" 2>/dev/null && \
    pass "init    创建 workspace" || fail "init" "创建失败"

# health
RESULT=$(python3 -m mini_note.cli health --workspace "$TMP_WS" --json 2>&1) || true
echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('ok') and 'checks' in d else 1)" 2>/dev/null && \
    pass "health  健康检查" || fail "health" "检查失败"

# lint
RESULT=$(python3 -m mini_note.cli lint --workspace "$TMP_WS" --changed-only --json 2>&1) || true
echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if 'broken_wikilinks' in d else 1)" 2>/dev/null && \
    pass "lint    Lint 检查" || fail "lint" "检查失败"

# index rebuild
RESULT=$(python3 -m mini_note.cli index rebuild --workspace "$TMP_WS" --json 2>&1) || true
echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('ok') else 1)" 2>/dev/null && \
    pass "index   重建索引" || fail "index" "重建失败"

# review list
RESULT=$(python3 -m mini_note.cli review list --workspace "$TMP_WS" --json 2>&1) || true
echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if isinstance(d, list) else 1)" 2>/dev/null && \
    pass "review  审核列表" || fail "review" "列表失败"

# backup create
RESULT=$(python3 -m mini_note.cli backup create --workspace "$TMP_WS" --reason verify --json 2>&1) || true
echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('ok') else 1)" 2>/dev/null && \
    pass "backup  创建备份" || fail "backup" "创建失败"

# restore verify
RESULT=$(python3 -m mini_note.cli restore verify --workspace "$TMP_WS" --snapshot "" --json 2>&1) || true
echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('error_code')=='MISSING_SNAPSHOT' else 1)" 2>/dev/null && \
    pass "restore 恢复验证" || fail "restore" "验证失败"

# unknown command
RESULT=$(python3 -m mini_note.cli unknown_cmd --workspace "$TMP_WS" 2>&1) || true
echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('ok')==False and d.get('error_code') else 1)" 2>/dev/null && \
    pass "error   错误处理" || fail "error" "未知命令应返回错误"

echo ""

# ----------------------------------------------------------
# 3. 完整测试套件
# ----------------------------------------------------------
if [ "$1" = "--quick" ]; then
    skip "pytest 测试套件（使用 --quick 跳过）"
else
    echo "[3] pytest 测试套件"
    python3 -m pytest tests/ -q --tb=short 2>&1
    PYTEST_EXIT=$?
    if [ $PYTEST_EXIT -eq 0 ]; then
        pass "pytest  全部测试通过"
    else
        fail "pytest" "部分测试失败 (exit=$PYTEST_EXIT)"
    fi
fi

echo ""

# ----------------------------------------------------------
# 4. OSS 配置检测
# ----------------------------------------------------------
echo "[4] OSS 备份配置检测"
python3 -c "
import os
vars = ['OSS_ENDPOINT','OSS_BUCKET','OSS_ACCESS_KEY_ID','OSS_ACCESS_KEY_SECRET']
missing = [v for v in vars if not os.getenv(v)]
if missing:
    print(f'  未配置: {missing}')
    print('  OSS 云端备份不可用（本地备份正常）')
else:
    print('  ✅ OSS 凭证完整，云端备份可用')
" 2>/dev/null

echo ""
echo "============================================"
echo -e "  结果: ${GREEN}$PASS 通过${NC}, ${RED}$FAIL 失败${NC}, ${YELLOW}$SKIP 跳过${NC}"
echo "============================================"

if [ $FAIL -gt 0 ]; then
    exit 1
fi
exit 0
