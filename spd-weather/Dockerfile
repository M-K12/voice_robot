# 使用轻量级官方 Python 镜像
FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 设置时区和语言，避免一些时间处理引发的问题
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 把依赖文件复制过来并安装
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# 将整个 spd-weather 目录复制进容器的 /app
COPY . /app

# 暴露 FastAPI 运行端口（默认 8000）
EXPOSE 8000

# 为了导入同一级模块（spd_weather 和内置 assets 的相对路径），在 scripts 目录中启动
WORKDIR /app/scripts

# 启动 uvicorn 命令（外部使用建议用生产级绑定的 uvicorn）
CMD ["uvicorn", "weather_api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
