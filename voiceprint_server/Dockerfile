FROM python:3.10-slim

WORKDIR /app

# 安装依赖项
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# 复制服务代码
COPY voiceprint_server.py .

# 创建声纹保存路径
RUN mkdir -p voiceprints

EXPOSE 8777


CMD ["python", "voiceprint_server.py"]
