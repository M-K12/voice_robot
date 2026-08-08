"""
Chat Router — 文本聊天与 SSE 广播路由
"""

from __future__ import annotations

import json
import logging
from typing import List, Optional
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from handlers.openai_chat_handler import OpenAIChatHandler
from visual_manager import visual_broadcast_manager
from sse_hub import sse_hub

logger = logging.getLogger("xiaoan.api.chat")
router = APIRouter()


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []
    system: Optional[str] = "你是一个智能语音助手，请用简洁友好的中文回答问题。"


@router.post("/chat")
async def chat_endpoint(request: ChatRequest):
    print(f"\033[96m[Chat] 用户文字提问: '{request.message}'\033[0m")

    async def event_generator():
        try:
            await visual_broadcast_manager.broadcast({"type": "state_change", "state": "listening"})
            await visual_broadcast_manager.broadcast({"type": "asr_result", "text": request.message, "is_final": True})
            await visual_broadcast_manager.broadcast({"type": "state_change", "state": "thinking"})
        except Exception:
            pass

        yield f'data: {json.dumps({"type": "debug_event", "step": "stt", "content": request.message}, ensure_ascii=False)}\n\n'

        from utils import load_config
        config = load_config()
        city = config.get("default_city", "")

        handler = OpenAIChatHandler()
        has_broadcasted_speaking = False
        accumulated_content = ""

        try:
            history_dicts = [{"role": m.role, "content": m.content} for m in request.history]
            async for token in handler.stream_project_text_chat(message=request.message, history=history_dicts, city=city):
                if not has_broadcasted_speaking:
                    has_broadcasted_speaking = True
                    try:
                        await visual_broadcast_manager.broadcast({"type": "state_change", "state": "speaking"})
                    except Exception:
                        pass
                accumulated_content += token
                if token:
                    try:
                        await visual_broadcast_manager.broadcast({"type": "subtitle", "text": token})
                    except Exception:
                        pass
                yield f'data: {json.dumps({"type": "delta", "content": token}, ensure_ascii=False)}\n\n'

            yield f'data: {json.dumps({"type": "debug_event", "step": "tts", "content": accumulated_content}, ensure_ascii=False)}\n\n'
            yield f'data: {json.dumps({"type": "done"})}\n\n'
        except Exception as e:
            logger.error(f"[Chat] 流生成发生异常: {e}")
            yield f'data: {json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)}\n\n'
        finally:
            try:
                await visual_broadcast_manager.broadcast({"type": "state_change", "state": "idle"})
            except Exception:
                pass

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/sse")
async def sse_endpoint(request: Request):
    """SSE long-lived connection for frontend event streaming."""
    q = sse_hub.connect()

    async def event_generator():
        try:
            async for event in sse_hub.stream(q):
                if await request.is_disconnected():
                    break
                yield event
        finally:
            sse_hub.disconnect(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
