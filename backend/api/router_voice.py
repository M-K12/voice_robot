"""
Voice WebSocket Router — 前端麦克风/播放 WebSocket 分发路由
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, WebSocket

from utils import load_config
from visual_manager import visual_broadcast_manager

logger = logging.getLogger("xiaoan.api.voice")
router = APIRouter()


@dataclass
class VoiceSessionContext:
    """路由层统一的会话上下文，向各 handler 注入全部所需参数。"""
    websocket: WebSocket
    voice: str
    config: dict
    visual_broadcast_manager: Any
    api_key: str = field(default_factory=lambda: os.getenv("DASHSCOPE_API_KEY", ""))
    voice_model: str = ""
    default_city: str = ""


@router.websocket("/voice_ws")
async def voice_websocket_endpoint(websocket: WebSocket, voice: str = "Tina"):
    await websocket.accept()
    logger.info("[WS] 前端语音通话 WebSocket 已连接")

    config = load_config()
    voice_model = config.get("voice_model_name") or ""
    default_city = config.get("default_city") or ""

    ctx = VoiceSessionContext(
        websocket=websocket,
        voice=voice,
        config=config,
        visual_broadcast_manager=visual_broadcast_manager,
        voice_model=voice_model,
        default_city=default_city,
    )

    if voice_model == "sherpa-local":
        from handlers.local_voice_handler import handle_local_voice_session
        await handle_local_voice_session(
            websocket=ctx.websocket,
            voice=ctx.voice,
            config=ctx.config,
            visual_broadcast_manager=ctx.visual_broadcast_manager,
        )
    elif voice_model == "xunfei-realtime":
        from handlers.xunfei_realtime_handler import handle_xunfei_realtime_session
        await handle_xunfei_realtime_session(
            websocket=ctx.websocket,
            voice=ctx.voice,
            config=ctx.config,
            visual_broadcast_manager=ctx.visual_broadcast_manager,
        )
    elif voice_model and "qwen-audio" in voice_model.lower():
        from handlers.qwen_audio_realtime_handler import handle_qwen_audio_realtime_session
        await handle_qwen_audio_realtime_session(
            websocket=ctx.websocket,
            voice=ctx.voice,
            config=ctx.config,
            visual_broadcast_manager=ctx.visual_broadcast_manager,
        )
    else:
        # 默认 Qwen-Omni 实时多模态模型
        from handlers.qwen_omni_realtime_handler import handle_qwen_omni_realtime_session
        await handle_qwen_omni_realtime_session(
            websocket=ctx.websocket,
            api_key=ctx.api_key,
            voice_model=ctx.voice_model or "qwen3.5-omni-plus-realtime",
            voice=ctx.voice,
            default_city_cfg=ctx.default_city,
            config=ctx.config,
            visual_broadcast_manager=ctx.visual_broadcast_manager,
        )
