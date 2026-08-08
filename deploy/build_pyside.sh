#!/bin/bash
# ================================================================
# PySide6 桌面前端专属一键打包脚本 (Linux / macOS)
# 用法: bash deploy/build_pyside_app.sh
# ================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "========================================================"
echo "   【前端桌面端专属打包】PySide6 客户端 (.py -> .so -> Executable)"
echo "========================================================"
echo ""

if command -v uv &>/dev/null; then
    uv run python deploy/build_pyside.py
else
    python3 deploy/build_pyside.py
fi

echo ""
echo "========================================================"
echo " ✅ 桌面前端构建成功！产物位于 dist/pyside_app/xiaoan_voice_desktop"
echo "========================================================"
