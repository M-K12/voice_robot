#!/bin/bash

echo "================================================="
echo "  小安声纹托管服务 (FastAPI) 阿里云一键部署脚本  "
echo "================================================="

# 检查 Python 环境
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未检测到 python3，请先安装 Python 3.9+！"
    exit 1
fi

# 创建虚拟环境
if [ ! -d "venv" ]; then
    echo "[1/3] 创建 Python 虚拟环境 venv..."
    python3 -m venv venv
fi

# 激活虚拟环境并安装依赖
echo "[2/3] 安装/更新依赖包..."
source venv/bin/activate
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# 尝试以后台 nohup 方式运行
echo "[3/3] 启动声音托管服务 (Port 8777)..."
pkill -f "voiceprint_server.py" || true
nohup python voiceprint_server.py > server.log 2>&1 &

sleep 2
if ps aux | grep -v grep | grep "voiceprint_server.py" > /dev/null; then
    echo "================================================="
    echo " 🎉 服务启动成功！"
    echo " 📍 健康检查接口: http://<您的服务器IP>:8777/health"
    echo " 📂 静态音频服务: http://<您的服务器IP>:8777/voiceprints/"
    echo " 📋 运行日志查看: tail -f server.log"
    echo "================================================="
else

    echo "[错误] 服务启动失败，请检查 server.log 查看日志！"
    cat server.log
fi
