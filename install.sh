#!/bin/bash
set -e

# ============================================================
# mini-note 一键安装脚本
# 用法: ./install.sh
# ============================================================

echo "=== mini-note 安装 ==="

# 1. 检测 Python 版本
echo "[1/5] 检测 Python 版本..."
python3 -c "import sys; v=sys.version_info; sys.exit(0 if v>=(3,10) else 1)" || {
    echo "❌ 需要 Python >= 3.10，当前: $(python3 --version)"
    exit 1
}
echo "  ✅ $(python3 --version)"

# 2. 创建虚拟环境
echo "[2/5] 创建虚拟环境..."
if [ ! -d venv ]; then
    python3 -m venv venv
    echo "  ✅ venv 已创建"
else
    echo "  ✅ venv 已存在"
fi
source venv/bin/activate

# 3. 安装依赖
echo "[3/5] 安装依赖..."
pip install -r requirements.txt -q
pip install pytest -q
echo "  ✅ 依赖安装完成"

# 4. 生成配置模板
echo "[4/5] 初始化配置..."
[ ! -f .env ] && cp .env.example .env && echo "  ⚠ 已创建 .env，请编辑填写 OSS 凭证" || echo "  ✅ .env 已存在"
[ ! -f meta/config.yaml ] && cp meta/config.example.yaml meta/config.yaml && echo "  ✅ 已创建 meta/config.yaml" || echo "  ✅ meta/config.yaml 已存在"
[ ! -f meta/identities.yaml ] && cp meta/identities.example.yaml meta/identities.yaml && echo "  ✅ 已创建 meta/identities.yaml" || echo "  ✅ meta/identities.yaml 已存在"

# 5. 初始化 workspace
echo "[5/5] 初始化 workspace..."
./run.sh init --workspace .
echo "✅ mini-note 安装完成！"
echo ""
echo "后续步骤："
echo "  1. 编辑 .env 填写 OSS 凭证（如需备份功能）"
echo "  2. 编辑 meta/purpose.md 描述你的知识库目标"
echo "  3. ./run.sh ingest --file <path> 开始摄入资料"
echo "  4. ./run.sh query --question '...' 查询知识库"
