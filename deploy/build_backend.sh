#!/bin/bash
# ================================================================
# 后端一键构建脚本 (Ubuntu 24.04)
# 流程: .py → Cython .so → PyInstaller 打包
# 依赖: uv (Python 包管理器)
# 用法: bash build_backend.sh
# ================================================================

set -e

# 清除所有网络代理环境变量，确保构建过程不受代理干扰
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY

# 获取脚本所在目录 (此时为 deploy 目录)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_ROOT/backend"

echo "========================================================"
echo "      后端构建: .py → .so → PyInstaller"
echo "========================================================"
echo "项目目录: $PROJECT_ROOT"
echo "后端目录: $BACKEND_DIR"
echo ""

# 检查 uv 是否可用
if ! command -v uv &>/dev/null; then
    echo "❌ 错误: 未找到 uv 命令。请先安装: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

cd "$BACKEND_DIR"

# 清理旧的编译产物 (*.so, *.c, backend.tar.gz) 以及 build/dist 目录
echo "-> 清理旧的编译产物与历史部署包 (*.so, *.c, backend.tar.gz, build/dist)..."
rm -f *.so *.c "$PROJECT_ROOT/deploy/backend.tar.gz"
rm -rf build dist

# 检查 python3-dev 是否已安装（Cython 编译 C 扩展必需）
if ! dpkg -s python3-dev &>/dev/null; then
    echo "-> 安装 python3-dev (编译 C 扩展必需)..."
    sudo apt-get update && sudo apt-get install -y python3-dev
fi

# ── [1/4] Cython 编译 .py → .so ──
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  [1/4] Cython 编译 .py → .so"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
uv run --python 3.12 --with cython --with setuptools python "$SCRIPT_DIR/compile_so.py"
echo ""

# ── [2/4] 验证编译结果 ──
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  [2/4] 验证编译结果"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
SO_COUNT=$(ls -1 *.so 2>/dev/null | wc -l)
PY_COUNT=$(ls -1 *.py 2>/dev/null | wc -l)
echo "  .so 文件数: $SO_COUNT"
echo "  .py 文件数: $PY_COUNT (应仅保留 main.py 和 compile_so.py)"
echo ""

if [ "$SO_COUNT" -eq 0 ]; then
    echo "❌ 错误: 未生成任何 .so 文件，编译可能失败"
    exit 1
fi

# 快速验证: main.py 能否 import 编译后的模块
echo "  -> 验证 import 链路..."
uv run --python 3.12 python -c "
import sys
sys.path.insert(0, '.')
try:
    import utils
    import sse_hub
    import weather_service
    print('  ✅ 核心模块 import 验证通过')
except ImportError as e:
    print(f'  ❌ import 失败: {e}')
    sys.exit(1)
"
echo ""

# ── [3/4] PyInstaller 编译打包 ──
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  [3/4] PyInstaller 编译打包"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 临时移走 .py 源码文件（除主入口外），迫使 PyInstaller 仅打包已编译的 .so 二进制模块
echo "-> 临时备份 .py 源文件以进行保护打包..."
mkdir -p temp_py_backup
for f in *.py; do
    if [ "$f" != "main.py" ] && [ "$f" != "compile_so.py" ]; then
        mv "$f" temp_py_backup/
    fi
done

# 执行打包（保证不论成功或失败，最后都会恢复源码文件）
set +e
uv run --python 3.12 --with pyinstaller python -m PyInstaller "$SCRIPT_DIR/backend.spec" --workpath "$BACKEND_DIR/build" --distpath "$BACKEND_DIR/dist" --clean --noconfirm
PACK_EXIT_CODE=$?
set -e

# 恢复 .py 源文件
echo "-> 恢复 .py 源文件到原目录..."
if [ -d temp_py_backup ] && [ "$(ls -A temp_py_backup 2>/dev/null)" ]; then
    mv temp_py_backup/* ./
fi
rm -rf temp_py_backup

if [ $PACK_EXIT_CODE -ne 0 ]; then
    echo "❌ 错误: PyInstaller 打包失败！"
    exit $PACK_EXIT_CODE
fi
echo ""

# ── [4/4] 生成部署包 & 清理产物 ──
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  [4/4] 生成部署包 & 清理产物"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
TAR_FILE="$PROJECT_ROOT/deploy/backend.tar.gz"

# 将项目根目录下的 .env 密钥配置和 configs/ 配置文件拷贝到打包目录
if [ -f "$PROJECT_ROOT/.env" ]; then
    echo "-> 打包密钥配置文件 .env 到后端部署包..."
    cp "$PROJECT_ROOT/.env" "$BACKEND_DIR/dist/backend/"
fi

if [ -d "$PROJECT_ROOT/configs" ]; then
    echo "-> 打包配置文件目录 configs/ 到与 backend 同级部署包..."
    cp -r "$PROJECT_ROOT/configs" "$BACKEND_DIR/dist/"
fi

if [ -d "$BACKEND_DIR/assets" ]; then
    echo "-> 打包语音静态资源目录 assets/ 到后端部署包..."
    cp -r "$BACKEND_DIR/assets" "$BACKEND_DIR/dist/backend/"
fi

echo "-> 制作归档部署包 (backend.tar.gz)..."
tar -czf "$TAR_FILE" -C "$BACKEND_DIR/dist" backend configs

# 清理中间构建目录与临时文件
echo "-> 清理中间产物 (*.so, build, dist)..."
rm -f *.so
rm -rf build dist __pycache__

if [ -f "$TAR_FILE" ]; then
    TAR_SIZE=$(du -sh "$TAR_FILE" | cut -f1)
    echo ""
    echo "========================================================"
    echo "✅ 后端构建与归档成功！"
    echo "部署包产物: $TAR_FILE ($TAR_SIZE)"
    echo "========================================================"
else
    echo "❌ 错误: 归档部署包生成失败: $TAR_FILE"
    exit 1
fi
