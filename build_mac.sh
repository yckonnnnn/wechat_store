#!/bin/bash
# macOS 打包脚本
# 用于在 macOS 上打包微信小店客服助手

echo "========================================"
echo "  微信小店客服助手 - macOS 打包脚本"
echo "========================================"
echo ""

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未检测到 Python3"
    exit 1
fi

echo "[1/4] Python 版本：$(python3 --version)"

# 创建虚拟环境
if [ ! -d ".venv" ]; then
    echo "[2/4] 创建虚拟环境..."
    python3 -m venv .venv
else
    echo "[2/4] 虚拟环境已存在"
fi

# 激活虚拟环境并安装依赖
echo "[3/4] 安装依赖..."
source .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo "[4/4] 开始打包..."
echo "这可能需要 2-5 分钟..."

# 清理旧文件
rm -rf build dist

# 运行 PyInstaller（需要单独的 macOS spec 文件）
# 注意：此脚本主要用于演示，macOS 打包可能需要调整 spec 文件
pyinstaller --clean weixin_store.spec

if [ $? -eq 0 ]; then
    echo ""
    echo "========================================"
    echo "  打包成功！"
    echo "========================================"
    echo ""
    echo "应用位置：dist/微信小店客服助手/"
    echo ""
else
    echo ""
    echo "========================================"
    echo "  打包失败"
    echo "========================================"
    exit 1
fi
