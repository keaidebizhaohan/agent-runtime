#!/bin/bash
# Agent Runtime Server 一键部署脚本

set -e

echo "========================================"
echo "  Agent Runtime Server 部署脚本"
echo "========================================"
echo ""

# 检查 uv
echo "[1/5] 检查环境..."
if ! command -v uv &> /dev/null; then
    echo "  ✗ uv 未安装，请先安装 uv: pip install uv"
    exit 1
fi
UV_VERSION=$(uv --version)
echo "  ✓ uv $UV_VERSION"

# 切换到脚本目录
cd "$(dirname "$0")"
echo "  工作目录: $(pwd)"

# 创建虚拟环境
echo ""
echo "[2/5] 创建虚拟环境..."
if [ ! -d ".venv" ]; then
    uv venv
    echo "  ✓ 虚拟环境创建成功"
else
    echo "  ✓ 虚拟环境已存在"
fi

# 同步依赖
echo ""
echo "[3/5] 同步依赖..."
if [ -f "pyproject.toml" ]; then
    uv sync > /dev/null 2>&1
    echo "  ✓ 依赖同步成功"
else
    echo "  ! 无 pyproject.toml，跳过 uv sync"
fi

# 安装 management
echo ""
echo "[4/5] 安装 management SDK..."
uv pip install -e ../management > /dev/null 2>&1
echo "  ✓ management SDK 安装成功"

# 安装 foundation
echo ""
echo "[5/5] 安装 foundation SDK..."
uv pip install -e ../foundation > /dev/null 2>&1
echo "  ✓ foundation SDK 安装成功"

# 启动服务器
echo ""
echo "启动服务器..."
echo ""
echo "========================================"
echo "  API: http://localhost:8000"
echo "  文档: http://localhost:8000/docs"
echo "========================================"
echo ""

uv run -m openjiuwen_runtime.server.main
