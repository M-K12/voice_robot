"""
Voice Robot Backend — FastAPI 主入口（前后端分离版本）

架构:
  - 后端常驻录音（sounddevice）→ KWS 唤醒检测 → Omni 对话 → 扬声器播放
  - 前端通过 SSE 被动接收事件（唤醒/转录/天气/挂断）
  - 前端无麦克风、无播放、无 WebSocket

提供路由:
  GET  /sse      → SSE 长连接（前端唯一数据通道）
  GET  /weather  → 天气查询
  GET  /health   → 健康检查

运行方式:
  uv run uvicorn backend.main:app --host 127.0.0.1 --port 8765 --reload
"""

from __future__ import annotations

import os
import json
import asyncio
import base64
import traceback
import uvicorn
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from backend.weather_router import router as weather_router
from backend.omni_realtime_client import OmniRealtimeClient, TurnDetectionMode
from backend.sse_hub import sse_hub
from backend.utils import fetch_default_city
from backend.tools import GLOBAL_TOOLS_SCHEMA, get_instructions, ToolContext, execute_tool

# FastAPI 初始化
app = FastAPI(title="Voice Robot Backend", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(weather_router)

DEFAULT_CITY = "北京"
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")

# ──────────────────────────────────────────────
# WebSocket 语音路由 (前端接入麦克风与播放)
# ──────────────────────────────────────────────
@app.websocket("/voice_ws")
async def voice_websocket_endpoint(websocket: WebSocket, voice: str = "Cherry", token: str = ""):
    await websocket.accept()
    print("\n\033[96m[WS] 前端语音通话 WebSocket 已连接\033[0m")
    
    api_key = token if token else DASHSCOPE_API_KEY
    if not api_key:
        print("[WS] 错误: 缺少 API Key")
        await websocket.close(code=4000, reason="API Key is missing")
        return
        
    client = None
    session_active = True
    expecting_weather_summary = False
    loop = asyncio.get_running_loop()
    
    # ── Callbacks for Omni ──
    async def on_interrupt():
        print("\033[93m[WS-Omni] User speaking detected - interrupting AI playback\033[0m")
        try:
            await websocket.send_json({"type": "interrupt"})
        except Exception:
            pass

    def on_input_transcript(text: str):
        if not text.strip(): return
        print(f"\033[94m[WS-STT] User: {text}\033[0m")
        asyncio.run_coroutine_threadsafe(
            websocket.send_json({"type": "input_transcript", "data": text}),
            loop
        )
        asyncio.run_coroutine_threadsafe(
            websocket.send_json({"type": "debug_event", "step": "stt", "content": text}),
            loop
        )

    def on_output_transcript(text: str, response_id: str):
        nonlocal expecting_weather_summary
        print(f"\033[92m[WS-TTS] AI: {text}\033[0m")
        if expecting_weather_summary:
            expecting_weather_summary = False
            # 发送 weather_summary 替换前端的“正在总结”提示
            asyncio.run_coroutine_threadsafe(
                websocket.send_json({"type": "weather_summary", "data": text}),
                loop
            )
        else:
            asyncio.run_coroutine_threadsafe(
                websocket.send_json({"type": "output_transcript", "data": text}),
                loop
            )
        asyncio.run_coroutine_threadsafe(
            websocket.send_json({"type": "debug_event", "step": "tts", "content": text}),
            loop
        )

    def on_audio_delta(audio_bytes: bytes):
        asyncio.run_coroutine_threadsafe(
            websocket.send_bytes(audio_bytes),
            loop
        )

    # ── Tool call handler ──
    async def handle_ws_tool_call(event):
        nonlocal session_active, expecting_weather_summary
        call_id = event.get("call_id")
        name = event.get("name")
        arguments_str = event.get("arguments", "{}")
        
        print(f"\033[95m[WS Tool Call] Received request: name={name}, call_id={call_id}, args={arguments_str}\033[0m")
        try:
            await websocket.send_json({
                "type": "debug_event",
                "step": "intent",
                "content": f"语义分析决定调用工具: {name}"
            })
        except Exception:
            pass
        
        try:
            ctx = ToolContext(
                websocket=websocket,
                default_city=DEFAULT_CITY,
                expecting_weather_summary=expecting_weather_summary,
                session_active=session_active
            )
            
            result_payload = await execute_tool(name, arguments_str, ctx)
            
            # Sync context changes back to local variables
            expecting_weather_summary = ctx.expecting_weather_summary
            session_active = ctx.session_active
        except Exception as e:
            print(f"\033[91m[WS Tool Call Exception] Error executing tool: {e}\033[0m")
            traceback.print_exc()
            result_payload = json.dumps({"error": str(e)})
            
        try:
            await client.send_event({
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": result_payload
                }
            })
            await client.send_event({"type": "response.create"})
        except Exception as e:
            print(f"\033[91m[WS Tool Call client send error]: {e}\033[0m")

    def on_tool_call(event):
        asyncio.create_task(handle_ws_tool_call(event))

    instructions = get_instructions(DEFAULT_CITY)

    try:
        client = OmniRealtimeClient(
            base_url="wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
            api_key=api_key,
            model="qwen3.5-omni-plus-realtime",
            on_interrupt=lambda: asyncio.create_task(on_interrupt()),
            on_input_transcript=on_input_transcript,
            on_output_transcript=on_output_transcript,
            on_audio_delta=on_audio_delta,
            turn_detection_mode=TurnDetectionMode.SERVER_VAD,
            extra_event_handlers={
                "response.function_call_arguments.done": on_tool_call,
                "response.created": lambda e: None,
                "response.done": lambda e: None,
                "conversation.item.input_audio_transcription.delta": lambda e: None
            }
        )
        await client.connect()
        await client.update_session({
            "modalities": ["text", "audio"],
            "instructions": instructions,
            "tools": GLOBAL_TOOLS_SCHEMA,
            "tool_choice": "auto",
            "turn_detection": {
                "type": "server_vad",
                "threshold": 0.85,
                "prefix_padding_ms": 300,
                "silence_duration_ms": 700,
                "create_response": True
            }
        })

        msg_task = asyncio.create_task(client.handle_messages())

        # Receive from frontend WS loop
        while session_active:
            msg = await websocket.receive()
            if "bytes" in msg:
                data = msg["bytes"]
                if len(data) > 1 and data[0] == 0x00:
                    pcm_bytes = data[1:]
                    await client.send_event({
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(pcm_bytes).decode()
                    })
            elif "text" in msg:
                try:
                    payload = json.loads(msg["text"])
                    if payload.get("type") == "query":
                        text = payload.get("text", "")
                        if text == "退下":
                            await websocket.send_json({"type": "hangup"})
                            session_active = False
                except Exception:
                    pass

        msg_task.cancel()
        
    except WebSocketDisconnect:
        print("[WS] 前端语音通话 WebSocket 已断开。")
    except Exception as e:
        print(f"[WS] 运行时发生异常: {e}")
        traceback.print_exc()
    finally:
        session_active = False
        if client:
            try:
                await client.close()
            except Exception:
                pass
        print("[WS] 前端语音通话会话已结束")

# ──────────────────────────────────────────────
# 路由
# ──────────────────────────────────────────────
@app.get("/sse")
async def sse_endpoint(request: Request):
    """SSE long-lived connection for frontend event streaming."""
    q = sse_hub.connect()

    async def event_generator():
        try:
            async for event in sse_hub.stream(q):
                # Check if client disconnected
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
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "api_key_set": bool(DASHSCOPE_API_KEY),
        "sse_clients": sse_hub.client_count,
    }

# ──────────────────────────────────────────────
# 启动与关闭
# ──────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    global DEFAULT_CITY
    DEFAULT_CITY = await fetch_default_city()

    # 前端麦克风接管模式下，后端不再主动开启本地声卡录音，以避免本地回声与硬件冲突。
    # 所有音频的采集和播放均通过 /voice_ws 由前端接入。
    print("=" * 50)
    print("Voice Robot Backend v2.0 — 前端麦克风接管模式")
    print(f"  默认城市: {DEFAULT_CITY}")
    print(f"  SSE 端点: /sse")
    print("=" * 50)

@app.on_event("shutdown")
async def shutdown_event():
    pass

if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8765, reload=True)
