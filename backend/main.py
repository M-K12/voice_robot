"""
Voice Robot Backend — FastAPI 主入口

运行方式:
  uv run python backend/main.py --reload
"""

from __future__ import annotations

import os
import sys
import asyncio
import logging
from pathlib import Path
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# 彻底清除所有网络代理环境变量，防止继承系统/用户环境及.env文件中的代理干扰
for _proxy_key in ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:
    os.environ.pop(_proxy_key, None)

# 智能多路径加载 .env 密钥配置文件
_env_candidates = [
    Path.cwd() / ".env",
    Path(sys.executable).parent / ".env",
    Path(sys.executable).parent / "_internal" / ".env",
    Path(__file__).parent / ".env",
    Path(__file__).parent.parent / ".env",
]
for _env_path in _env_candidates:
    if _env_path.exists():
        load_dotenv(dotenv_path=_env_path)

for _proxy_key in ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:
    os.environ.pop(_proxy_key, None)

# Sanitize NO_PROXY to prevent httpx parsing errors with IPv6 addresses like ::1/128
no_proxy = os.environ.get("NO_PROXY", "")
if no_proxy:
    parts = []
    for part in no_proxy.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            part = part.replace("[", "").replace("]", "")
            if "/" in part:
                part = part.split("/", 1)[0]
        if part and part not in parts:
            parts.append(part)
    os.environ["NO_PROXY"] = ",".join(parts)


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logging.getLogger("xiaoan").setLevel(logging.INFO)
logger = logging.getLogger("xiaoan.main")


class HealthCheckFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "GET /health" not in record.getMessage()

logging.getLogger("uvicorn.access").addFilter(HealthCheckFilter())


# 应用生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    from utils import fetch_default_city, load_config
    from logger_setup import setup_logging
    cfg = load_config()
    setup_logging(console_level=cfg.get("log_level", "INFO"), file_level=cfg.get("log_file_level", "WARNING"))

    default_city = await fetch_default_city()
    logging.info(f"🚀 [Backend Service Started] Voice Robot Backend v2.0 | 默认城市: {default_city}")

    # 🌐 启动后台 POI 异步预热（根据 default_city 增量预热本地 poi_cache.json，零阻塞主线程）
    try:
        from poi_prewarmer import prewarm_city_pois
        asyncio.create_task(prewarm_city_pois(default_city))
    except Exception as e:
        logging.warning(f"⚠️ [POI Prewarm Trigger Error] {e}")

    # 语音静态资源目录挂载
    _assets_candidates = [
        Path(sys.executable).parent / "assets",
        Path.cwd() / "assets",
        Path.cwd() / "backend" / "assets",
        Path(__file__).parent / "assets",
        Path(sys.executable).parent / "_internal" / "assets",
    ]
    _valid_assets_dir = None
    for _p in _assets_candidates:
        if _p.exists() and _p.is_dir() and any(_p.iterdir()):
            _valid_assets_dir = _p
            break
    if _valid_assets_dir:
        app.mount("/assets", StaticFiles(directory=str(_valid_assets_dir)), name="assets")
        logging.info(f"✅ 成功挂载语音静态资源目录 /assets -> {_valid_assets_dir}")
    else:
        logging.warning("⚠️ 未找到 assets 语音静态资源目录，/assets/ 将无法访问！")

    # 声纹预加载（若选用 Qwen-Audio 模型，内部自行判断）
    try:
        from handlers.qwen_audio_realtime_handler import maybe_preload_voiceprints
        asyncio.create_task(maybe_preload_voiceprints(cfg))
    except ImportError:
        pass

    yield


app = FastAPI(title="Voice Robot Backend", version="2.0.0", lifespan=lifespan)

# CORS 跨域配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 导入并挂载模块化子路由
from api.router_chat import router as chat_router
from api.router_voice import router as voice_router
from api.router_config import router as config_router
from api.router_visual import router as visual_router
from api.router_weather import router as weather_router

app.include_router(chat_router)
app.include_router(voice_router)
app.include_router(config_router)
app.include_router(visual_router)
app.include_router(weather_router)


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=10850,
        log_level="info"
    )
