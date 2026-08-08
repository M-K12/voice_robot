"""
Config & System Router — 配置管理、健康检查与用户信息动态接口
"""

from __future__ import annotations

import os
import logging
import uuid
import socket
import asyncio
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from visual_manager import visual_broadcast_manager
from sse_hub import sse_hub

logger = logging.getLogger("xiaoan.api.config")
router = APIRouter()

OVERRIDE_CITY: Optional[str] = None
USER_INFO_OVERRIDE: dict = {}


async def resolve_effective_city(config_city: Optional[str] = None) -> tuple[str, str]:
    """
    按优先级解析当前有效聚焦城市：
    1. OVERRIDE_CITY (HTTP 接口动态传入 areaName - 最高优先级)
    2. config_city / 本地配置文件中的设置 (中优先级)
    3. IP 自动获取 (保底)
    返回: (city_name, priority_source)
    """
    global OVERRIDE_CITY
    if OVERRIDE_CITY and OVERRIDE_CITY.strip():
        return OVERRIDE_CITY.strip(), "HTTP API Override"

    if config_city and config_city.strip():
        return config_city.strip(), "Local Config"

    from utils import get_city_by_ip
    ip_city = await get_city_by_ip()
    return ip_city, "IP Auto-Location"


class UserInfoUpdateRequest(BaseModel):
    timestamp: Optional[str] = None
    tenantId: Optional[str] = None
    userId: Optional[str] = None
    orgId: Optional[str] = None
    tenantType: Optional[str] = None
    areaCode: Optional[str] = None
    tenantName: Optional[str] = None
    userName: Optional[str] = None
    orgName: Optional[str] = None
    tenantTypeName: Optional[str] = None
    areaName: Optional[str] = None


@router.get("/config")
def get_config_endpoint(sherpa_model_dir: str = None):
    from utils import load_config, read_wake_word_from_model
    cfg = load_config()
    target_dir = sherpa_model_dir if sherpa_model_dir else cfg.get("sherpa_model_dir")
    cfg["wake_word"] = read_wake_word_from_model(target_dir)
    if sherpa_model_dir:
        return {"wake_word": cfg["wake_word"], "sherpa_model_dir": target_dir}
    return cfg


@router.post("/config")
def update_config_endpoint(new_config: dict):
    from utils import save_config_split, write_wake_word_to_model
    from logger_setup import update_logging_levels

    wake_word = new_config.get("wake_word")
    model_dir = new_config.get("sherpa_model_dir")
    if wake_word and model_dir:
        try:
            write_wake_word_to_model(model_dir, wake_word)
        except Exception as e:
            logger.error(f"[POST /config] Failed to write wake_word to keywords.txt: {e}")

    try:
        merged_config = save_config_split(new_config)

        console_lvl = merged_config.get("log_level", "INFO")
        file_lvl = merged_config.get("log_file_level", "WARNING")
        update_logging_levels(console_level=console_lvl, file_level=file_lvl)

        # 声纹预加载（内部自行判断是否适用 qwen-audio 模型）
        try:
            from handlers.qwen_audio_realtime_handler import maybe_preload_voiceprints
            asyncio.create_task(maybe_preload_voiceprints(merged_config))
        except ImportError:
            pass

        return {"status": "success", "config": merged_config}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
def health_check():
    api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("ALIYUN_API_KEY")
    return {
        "status": "ok",
        "api_key_set": bool(api_key),
        "sse_clients": sse_hub.client_count,
    }


@router.get("/device_id")
async def get_device_id():
    """获取设备唯一ID"""
    device_id = uuid.uuid5(uuid.NAMESPACE_DNS, socket.gethostname() + uuid.getnode().__str__()).hex
    return {"device_id": device_id}


@router.post("/api/user_info")
async def update_user_info(req: UserInfoUpdateRequest):
    global OVERRIDE_CITY, USER_INFO_OVERRIDE

    req_dict = req.model_dump(exclude_unset=True)
    USER_INFO_OVERRIDE.update(req_dict)

    target_city = req.areaName.strip() if req.areaName and req.areaName.strip() else None
    if target_city:
        OVERRIDE_CITY = target_city

    effective_city, priority_source = await resolve_effective_city()
    logger.info(f"👤 [用户信息接口] 收到 POST 更新请求: areaName='{req.areaName}', userName='{req.userName}', orgName='{req.orgName}', effective_city='{effective_city}'")

    info_payload = {
        "type": "user_info_update",
        **USER_INFO_OVERRIDE,
        "effective_city": effective_city,
        "priority_source": priority_source
    }
    await visual_broadcast_manager.broadcast(info_payload)

    if target_city:
        try:
            from api.router_weather import get_weather
            weather_info = await get_weather(effective_city)
            await visual_broadcast_manager.broadcast({
                "type": "weather_data",
                "data": weather_info
            })
        except Exception as e:
            logger.warning(f"[UserInfoUpdate] 实时触发天气查询失败: {e}")

    return {
        "status": "success",
        "user_info": {
            **USER_INFO_OVERRIDE,
            "effective_city": effective_city,
            "priority_source": priority_source
        }
    }


@router.post("/api/logs/frontend")
async def receive_frontend_logs(request: Request):
    try:
        data = await request.json()
        level = (data.get("level") or "info").lower()
        msg = data.get("message", "")
        context = data.get("context", "")
        log_line = f"[{context}] {msg}" if context else msg

        from logger_setup import frontend_logger
        if level in ("error", "fatal"):
            frontend_logger.error(log_line)
        elif level in ("warn", "warning"):
            frontend_logger.warning(log_line)
        else:
            frontend_logger.info(log_line)
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
