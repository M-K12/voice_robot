# SPD Weather API 服务部署指南

这是一个基于 `spd_weather.py` 包装的 FastAPI 服务。
目前已经被设计为可独立部署于 Ubuntu 或其他 Linux 服务器上的微服务，并添加了跨域支持（CORS），以便供你的前端或其他外部应用调用。

## 目录结构
- `scripts/weather_api.py`: FastAPI 接口服务端
- `scripts/spd_weather.py`: 原有天气抓取与核心数据处理逻辑
- `assets/`: 原有的各种地点缓存资产
- `Dockerfile`: 用来打包 Docker 镜像
- `docker-compose.yml`: 一键式容器编排部署文件
- `deploy.sh`: 一键安装和部署脚本

## 方案一：Docker 部署 (推荐)
最简单且不容易污染宿主机的运行方式。
1. 将 `spd-weather` 整个目录上传到 Ubuntu 服务器。
2. 进入目录：`cd spd-weather`
3. 赋予脚本执行权限：`chmod +x deploy.sh`
4. 执行一键部署：`./deploy.sh`

> **提示**：如果需要配置自己的 Token，可以在 `docker-compose.yml` 中的 `SPD_WEATHER_TOKEN=` 补充你的 Token 后再执行部署。

## 方案二：手动测试 (部署前建议执行)
在正式将其配置为 Systemd 服务之前，你可以先在终端手动运行并查看日志输出：

1. 激活环境并进入目录：
```bash
conda activate py12
cd /opt/spd-weather/scripts
```

2. 启动服务：
```bash
uvicorn weather_api:app --host 0.0.0.0 --port 8000 --workers 2
```

3. 验证：
   - 打开浏览器访问 `http://服务器IP:8000/docs` 查看接口文档。
   - 使用 `curl` 测试：`curl "http://127.0.0.1:8000/api/weather/text?city=北京"`

## 方案三：使用 Systemd 裸机部署 (使用现有 Conda py12 环境)
如果不方便使用 Docker，也完全可以使用 Ubuntu 原生的 Systemd 基于你现有的 Conda 环境进行部署。

1. 进入你的 conda 环境并安装必需依赖：
```bash
# 激活你的 py12 环境
conda activate py12

# 切换到代码上传的目录
cd /opt/spd-weather

# 安装运行所需依赖
pip install -r requirements.txt
```

2. 找到 `py12` 环境下 `uvicorn` 的绝对路径，你可以通过此命令获取：
```bash
which uvicorn
# 假设输出为：/home/ubuntu/miniconda3/envs/py12/bin/uvicorn
```

3. 编辑本目录下的 `weather-api.service` 文件，将 `ExecStart` 中的占位路径替换为你上一步获取到的**绝对路径**。同时确保 `User` 和 `WorkingDirectory` 是正确的。

4. 复制 service 文件：
```bash
sudo cp weather-api.service /etc/systemd/system/
```
*(注意：也可以在其中写入真实的 `SPD_WEATHER_TOKEN=...` 环境变量)*

5. 启动并配置开机自启：
```bash
sudo systemctl daemon-reload
sudo systemctl enable weather-api.service
sudo systemctl start weather-api.service
# 查看运行状态
sudo systemctl status weather-api.service
```

## API 接口使用方法
服务默认运行在 `8000` 端口。你可以访问：

1. **获取 JSON 天气**
   `GET http://IP_ADDRESS:8000/api/weather/json?city=北京`

2. **获取纯文本天气**
   `GET http://IP_ADDRESS:8000/api/weather/text?city=北京`

3. **查看 Swagger 文档**
   `http://IP_ADDRESS:8000/docs`
