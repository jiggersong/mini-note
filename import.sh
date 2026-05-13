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

# 参数解析
DRY_RUN=false
OWNER="user-default"
SCOPE="shared"
SRC_DIR=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h) usage ;;
        --dry-run) DRY_RUN=true; shift ;;
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
if [ -f venv/bin/activate ]; then
    source venv/bin/activate
fi
PYTHONPATH="$SCRIPT_DIR/src" python3 -m mini_note.cli ingest \
    --workspace "$SCRIPT_DIR" \
    --scan-inbox \
    --owner "$OWNER" \
    --scope "$SCOPE" \
    --json

echo ""
echo -e "${GREEN}✅ 导入完成${NC}"
