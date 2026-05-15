#!/bin/bash
set -e

# ============================================================
# mini-note 目录批量导入脚本
# 用法: ./import.sh <来源目录> [--owner ID] [--scope SCOPE] [--dry-run]
# ============================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

usage() {
    echo "用法: ./import.sh <来源目录> [选项]"
    echo ""
    echo "将指定目录中的文件批量导入 mini-note 知识库。"
    echo ""
    echo "选项:"
    echo "  --owner ID      文件归属（默认 user-default）"
    echo "  --scope SCOPE   可见范围 shared/private（默认 shared）"
    echo "  --force         跳过磁盘空间预检，强制导入"
    echo "  --cleanup       导入后将 inbox 文件移至 processed/"
    echo "  --dry-run       仅列出文件，不执行导入"
    echo "  --help          显示帮助"
    echo ""
    echo "示例:"
    echo "  ./import.sh ~/Documents/notes"
    echo "  ./import.sh ~/Downloads/ecs-docs --owner alice --scope private"
    echo "  ./import.sh ./staging --dry-run"
    exit 0
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 固定 venv Python 路径（不依赖 PATH 中的 python3）
VENV_PYTHON="$SCRIPT_DIR/venv/bin/python3"
if [ ! -x "$VENV_PYTHON" ]; then
    echo -e "${RED}错误: 未找到 venv Python ($VENV_PYTHON)，请先运行 ./install.sh${NC}" >&2
    exit 1
fi

export PYTHONUNBUFFERED=1
export PYTHONIOENCODING=UTF-8

# 参数解析
DRY_RUN=false
FORCE=false
CLEANUP=""
OWNER="user-default"
SCOPE="shared"
SRC_DIR=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h) usage ;;
        --dry-run) DRY_RUN=true; shift ;;
        --force) FORCE=true; shift ;;
        --cleanup) CLEANUP="--cleanup processed"; shift ;;
        --owner) OWNER="$2"; shift 2 ;;
        --scope) SCOPE="$2"; shift 2 ;;
        -*) echo -e "${RED}未知选项: $1${NC}"; exit 1 ;;
        *) SRC_DIR="$1"; shift ;;
    esac
done

if [ -z "$SRC_DIR" ]; then
    echo -e "${RED}错误: 请指定来源目录${NC}"
    usage
fi

if [ ! -d "$SRC_DIR" ]; then
    echo -e "${RED}错误: 目录不存在: $SRC_DIR${NC}"
    exit 1
fi

# 计算文件列表
echo "=== 扫描来源目录 ==="
echo "来源: $SRC_DIR"
echo "归属: $OWNER"
echo "范围: $SCOPE"
echo ""

FILE_COUNT=0
TOTAL_SIZE=0
while IFS= read -r -d '' f; do
    name=$(basename "$f")
    [[ "$name" == .* ]] && continue
    [[ "$name" == ".gitkeep" ]] && continue
    FILE_COUNT=$((FILE_COUNT + 1))
    size=$(stat -f%z "$f" 2>/dev/null || stat -c%s "$f" 2>/dev/null)
    TOTAL_SIZE=$((TOTAL_SIZE + size))
done < <(find "$SRC_DIR" -type f -print0)

if [ "$FILE_COUNT" -eq 0 ]; then
    echo "来源目录中没有可导入的文件。"
    exit 0
fi

# 格式化文件大小
if [ $TOTAL_SIZE -ge 1048576 ]; then
    SIZE_FMT="$((TOTAL_SIZE / 1048576)) MB"
elif [ $TOTAL_SIZE -ge 1024 ]; then
    SIZE_FMT="$((TOTAL_SIZE / 1024)) KB"
else
    SIZE_FMT="${TOTAL_SIZE} B"
fi

echo "文件数: $FILE_COUNT"
echo "总大小: $SIZE_FMT"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo "--- 文件列表（仅预览） ---"
    find "$SRC_DIR" -type f -not -name ".*" -not -name ".gitkeep" -exec ls -lh {} \;
    echo ""
    echo "--dry-run 模式，未执行导入。"
    exit 0
fi

# 磁盘空间预检（外部源目录 → inbox 副本(1x) + 摄入输出(2x) = 3x 估算）
if [ "$FORCE" = false ]; then
    echo "--- 磁盘空间预检 ---"
    PRECHECK=$(./run.sh ingest precheck-disk --dir "$SRC_DIR" --json 2>&1) || true
    if [ -z "$PRECHECK" ]; then
        echo -e "${RED}⚠ 磁盘预检执行失败，无法评估空间需求。${NC}"
        echo "使用 --force 可跳过预检强制导入。"
        exit 1
    fi
    # 提取评估数据；import.sh 估算 = 原始文件 × 3（含 inbox 副本）
    ASSESSMENT=$(echo "$PRECHECK" | "$VENV_PYTHON" -c "
import sys, json
d = json.load(sys.stdin)
total = d.get('total_size_bytes', 0)
avail = d.get('available_bytes', 0)
margin = d.get('safe_margin_bytes', 100*1024*1024)
# 外部源导入：inbox 副本 + archive + extracted + index ≈ 3x
est = total * 3
fit = (avail - est) >= margin
print(f'{d.get(\"file_count\",0)}|{total}|{avail}|{est}|{fit}')
" 2>/dev/null)
    if [ -z "$ASSESSMENT" ]; then
        echo -e "${RED}⚠ 无法解析预检结果。${NC}"
        echo "使用 --force 可跳过预检强制导入。"
        exit 1
    fi
    IFS='|' read -r FC TOTAL_SZ AVAIL_SZ EST_SZ WOULD_FIT <<< "$ASSESSMENT"

    fmt_bytes() {
        "$VENV_PYTHON" -c "print(f'{$1 / 1024 / 1024:.1f} MB')"
    }
    echo "  文件数: $FC"
    echo "  文件总大小: $(fmt_bytes $TOTAL_SZ)"
    echo "  预估需求(inbox副本+摄入): $(fmt_bytes $EST_SZ)"
    echo "  当前可用: $(fmt_bytes $AVAIL_SZ)"

    if [ "$WOULD_FIT" = "False" ]; then
        echo ""
        echo -e "${RED}⚠ 磁盘空间不足，导入后可用空间可能低于安全余量。${NC}"
        echo "使用 --force 可跳过预检强制导入。"
        exit 1
    fi
    echo "磁盘空间充足，可以导入。"
    echo ""
fi

# 复制到 inbox
echo "--- 复制文件到 inbox ---"
INBOX_DIR="$SCRIPT_DIR/raw/inbox/users"
mkdir -p "$INBOX_DIR"

COPIED=0
while IFS= read -r -d '' f; do
    name=$(basename "$f")
    [[ "$name" == .* ]] && continue
    [[ "$name" == ".gitkeep" ]] && continue

    # 处理重名文件
    dest="$INBOX_DIR/$name"
    if [ -f "$dest" ]; then
        base="${name%.*}"
        ext="${name##*.}"
        dest="$INBOX_DIR/${base}-$(date +%H%M%S).${ext}"
    fi
    cp "$f" "$dest"
    echo "  $name"
    COPIED=$((COPIED + 1))
done < <(find "$SRC_DIR" -type f -print0)

echo "已复制 $COPIED 个文件。"

# 执行批量摄入
echo ""
echo "--- 执行批量摄入 ---"
FORCE_FLAG=""
if [ "$FORCE" = true ]; then
    FORCE_FLAG="--force"
fi
PYTHONPATH="$SCRIPT_DIR/src" "$VENV_PYTHON" -u -m mini_note.cli ingest \
    --workspace "$SCRIPT_DIR" \
    --scan-inbox \
    --owner "$OWNER" \
    --scope "$SCOPE" \
    $FORCE_FLAG \
    $CLEANUP \
    --json

echo ""
echo -e "${GREEN}✅ 导入完成${NC}"
