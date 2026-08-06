#!/bin/bash
# ================================================================
# 前端极速构建脚本 (Ubuntu 24.04 / Linux x64)
# 优势: 专为极速构建设计 (单目标 deb + 多核并发加速 + 毫秒级启动)
# 产物: deploy/xiaoan_voice.tar.gz (包含 xiaoan_voice 根目录)
# 用法:
#   bash build_xiaoan_voice.sh          # 默认: 仅打包极速 Tauri 桌面应用 (.deb)
#   bash build_xiaoan_voice.sh --web    # 额外编译 Web dist 静态文件
# ================================================================

set -e

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "========================================================"
echo "   前端极速构建: Vue + Tauri v2 (Target: deb)"
echo "========================================================"
echo "项目目录: $PROJECT_ROOT"
echo ""

# 解析参数
WEB_MODE=false
MODEL_TYPE="int8" # 默认打包 int8 极速模型，极速瘦身与毫秒启动

for arg in "$@"; do
    case "$arg" in
        --web)
            WEB_MODE=true
            ;;
        --fp32|--float)
            MODEL_TYPE="fp32"
            ;;
        --int8)
            MODEL_TYPE="int8"
            ;;
    esac
done

echo "模式选项: Web编译=[$WEB_MODE], 唤醒模型类型=[$MODEL_TYPE]"
echo ""

# 启用 CPU 全核心多线程加速 Rust 编译
export CARGO_BUILD_JOBS=$(nproc)
echo "⚡ CPU 编译加速: 已启用 $(nproc) 核心并行编译"
echo ""

cd "$PROJECT_ROOT"

# ── 0. 清理历史构建产物 (Clean Build) ──
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  [0/3] 清理历史构建残留 (dist, staging, tar.gz)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
rm -rf "$PROJECT_ROOT/dist"
rm -rf "$PROJECT_ROOT/deploy/frontend_staging"
rm -f "$PROJECT_ROOT/deploy/voice.tar.gz" "$PROJECT_ROOT/deploy/xiaoan_voice.tar.gz" "$PROJECT_ROOT/deploy/frontend.tar.gz"
echo "  ✅ 历史残留已完全清理"
echo ""

# ── 1. 安装 npm 依赖 ──
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  [1/3] 安装 npm 依赖"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
npm install
echo ""

# ── 2. --web 模式: 编译 Vue dist ──
if $WEB_MODE; then
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  [2/3] 编译 Vue 静态文件 (npm run build)"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    npm run build
    echo ""
    echo "  ✅ dist/ 静态文件已生成"
    echo ""
else
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  [2/3] 跳过 Web 静态文件编译（默认模式）"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
fi

# ── 3. Tauri Linux 桌面应用构建 (.deb 极速构建) ──
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  [3/3] Tauri Linux 桌面应用构建 (npm run tauri build)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
npm run tauri build
echo ""

# ── 4. 制作前端归档部署包 (包含 voice 一级根目录) ──
TAR_FILE="$PROJECT_ROOT/deploy/voice.tar.gz"
RELEASE_DIR="$PROJECT_ROOT/src-tauri/target/release"
DEB_DIR="$PROJECT_ROOT/src-tauri/target/release/bundle/deb"
STAGING_DIR="$PROJECT_ROOT/deploy/frontend_staging"
INNER_DIR_NAME="voice"
PACKAGE_DIR="$STAGING_DIR/$INNER_DIR_NAME"

echo "-> 制作包含 $INNER_DIR_NAME 根目录的归档部署包 (voice.tar.gz)..."
rm -rf "$STAGING_DIR"
mkdir -p "$PACKAGE_DIR"

# 查找二进制文件 (voice-robot 或 app)
EXEC_FILE=""
if [ -f "$RELEASE_DIR/voice-robot" ]; then
    EXEC_FILE="$RELEASE_DIR/voice-robot"
elif [ -f "$RELEASE_DIR/app" ]; then
    EXEC_FILE="$RELEASE_DIR/app"
fi

if [ -n "$EXEC_FILE" ]; then
    cp "$EXEC_FILE" "$PACKAGE_DIR/voice-client"
    chmod +x "$PACKAGE_DIR/voice-client"
fi

# 从 kws_config.json 动态读取实际使用的 KWS 模型目录（避免硬编码与运行时配置不符）
KWS_CONFIG_FILE="$PROJECT_ROOT/configs/kws_config.json"
if [ -f "$KWS_CONFIG_FILE" ]; then
    # 提取 sherpa_model_dir 最后一个路径段作为模型目录名
    KWS_MODEL_DIR_RAW=$(python3 -c "import json,sys; d=json.load(open('$KWS_CONFIG_FILE')); print(d.get('sherpa_model_dir',''))" 2>/dev/null || echo "")
    if [ -n "$KWS_MODEL_DIR_RAW" ]; then
        KWS_MODEL_NAME=$(basename "$KWS_MODEL_DIR_RAW")
        echo "-> 从 kws_config.json 读取 KWS 模型: $KWS_MODEL_NAME"
    else
        KWS_MODEL_NAME="sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"
        echo "[WARN] 无法解析 kws_config.json 中的 sherpa_model_dir，使用默认值: $KWS_MODEL_NAME"
    fi
else
    KWS_MODEL_NAME="sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"
    echo "[WARN] kws_config.json 不存在，使用默认 KWS 模型名: $KWS_MODEL_NAME"
fi
KWS_SRC_DIR="$PROJECT_ROOT/sherpa/models/$KWS_MODEL_NAME"
if [ -d "$KWS_SRC_DIR" ]; then
    mkdir -p "$PACKAGE_DIR/sherpa/models/$KWS_MODEL_NAME"
    cp -r "$KWS_SRC_DIR/"* "$PACKAGE_DIR/sherpa/models/$KWS_MODEL_NAME/"

    if [ "$MODEL_TYPE" == "fp32" ]; then
        echo "-> 剔除 int8 量化模型，仅打包【高精度 FP32】浮点唤醒模型..."
        find "$PACKAGE_DIR/sherpa/models/$KWS_MODEL_NAME" -type f -name "*.int8.onnx" -delete 2>/dev/null || true
    else
        echo "-> 优先保留 int8 模型，安全剔除有 int8 替代品的 FP32 浮点模型..."
        python3 -c "
import os, glob
model_dir = '$PACKAGE_DIR/sherpa/models/$KWS_MODEL_NAME'
for int8_file in glob.glob(os.path.join(model_dir, '*.int8.onnx')):
    fp32_file = int8_file.replace('.int8.onnx', '.onnx')
    if os.path.exists(fp32_file):
        os.remove(fp32_file)
" 2>/dev/null || true
    fi
    echo "-> 已打包唤醒模型: $KWS_MODEL_NAME (MODEL_TYPE=$MODEL_TYPE)"
else
    echo "[WARN] 未找到 KWS 模型目录: $KWS_SRC_DIR，跳过模型打包"
fi

# 写入一键启动脚本
cat << 'EOF' > "$PACKAGE_DIR/start_voice.sh"
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── 清除代理环境变量，确保前端直连本地后端 (127.0.0.1)，不走 Clash/VPN 代理 ──
unset http_proxy https_proxy all_proxy ftp_proxy
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY FTP_PROXY
# 保留 no_proxy 确保其他应用不受影响，并追加 127.0.0.1 防止 WebView 代理逃逸
export NO_PROXY="127.0.0.1,localhost,::1${NO_PROXY:+,$NO_PROXY}"
export no_proxy="127.0.0.1,localhost,::1${no_proxy:+,$no_proxy}"

# ── 音频后端自动适配（cpal 走 ALSA/PulseAudio，不走 GStreamer）──
# WSLg: PulseAudio socket 在 /mnt/wslg/runtime-dir/pulse/native
if [ -S "/mnt/wslg/runtime-dir/pulse/native" ]; then
    export PULSE_SERVER="unix:/mnt/wslg/runtime-dir/pulse/native"
# 普通 Linux: 仅当 XDG_RUNTIME_DIR 非空时才检查 pulse socket（避免路径拼接错误）
elif [ -n "${XDG_RUNTIME_DIR}" ] && [ -S "${XDG_RUNTIME_DIR}/pulse/native" ]; then
    export PULSE_SERVER="unix:${XDG_RUNTIME_DIR}/pulse/native"
fi

# 强制 cpal/ALSA 使用标准配置，防止 PipeWire 插件接管导致挂起
# 注: GST_PLUGIN_FEATURE_RANK 对 cpal 无效，此处改用 ALSA 标准路径确保兼容
export ALSA_CONFIG_PATH=/usr/share/alsa/alsa.conf

chmod +x ./voice-client
./voice-client "$@"
EOF
chmod +x "$PACKAGE_DIR/start_voice.sh"

# 拷贝 configs/ 运行时配置目录（包含 kws_config.json / global.json 等，Rust 侧 read_config_file 依赖此目录）
if [ -d "$PROJECT_ROOT/configs" ]; then
    cp -r "$PROJECT_ROOT/configs" "$PACKAGE_DIR/configs"
    echo "-> 已打包 configs/ 运行时配置目录"
else
    echo "[WARN] 未找到 configs/ 目录，跳过配置文件打包（可能导致运行时无法加载 KWS/模型配置）"
fi

# 压缩打成包含 voice 根目录的归档 voice.tar.gz
tar -czf "$TAR_FILE" -C "$STAGING_DIR" "$INNER_DIR_NAME"
rm -rf "$STAGING_DIR"

# ── 汇总产物 ──
echo "========================================================"
echo "✅ 前端极速构建完成！"
echo ""
if [ -f "$TAR_FILE" ]; then
    TAR_SIZE=$(du -sh "$TAR_FILE" | cut -f1)
    echo "部署包产物: $TAR_FILE ($TAR_SIZE)"
fi
echo "解压使用说明:"
echo "  • 解压命令: tar -zxvf voice.tar.gz"
echo "  • 启动步骤: cd voice && ./start_voice.sh  (或 ./voice-client)"
echo "========================================================"
