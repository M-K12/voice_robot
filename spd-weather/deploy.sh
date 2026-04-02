#!/bin/bash
# 方便的部署脚本（针对 Ubuntu 等 Linux 发行版）

set -e

echo ">>> 开始部署 SPD Weather API ..."

# 检查 Docker 是否安装
if ! command -v docker &> /dev/null; then
    echo "未检测到 Docker，请先安装 Docker: https://docs.docker.com/engine/install/ubuntu/"
    exit 1
fi

if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "未检测到 Docker Compose，请先安装 Docker Compose。"
    exit 1
fi

echo ">>> 构建分离的 Docker 镜像并启动容器 ..."

# 使用 Docker Compose 启动（如果没有安装新版的 docker compose 可以退化到 docker-compose）
if docker compose version &> /dev/null; then
    docker compose up -d --build
else
    docker-compose up -d --build
fi

echo ">>> 部署完成！"
echo "API 地址: http://127.0.0.1:8000"
echo "Swagger 接口文档: http://127.0.0.1:8000/docs"
echo "你可以通过执行 'docker compose logs -f' 查看实时日志。"
