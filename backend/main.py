"""
Voice Robot Backend — FastAPI 主入口
提供：
  POST /chat      → Qwen-Max SSE 流式对话
  GET  /weather   → 天气查询（调用 spd-weather skill）
  GET  /health    → 健康检查

运行方式（从项目根目录）：
  uv run uvicorn backend.main:app --host 127.0.0.1 --port 8765 --reload
"""

from __future__ import annotations

import os
import sys
from dotenv import load_dotenv

# 加载 .env 环境变量
load_dotenv()
import json
import time
import asyncio
import base64
import subprocess
import shutil
import traceback
from pathlib import Path
from typing import AsyncIterator, List, Optional

import uvicorn
import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.weather_router import router as weather_router, _parse_weather_text
from backend.omni_realtime_client import OmniRealtimeClient, TurnDetectionMode
from dashscope.audio.qwen_tts_realtime import QwenTtsRealtime, QwenTtsRealtimeCallback

# ──────────────────────────────────────────────
# Sherpa-ONNX KWS 唤醒模型初始化
# ──────────────────────────────────────────────
if sys.platform == "win32":
    import importlib.util
    # 注入 sherpa_onnx 的 DLL
    spec_sherpa = importlib.util.find_spec("sherpa_onnx")
    if spec_sherpa and spec_sherpa.origin:
        sherpa_onnx_dir = Path(spec_sherpa.origin).parent
        print(f"[Main] Windows 检测: 添加 sherpa_onnx DLL 路径 {sherpa_onnx_dir}")
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(str(sherpa_onnx_dir))
            except Exception: pass
        os.environ["PATH"] = str(sherpa_onnx_dir) + os.pathsep + os.environ.get("PATH", "")
    
    # 注入 onnxruntime 的 DLL (修复 version [23] mismatch)
    spec_ort = importlib.util.find_spec("onnxruntime")
    if spec_ort and spec_ort.origin:
        ort_dir = Path(spec_ort.origin).parent / "capi"
        if ort_dir.exists():
            print(f"[Main] Windows 检测: 强制添加 onnxruntime DLL 路径 {ort_dir}")
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(str(ort_dir))
                except Exception: pass
            os.environ["PATH"] = str(ort_dir) + os.pathsep + os.environ.get("PATH", "")

try:
    import sherpa_onnx
except ImportError:
    print("[Main] 未安装 sherpa-onnx，语音唤醒功能将不可用。")
    sherpa_onnx = None

KWS_SPOTTER = None
def init_kws_spotter():
    global KWS_SPOTTER
    if not sherpa_onnx:
        print("[KWS] sherpa_onnx 模块未安装，无法进行本地唤醒检测。")
        return
    
    try:
        # 确定项目根目录，确保路径在 Windows/Ubuntu 下均准确
        base_dir = Path(__file__).resolve().parent.parent.parent
        cl_test_dir = base_dir / "cl_test"
        model_dir = cl_test_dir / "models" / "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"
        
        print(f"[KWS] 正在加载模型: {model_dir.relative_to(base_dir) if base_dir in model_dir.parents else model_dir}")
        
        if not model_dir.exists():
            print(f"[KWS] 错误: 模型目录不存在: {model_dir}")
            return
            
        KWS_SPOTTER = sherpa_onnx.KeywordSpotter(
            tokens=str(model_dir / "tokens.txt"),
            encoder=str(model_dir / "encoder-epoch-12-avg-2-chunk-16-left-64.onnx"),
            decoder=str(model_dir / "decoder-epoch-12-avg-2-chunk-16-left-64.onnx"),
            joiner=str(model_dir / "joiner-epoch-12-avg-2-chunk-16-left-64.onnx"),
            num_threads=2,
            max_active_paths=4,
            keywords_file=str(model_dir / "keywords.txt"),
            keywords_score=1.0,
            keywords_threshold=0.18,
            num_trailing_blanks=1,
            provider="cpu"
        )
        print("[KWS] Sherpa-ONNX 唤醒模型加载成功。")
    except Exception as e:
        print(f"[KWS] 加载唤醒模型失败 (检查 DLL 或模型路径): {e}")

# ──────────────────────────────────────────────
# FastAPI 初始化
# ──────────────────────────────────────────────
app = FastAPI(title="Voice Robot Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(weather_router)

# --- 全局配置：动态默认城市 ---
DEFAULT_CITY = "北京"

async def update_default_city():
    global DEFAULT_CITY
    
    # 1. 尝试从项目根目录读取配置
    config_path = (Path(__file__).parent.parent / "config.json").resolve()
    print(f"[Main] Checking config at: {config_path}")
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                import json
                config_data = json.load(f)
                city = config_data.get("default_city")
                if city:
                    DEFAULT_CITY = city
                    print(f"[Main] Default city loaded from config.json: {DEFAULT_CITY}")
                    return  # 读取成功直接返回
                else:
                    print("[Main] 'default_city' parsing failed or not found in config.json")
        except Exception as e:
            print(f"[Main] Failed to read config.json: {e}")
    else:
        print(f"[Main] config.json not found at {config_path}")

    # 2. 尝试从网络基站获取
    try:
        async with httpx.AsyncClient() as client:
            # 使用 ip-api.com 获取当前 IP 的地理位置（中文）
            resp = await client.get("http://ip-api.com/json/?lang=zh-CN", timeout=5.0)
            data = resp.json()
            if data.get("status") == "success":
                city = data.get("city", "")
                if city:
                    # 去掉“市”字，如“成都市”变“成都”
                    if city.endswith("市"):
                        city = city[:-1]
                    DEFAULT_CITY = city
                    print(f"[Main] Default city updated to: {DEFAULT_CITY} (based on IP)")
    except Exception as e:
        print(f"[Main] Failed to get city by IP: {e}")

@app.on_event("startup")
async def startup_event():
    await update_default_city()
    init_kws_spotter()

# ──────────────────────────────────────────────
# 数据模型
# ──────────────────────────────────────────────
class ChatTurn(BaseModel):
    role: str       # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[ChatTurn] = []
    system: Optional[str] = "你是一个智能语音助手，请用简洁友好的中文回答问题。"


class CityExtractRequest(BaseModel):
    message: str


# ──────────────────────────────────────────────
# Qwen-Max 流式对话
# ──────────────────────────────────────────────
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


from fastapi import Request

async def _stream_qwen(messages: list[dict], api_key: str) -> AsyncIterator[str]:
    """调用 DashScope Qwen-Max（兼容 OpenAI 接口），流式 SSE 输出。"""
    if not api_key:
        yield 'data: {"type": "error", "message": "请在前端右上角设置中填写 DashScope API Key"}\n\n'
        return
        
    try:
        from openai import AsyncOpenAI  # type: ignore
        client = AsyncOpenAI(api_key=api_key, base_url=QWEN_BASE_URL)
        stream = await client.chat.completions.create(
            model="qwen-turbo",
            messages=messages,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                data = json.dumps({"type": "delta", "content": delta}, ensure_ascii=False)
                yield f"data: {data}\n\n"
        yield 'data: {"type":"done"}\n\n'
    except Exception as exc:
        err = json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False)
        yield f"data: {err}\n\n"


@app.post("/chat")
async def chat_endpoint(req: ChatRequest, request: Request):
    """SSE 流式聊天接口。"""
    auth = request.headers.get("Authorization", "")
    api_key = auth[len("Bearer "):].strip() if auth.startswith("Bearer ") else DASHSCOPE_API_KEY

    messages: list[dict] = []
    if req.system:
        messages.append({"role": "system", "content": req.system})
    for turn in req.history:
        messages.append({"role": turn.role, "content": turn.content})
    messages.append({"role": "user", "content": req.message})

    return StreamingResponse(
        _stream_qwen(messages, api_key),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "api_key_set": bool(os.getenv("DASHSCOPE_API_KEY"))
    }


@app.post("/extract_city")
async def extract_city(req: CityExtractRequest, request: Request):
    """
    通过大模型提取用户语句中的标准地市级名称（例如：萧山 -> 杭州）
    非流式返回，用于前端查不到天气时的智能重拾字典
    """
    auth = request.headers.get("Authorization", "")
    api_key = auth[len("Bearer "):].strip() if auth.startswith("Bearer ") else os.getenv("DASHSCOPE_API_KEY")

    if not api_key:
        raise HTTPException(status_code=500, detail="Missing DASHSCOPE_API_KEY")

    import openai
    client = openai.AsyncOpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    
    try:
        response = await client.chat.completions.create(
            model="qwen-turbo",
            messages=[
                {"role": "system", "content": "你是一个地名抓取机器。请将用户句子中提到的地点转换为**地级市/直辖市**（例如：萧山->杭州，朝阳区->北京），只能输出最终的纯中文名字，不要任何标点和废话！"},
                {"role": "user", "content": req.message}
            ],
            stream=False,
            temperature=0.1
        )
        city = response.choices[0].message.content.strip()
        return {"city": city}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class LivekitTokenRequest(BaseModel):
    room: str = "voice-room"
    identity: str = "user"

@app.post("/livekit_token")
async def get_livekit_token(req: LivekitTokenRequest):
    """
    颁发供 Tauri (Rust) 客户端直连 LiveKit Server 的 Participant Token。
    默认 devkey 和 secret 为 livekit 官方本地测试默认值。
    """
    from livekit.api import AccessToken, VideoGrants
    api_key = os.getenv("LIVEKIT_API_KEY", "devkey")
    api_secret = os.getenv("LIVEKIT_API_SECRET", "secret")
    url = os.getenv("LIVEKIT_URL", "ws://127.0.0.1:7880")
    
    token = AccessToken(api_key, api_secret) \
        .with_identity(req.identity) \
        .with_name(req.identity) \
        .with_grants(VideoGrants(room_join=True, room=req.room)) \
        .to_jwt()
        
    return {"token": token, "url": url}


# ──────────────────────────────────────────────
# 天气工具（供语音接口调用，已从 subprocess 优化为原生导入）
# ──────────────────────────────────────────────
from backend.weather_router import weather_client

async def _run_weather_script(city: str) -> str:
    print(f"\n{'='*50}")
    print(f"🌦️  开始调用原生天气查询工具 (WeatherTools.get_city_weather) 🌦️")
    print(f"👉 目标查询城市: {city}")
    
    if not weather_client:
        print(f"❌ 错误: weather_client 未初始化")
        print(f"{'='*50}\n")
        return json.dumps({"error": "Weather client not available"})

    try:
        start_time = time.time()
        # 直接异步调用
        raw = await weather_client.get_city_weather(city)
        elapsed = time.time() - start_time
        print(f"⏱️  执行耗时: {elapsed*1000:.2f} 毫秒")
        
        if not raw or "[错误]" in raw:
            print(f"❌ 查询失败: {raw}")
            print(f"{'='*50}\n")
            return json.dumps({"error": raw or "Unknown error"})
            
        print(f"✅ 查询成功！")
        
        # 调试：打印返回数据摘要
        try:
            # 尝试解析并美化 JSON
            parsed_json = json.loads(raw)
            pretty_json = json.dumps(parsed_json, ensure_ascii=False, indent=2)
            if len(pretty_json) > 800:
                print(f"📄 返回数据摘要 (前800字): \n{pretty_json[:800]}\n... [省略]")
            else:
                print(f"📄 内容详情: \n{pretty_json}")
        except json.JSONDecodeError:
            # 非 JSON 则打印文本摘要
            print(f"📄 原始返回片段: \n{raw[:500]}...")
            
        print(f"{'='*50}\n")
        return raw
    except Exception as e:
        print(f"❌ 发生异常: {str(e)}")
        print(f"{'='*50}\n")
        return json.dumps({"error": str(e)})

# ──────────────────────────────────────────────
# 本地字典经纬度查询（供下发打点指令）
# ──────────────────────────────────────────────
_CITY_TO_AREACODE = {}
_AREACODE_TO_STATION = {}
_DICT_LOADED = False

def _load_station_dicts_for_main():
    global _CITY_TO_AREACODE, _AREACODE_TO_STATION, _DICT_LOADED
    if _DICT_LOADED:
        return
    base_dir = Path(__file__).parent.parent / "spd-weather" / "assets"
    try:
        with open(base_dir / "city_to_areacode.json", "r", encoding="utf-8") as f:
            _CITY_TO_AREACODE = json.load(f)
        with open(base_dir / "areacode_to_station.json", "r", encoding="utf-8") as f:
            _AREACODE_TO_STATION = json.load(f)
        _DICT_LOADED = True
    except Exception as e:
        print(f"[Main] Failed to load station dicts: {e}")

def get_city_lonlat(city: str) -> Optional[list[float]]:
    _load_station_dicts_for_main()
    
    # 用简单的省会/别名映射补充（适配用户习惯大名，如"成都"到字典匹配）
    alias = {
        "北京": "北京", "上海": "上海", "天津": "天津", "重庆": "重庆",
        "魔都": "上海", "帝都": "北京", "蓉城": "成都", "羊城": "广州"
    }
    c = alias.get(city, city)
    
    # 尝试多种匹配后缀
    candidates = [c, c.replace("市", ""), c + "市"]
    area_code = None
    for cand in candidates:
        area_code = _CITY_TO_AREACODE.get(cand)
        if area_code:
            break
            
    if not area_code:
        return None
    
    station = _AREACODE_TO_STATION.get(area_code)
    if not station:
        return None
        
    lat = station.get("lat")
    lon = station.get("lon")
    if lat is not None and lon is not None:
        return [lon, lat]
    return None


# ──────────────────────────────────────────────
# Qwen-TTS-Flash-Realtime 助手
# ──────────────────────────────────────────────
class WeatherTTSCallback(QwenTtsRealtimeCallback):
    """
    接收 qwen3-tts-flash-realtime 的音频流并通过 WebSocket 转发给前端。
    """
    def __init__(self, websocket, loop):
        self.websocket = websocket
        self.loop = loop

    def on_open(self):
        print("[WeatherTTS] Connected.")

    def on_close(self, code, msg):
        print(f"[WeatherTTS] Closed: {code} - {msg}")

    def on_event(self, event):
        if not isinstance(event, dict):
            return
        etype = event.get('type')
        if etype == 'response.audio.delta':
            delta = event.get('delta')
            if delta:
                audio_bytes = base64.b64decode(delta)
                # 转发 PCM 音频给前端
                asyncio.run_coroutine_threadsafe(
                    self.websocket.send_bytes(audio_bytes),
                    self.loop
                )

    def on_data(self, data: bytes):
        # 虽然 on_event 已经处理了 delta，但 SDK 有时会直接调用 on_data
        if data:
            asyncio.run_coroutine_threadsafe(
                self.websocket.send_bytes(data),
                self.loop
            )

def _speak_text_realtime(text: str, websocket: WebSocket, loop: asyncio.AbstractEventLoop, tts_state: dict = None, client=None, api_key: str = ""):
    """在后台线程中启动 TTS 合成并将音频流转发给前端。"""
    import threading

    def _run_tts():
        try:
            import dashscope

            if tts_state is not None:
                tts_state["playing"] = True

            if client is not None:
                asyncio.run_coroutine_threadsafe(
                    client.send_event({"type": "input_audio_buffer.clear"}),
                    loop
                )

            # 用 threading.Event 等待合成完毕
            done_event = threading.Event()

            class _TTSCallback(QwenTtsRealtimeCallback):
                def __init__(self):
                    self.audio_buffer = bytearray()

                def on_open(self):
                    print("[WeatherTTS] Connected.")

                def on_close(self, code, msg):
                    print(f"[WeatherTTS] Closed: {code} - {msg}")
                    done_event.set()

                def on_event(self, event):
                    if not isinstance(event, dict):
                        return
                    etype = event.get('type')
                    if etype == 'response.audio.delta':
                        delta = event.get('delta')
                        if delta:
                            audio_bytes = base64.b64decode(delta)
                            self.audio_buffer.extend(audio_bytes)
                            asyncio.run_coroutine_threadsafe(
                                websocket.send_bytes(audio_bytes),
                                loop
                            )
                    elif etype == 'response.done':
                        # print("[WeatherTTS] Synthesis done. Saving to tts_debug_output.wav")
                        # try:
                        #     import wave
                        #     with wave.open("tts_debug_output.wav", "wb") as wf:
                        #         wf.setnchannels(1)
                        #         wf.setsampwidth(2)
                        #         wf.setframerate(24000)
                        #         wf.writeframes(self.audio_buffer)
                        #     print("[WeatherTTS] Successfully saved tts_debug_output.wav")
                        # except Exception as e:
                        #     print(f"[WeatherTTS] Failed to save wav file: {e}")
                        # 
                        done_event.set()

            effective_key = api_key if api_key else os.getenv("DASHSCOPE_API_KEY", "")
            dashscope.api_key = effective_key

            callback = _TTSCallback()
            tts_client = QwenTtsRealtime(
                model='qwen3-tts-flash-realtime',
                callback=callback
            )
            tts_client.connect()

            # 必须先 update_session 配置语音参数
            # 使用官方默认女声 Cherry 以保持和 Omni 闲聊声音一致
            tts_client.update_session(voice="Cherry")

            # 发送要合成的文本
            import re
            if isinstance(text, str):
                cleaned_text = re.sub(r'\s+', '', text)
                if cleaned_text:
                    tts_client.append_text(cleaned_text)
            else:
                while True:
                    chunk = text.get()
                    if chunk is None:
                        break
                    if chunk:
                        cleaned_chunk = re.sub(r'\s+', '', chunk)
                        if cleaned_chunk:
                            tts_client.append_text(cleaned_chunk)

            # 告知服务器文本输入完毕，开始合成
            tts_client.finish()

            # 等待合成完成（最长30秒超时）
            done_event.wait(timeout=30.0)

            try:
                tts_client.close()
            except Exception:
                pass

        except Exception as e:
            print(f"[WeatherTTS] Error in _speak_text_realtime: {e}")
        finally:
            if tts_state is not None:
                tts_state["playing"] = False

    threading.Thread(target=_run_tts, daemon=True).start()

# ──────────────────────────────────────────────
# KWS 唤醒端点
# ──────────────────────────────────────────────
from datetime import datetime
import numpy as np

@app.websocket("/ws/kws")
async def kws_ws(websocket: WebSocket, token: Optional[str] = None):
    """
    接收来自前端的音频流，供本地离线唤醒模型检测。
    """
    await websocket.accept()
    if not KWS_SPOTTER:
        await websocket.close(reason="KWS Model not loaded")
        return
    
    stream = KWS_SPOTTER.create_stream()
    
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
                
            if "bytes" in message and message["bytes"]:
                pcm_data = message["bytes"]
                # 预处理：16000Hz PCM 16-bit 单声道的二进制数据 -> float32 [-1.0, 1.0]
                samples = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0
                
                stream.accept_waveform(16000, samples)
                while KWS_SPOTTER.is_ready(stream):
                    KWS_SPOTTER.decode_stream(stream)
                    
                result = KWS_SPOTTER.get_result(stream)
                if result:
                    # [V4.3] 兼容处理：确保 result 是字符串或提取其 keyword 属性
                    text = getattr(result, 'keyword', str(result))
                    if text.strip():
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] [KWS] 检测到关键词: {text}")
                        await websocket.send_json({
                            "type": "result", 
                            "text": text, 
                            "is_final": True
                        })
                        KWS_SPOTTER.reset_stream(stream)
                    
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[ws/kws] EXCEPTION: {e}")


@app.websocket("/voice_ws")
async def voice_ws(websocket: WebSocket, voice: Optional[str] = None, token: Optional[str] = None):
    await websocket.accept()
    websocket_active = True
    loop = asyncio.get_running_loop()
    tts_state = {"playing": False}
    handling_weather = False  # 新增：用于屏蔽大模型多余的语音干扰
    omni_audio_buffer = bytearray() # 新增：用于调试，保存大模型原生语音
    input_audio_buffer = bytearray() # 新增：用于调试，保存麦克风输入音频
    last_user_query = ""      # 新增：记录用户最后的提问，用于增强天气总结的上下文
    last_processed_transcript = ""
    last_processed_time = 0
    mute_llm_audio = False    # 新增：用于屏蔽单次文字问答时的大模型音频输出
    api_key = token if token else os.getenv("DASHSCOPE_API_KEY", "")
    # voice already passed from query param

    HEARTBEAT_INTERVAL = 25  # seconds
    
    # --- 新增的意图缓冲池（实现 use_tool 的拦截逻辑）---
    # buffering: 正在收集音频文本，等待意图判断
    # intercepted: 确认为内部工具逻辑（天气/挂断），抛弃大模型数据
    # passthrough: 确认为普通聊天，放行缓冲数据
    intercept_state = "buffering" 
    intercept_buffer = []
    last_interaction_time = time.time() # 新增：记录最后一次有效交互时间

    # --- 音频回调 ---
    async def on_audio(audio_data: bytes):
        nonlocal websocket_active, handling_weather, mute_llm_audio, intercept_state, intercept_buffer, last_interaction_time
        if not websocket_active or handling_weather or mute_llm_audio or intercept_state == "intercepted":
            return
            
        last_interaction_time = time.time() # 模型有音频输出，刷新活跃时间
            
        async def _send(b=audio_data):
            try:
                if isinstance(b, str):
                    audio_bytes = base64.b64decode(b)
                else:
                    audio_bytes = b
                if websocket_active:
                    await websocket.send_text(json.dumps({"type": "llm_speaking"})) # 告诉前端AI正在说话，可选
                    await websocket.send_bytes(audio_bytes)
            except Exception:
                pass
                
        if intercept_state == "buffering":
            intercept_buffer.append(_send)
        else:
            asyncio.run_coroutine_threadsafe(_send(), loop)

    async def on_interrupt():
        nonlocal websocket_active, intercept_state, intercept_buffer, last_interaction_time
        
        # 用户打断，立刻清空当前大模型的回复缓冲，准备接收新的判断
        intercept_state = "buffering"
        intercept_buffer.clear()
        last_interaction_time = time.time() # 用户开始说话，刷新活跃时间
        
        if not websocket_active:
            return
        try:
            await websocket.send_text(json.dumps({"type": "interrupt"}))
        except Exception:
            pass

    # --- 智能提取城市助手方法 ---
    async def _extract_city_llm(text: str) -> str:
        try:
            import openai
            oai_client = openai.AsyncOpenAI(
                api_key=api_key,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            )
            response = await oai_client.chat.completions.create(
                model="qwen-turbo",
                messages=[
                    {"role": "system", "content": f"你是一个精确的地名实体抽取机器。请提取用户句子中提到的地理位置，必须输出标准的【简体中文】地名，可以精确到县级单位（例如：安吉、双流、海淀）。\n如果句子中【包含】明确的地名，只输出该地名的纯中文名称（如“北京”、“纽约”、“双流”），最好是单独的市名或区县名。\n如果句子中【完全不包含】任何地名（例如：“想在露天球场”、“今天适合徒步吗”），你必须严格输出大写英文字母 NONE，严禁输出任何中文、标点或猜测！"},
                    {"role": "user", "content": text}
                ],
                stream=False,
                temperature=0.1,
                max_tokens=10
            )
            result = response.choices[0].message.content.strip()
            if result.upper() == "NONE":
                return "NONE"
            return result
        except Exception as e:
            print(f"[_extract_city_llm] Error: {e}")
            return ""

    async def _summarize_weather_llm(raw_weather: str, city: str, api_key: str, user_query: str = ""):
        """使用 qwen-文字模型 将原始天气数据流式总结为一段自然的语音播报文案。"""
        if not api_key:
            print(f"[_summarize_weather_llm] No API Key provided for {city}")
            yield f"已为您查到{city}的天气，请看屏幕显示。"
            return
        
        try:
            print(f"[_summarize_weather_llm] Summarizing weather for {city} using qwen-flash (Query: {user_query})...")
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=api_key, base_url=QWEN_BASE_URL)
            
            stream = await client.chat.completions.create(
                model="qwen-flash",
                messages=[
                    {"role": "system", "content": f"""请结合气象数据，全面且详尽地解答用户关于【{city}】的天气询问。
用户的问题是："{user_query}"。
要求：

                "你是一个专业、贴心且反应极快的语音助手。你精通气象并能精准洞察天气对日常生活的影响，风格像一位懂生活的老朋友，严禁自称管家或使用任何机械的开场白。\n"
                "1. **直接回复（无思考无排版）**：必须直接给出最终回答，严禁输出 [THINK] 标签或内心独白；严禁使用星号、横线等任何 Markdown 符号，输出必须是纯净的语音文本。\n"
                "2. **强制调用（绝不伪造数据）**：涉及天气、气温、降水及户外活动决策（如打球、徒步、穿衣等），严禁依靠记忆瞎猜或凑数，必须立刻且仅调用 `get_weather` 工具获取真实数据。\n"
                "3. **静默执行（Zero-chatting）**：判定需要调用工具时，必须直接静默调用。严禁在调用前输出“好的”、“查询中”等任何垫片词，保持交互的瞬时感。\n"
                "4. **深度生活建议（核心任务）**：严禁只报数字。拿到数据后必须主动结合场景给出建议：如紫外线强提醒防晒，风大不宜羽毛球，降温提醒带件外套方便穿脱，连阴雨提醒心情除霉。让每一句天气预报都变成实用的生活指南。\n"
                "5. **多轮追踪与缺省**：若地点不详，默认使用定位 '{DEFAULT_CITY}'（回复中用“咱这儿”带出）；追问（如“那后天呢”）必须继承地点并静默调用工具后再作答。\n"
                "6. **感性口语化（200字上限）**：回复控制在200字及10句以内。拒绝“预计”、“降水概率”等术面词，多说“会有点”、“建议带上”、“记得哦”。遇到恶劣天气要表现出真实的关怀或警示，拒绝复读机式的播报。\n"
                "7. **异常处理**：若工具报错或无返回，请温柔告知“气象站好像暂时断线了，建议您等下再问我”。\n"
                "8. **【核心性能要求】**：请务必让第一个短句尽量简短（例如：“咱这儿今天天气不错！”或“{city}要下雨了哦”），以便 TTS 能够最快触发响应。"""
},
                    {"role": "user", "content": f"城市：{city}\n原始数据：{raw_weather}"}
                ],
                stream=True,
                temperature=0.1,
                max_tokens=200
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    yield delta
        except Exception as e:
            print(f"[_summarize_weather_llm] Error: {e}")
            import traceback
            traceback.print_exc()
            yield f"已为您查到{city}的天气，请看屏幕显示。"

    async def _stream_weather_and_speak(organized_text: str, city_name: str, key: str, query: str, skip_audio: bool):
        """助手函数：管理 LLM 的文本流式生成、将其推送至 WebSocket，同时喂给后台 TTS"""
        import queue
        import uuid
        text_queue = queue.Queue() if not skip_audio else None
        response_id = f"weather_{uuid.uuid4().hex[:8]}"
        
        if not skip_audio:
            _speak_text_realtime(text_queue, websocket, loop, tts_state, client_ref[0], api_key=key)
            
        summary_msg = ""
        async for chunk in _summarize_weather_llm(organized_text, city_name, key, query):
            summary_msg += chunk
            if websocket_active:
                await websocket.send_text(json.dumps({
                    "type": "weather_summary",
                    "data": summary_msg,
                    "response_id": response_id
                }, ensure_ascii=False))
            if text_queue is not None:
                text_queue.put(chunk)
                
        if text_queue is not None:
            text_queue.put(None)

    def on_input_transcript(transcript: str, is_text: bool = False, no_audio: bool = False):
        nonlocal websocket_active, last_user_query, handling_weather, last_processed_transcript, last_processed_time, intercept_state, intercept_buffer, last_interaction_time
        if not websocket_active:
            return
            
        current_time = time.time()
        last_interaction_time = current_time # 用户完整发出了文本/声音段落，刷新时间

        # 去重：如果是语音识别，如果和上一次文本相同且间隔小于1秒，忽略
        if not is_text and transcript == last_processed_transcript and (current_time - last_processed_time) < 1.0:
            return
            
        transcript = transcript.strip()
        if not is_text and not transcript:
            # VAD 噪音触发导致文字为空，直接拦截并终止大模型的妄想作答，避免重复说话！
            print("[voice_ws] Empty transcript (noise), ignoring and cancelling response.")
            intercept_state = "intercepted"
            intercept_buffer.clear()
            if client_ref[0] and getattr(client_ref[0], '_is_responding', False):
                asyncio.run_coroutine_threadsafe(
                    client_ref[0].send_event({"type": "response.cancel"}), loop
                )
            return

        last_processed_transcript = transcript
        last_processed_time = current_time

        print(f"[voice_ws] Input Transcript (is_text={is_text}): {transcript}")
        last_user_query = transcript # 记录上下文
        try:
            is_hangup = _HANGUP_RE.search(transcript.strip())
            is_weather = _WEATHER_RE.search(transcript)

            if is_hangup or is_weather:
                intercept_state = "intercepted"
                intercept_buffer.clear()  # 丢弃缓冲的大模型抢答！不再需要靠收回前端消息了
                
                if handling_weather:
                    return
                handling_weather = True
                print(f"[voice_ws] Fallback intent matched in transcript: {transcript}")
                
                # 立即取消 Omni 模型的回复并通知前端撤回抢答气泡
                # 必须在发送 input_transcript 之前发送 retract_bot！（保留这部分逻辑避免竞态前端残留）
                if client_ref[0] and getattr(client_ref[0], '_is_responding', False):
                    asyncio.run_coroutine_threadsafe(
                        client_ref[0].send_event({"type": "response.cancel"}), loop
                    )
                asyncio.run_coroutine_threadsafe(
                    websocket.send_text(json.dumps({"type": "retract_bot"})), loop
                )
            else:
                intercept_state = "passthrough"
                # 把之前憋住的大量大模型（普通聊天）回应和音频一次性冲洗给前端
                buffer_copy = list(intercept_buffer)
                intercept_buffer.clear()
                
                async def _flush_buf(buf):
                    for coro in buf:
                        await coro()
                        
                asyncio.run_coroutine_threadsafe(_flush_buf(buffer_copy), loop)

            # 发送用户的文本到前端，这必须在 retract_bot 之后发送，这样前端才能正确删除旧的气泡
            if not is_text:
                asyncio.run_coroutine_threadsafe(
                    websocket.send_text(json.dumps({"type": "input_transcript", "data": transcript})),
                    loop
                )
            
            if is_hangup:
                async def _run_hangup():
                    nonlocal handling_weather, websocket_active
                    print(f"[voice_ws] Hangup intent matched: {transcript}")
                    try:
                        # 1. 停止当前所有播报
                        await on_interrupt()
                        
                        summary_msg = "好的，先退下了。有需要随时叫我。"
                        if websocket_active:
                            await websocket.send_text(json.dumps({
                                "type": "output_transcript",
                                "data": summary_msg
                            }, ensure_ascii=False))
                        
                        # 2. 播报退出语音
                        if not no_audio:
                            # 尝试使用 TTS 播报，但由于要挂断，这里使用推送到队列的方式
                            _speak_text_realtime(summary_msg, websocket, loop, tts_state, client_ref[0], api_key=api_key)
                        
                        # 3. 通知前端彻底挂断（前端收到此消息应恢复 KWS 唤醒）
                        if websocket_active:
                            await websocket.send_text(json.dumps({"type": "hangup"}))
                        
                        # 4. 彻底关闭大模型客户端
                        if client_ref[0]:
                            await client_ref[0].close()
                            
                    except Exception as e:
                        print(f"[_run_hangup] Error: {e}")
                    finally:
                        handling_weather = False
                        # 注意：这里不需要手动设为 False，因为 loop 还在运行，但前端会关闭 WS 导致 loop 退出
                
                asyncio.run_coroutine_threadsafe(_run_hangup(), loop)
                return

            if is_weather:
                async def _run_fallback_weather(transcript_for_eval):
                    nonlocal handling_weather
                    try:
                        print(f"[Fallback] >>> START for: {transcript_for_eval}")
                        # 立刻取消当前大模型正在进行的或即将开始的语音回答（仅在有活跃回答时）
                        if client_ref[0] and getattr(client_ref[0], 'ws', None):
                            if getattr(client_ref[0], '_is_responding', False):
                                await client_ref[0].send_event({"type": "response.cancel"})
                        
                        # 立刻告知前端停止播放已有音频（掐断）
                        await on_interrupt()

                        # 1. 精准提取城市
                        print(f"[Fallback] Step 1: Extracting city...")
                        city = await _extract_city_llm(transcript_for_eval)
                        
                        if city == "NONE":
                            # 如果大模型明确判断句子中没有地名，直接应用默认城市，跳过不可靠的正则匹配
                            print("[Fallback] LLM returned NONE, using DEFAULT_CITY")
                            city = DEFAULT_CITY
                        elif not city:
                            # 只有大模型请求失败时，才降级使用正则匹配
                            m = _CITY_RE.search(transcript_for_eval)
                            city = m.group(1) if m else DEFAULT_CITY
                            for prefix in ["查一下", "帮我查", "帮我看一下", "看一下"]:
                                if city.startswith(prefix):
                                    city = city[len(prefix):]
                        
                        print(f"[Fallback] Step 2: Calling weather for city: '{city}'")
                        raw = await _run_weather_script(city)
                        print(f"[Fallback] Step 3: Weather returned ({len(raw)} chars)")
                        
                        if raw.startswith('{"error"'):
                            try:
                                data_obj = json.loads(raw)
                                organized_text = data_obj.get("error", "抱歉，天气查询失败。")
                                weather_data = None
                            except:
                                organized_text = raw
                                weather_data = None
                        else:
                            organized_text = raw
                            weather_data = _parse_weather_text(raw, city)
                        
                        if websocket_active:
                            if weather_data:
                                lonlat = get_city_lonlat(city)
                                if lonlat:
                                    import time as _tt
                                    await websocket.send_text(json.dumps({
                                        "type": "query_info",
                                        "data": {
                                            "time": _tt.strftime("%Y-%m-%d"),
                                            "lonLat": lonlat,
                                            "description": "气温",
                                            "element_id": "TEM"
                                        }
                                    }, ensure_ascii=False))

                                await websocket.send_text(json.dumps({
                                    "type": "weather_data",
                                    "city": city,
                                    "data": weather_data
                                }, ensure_ascii=False))
                                print(f"[Fallback] Step 4: Weather data sent for {city}")
                                
                                print(f"[Fallback] Step 5: Summarizing...")
                                await _stream_weather_and_speak(organized_text, city, api_key, last_user_query, no_audio)
                            else:
                                await _stream_weather_and_speak(organized_text, city, api_key, last_user_query, no_audio)
                            
                    except Exception as e:
                        print(f"[Fallback] !!! ERROR: {e}")
                        import traceback
                        traceback.print_exc()
                    finally:
                        handling_weather = False
                        print(f"[Fallback] <<< END, handling_weather=False")
                
                asyncio.run_coroutine_threadsafe(_run_fallback_weather(transcript), loop)
                
        except Exception as e:
            print(f"[voice_ws] on_input_transcript error: {e}")


    def on_output_transcript(transcript: str, response_id: str = ""):
        nonlocal websocket_active, handling_weather, intercept_state, intercept_buffer, last_interaction_time
        if not websocket_active or intercept_state == "intercepted":
            return
            
        last_interaction_time = time.time() # 大模型输出文字，刷新时间
        
        # 拦截：如果大模型输出了字面量 get_weather("city")，则当作天气意图处理
        import re as _re
        _gw_re = _re.compile(r'get_weather\s*\(\s*["\x27]([^"\x27]+)["\x27]\s*\)')
        m = _gw_re.search(transcript)
        if m and not handling_weather:
            city = m.group(1)
            print(f"[voice_ws] Intercepted literal get_weather for city: {city}")
            handling_weather = True
            
            async def _run_intercepted_weather(city_name):
                nonlocal handling_weather
                try:
                    print(f"[Intercepted] >>> START for city: {city_name}")
                    if client_ref[0] and getattr(client_ref[0], 'ws', None):
                        if getattr(client_ref[0], '_is_responding', False):
                            await client_ref[0].send_event({"type": "response.cancel"})
                    await on_interrupt()
                    
                    raw = await asyncio.to_thread(_run_weather_script, city_name)
                    print(f"[Intercepted] Weather returned ({len(raw)} chars)")
                    
                    if raw.startswith('{"error"'):
                        try:
                            data_obj = json.loads(raw)
                            organized_text = data_obj.get("error", '')
                            weather_data = None
                        except:
                            organized_text = raw
                            weather_data = None
                    else:
                        organized_text = raw
                        weather_data = _parse_weather_text(raw, city_name)
                    
                    if websocket_active:
                        if weather_data:
                            lonlat = get_city_lonlat(city_name)
                            if lonlat:
                                import time as _tt
                                await websocket.send_text(json.dumps({
                                    "type": "query_info",
                                    "data": {
                                        "time": _tt.strftime("%Y-%m-%d"),
                                        "lonLat": lonlat,
                                        "description": "气温",
                                        "element_id": "TEM"
                                    }
                                }, ensure_ascii=False))
                                
                            await websocket.send_text(json.dumps({
                                "type": "weather_data",
                                "city": city_name,
                                "data": weather_data
                            }, ensure_ascii=False))
                            await _stream_weather_and_speak(organized_text, city_name, api_key, last_user_query, False)
                        else:
                            await _stream_weather_and_speak(organized_text, city_name, api_key, last_user_query, False)
                except Exception as e:
                    print(f"[Intercepted] !!! ERROR: {e}")
                    import traceback
                    traceback.print_exc()
                finally:
                    handling_weather = False
                    print(f"[Intercepted] <<< END")
            
            asyncio.run_coroutine_threadsafe(_run_intercepted_weather(city), loop)
            return
        
        if handling_weather:
            return

        async def _send(t=transcript, r=response_id):
            try:
                if websocket_active:
                    await websocket.send_text(json.dumps({
                        "type": "output_transcript",
                        "data": t,
                        "response_id": r
                    }, ensure_ascii=False))
            except Exception:
                pass

        if intercept_state == "buffering":
            intercept_buffer.append(_send)
        else:
            asyncio.run_coroutine_threadsafe(_send(), loop)

    # --- 天气工具函数 ---
    async def handle_function_call(client: OmniRealtimeClient, function_name: str, function_args: dict, call_id: str):
        """执行工具函数并把结果回传给模型"""
        nonlocal handling_weather

        # 互斥：如果 fallback 关键词检测已经在处理天气，跳过原生函数调用路径
        if function_name == "get_weather" and handling_weather:
            print(f"[voice_ws] Skipping native get_weather — fallback already handling")
            if client:
                await client.send_event({
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps({"info": "已由本地天气处理器处理"}),
                    }
                })
            return

        # 提前设置标志，阻止 fallback 重复触发
        if function_name == "get_weather":
            handling_weather = True

        print(f"[voice_ws] --- Calling weather skill (Native Function Call) ---")
        print(f"[voice_ws]   -> Function: {function_name}, Args: {function_args}")
        result = ""
        if function_name == "get_weather":
            city = function_args.get("city", "").strip()
            # 大模型如果没有抓取到地名，可能会传入空字符，这里做一层把关
            if not city or city == '""' or city.upper() == "NONE":
                print(f"[voice_ws] Native call didn't provide a specific city, defaulting to {DEFAULT_CITY}")
                city = DEFAULT_CITY

            raw = await asyncio.to_thread(_run_weather_script, city)
            print(f"[voice_ws]   -> Tool Output: {raw[:300]}...")
            result = raw
            # 把天气卡片数据同步给前端
            try:
                if raw.startswith('{"error"'):
                    parsed_err = json.loads(raw)
                    organized_text = parsed_err.get("error", "抱歉，天气查询失败。")
                    weather_data = None
                else:
                    organized_text = raw
                    weather_data = _parse_weather_text(raw, city)

                if weather_data:
                    lonlat = get_city_lonlat(city)
                    if lonlat:
                        import time as _tt
                        await websocket.send_text(json.dumps({
                            "type": "query_info",
                            "data": {
                                "time": _tt.strftime("%Y-%m-%d"),
                                "lonLat": lonlat,
                                "description": "气温",
                                "element_id": "TEM"
                            }
                        }, ensure_ascii=False))

                    await websocket.send_text(json.dumps({
                        "type": "weather_data",
                        "city": city,
                        "data": weather_data
                    }, ensure_ascii=False))
                    
                    # --- 使用 LLM 总结并由 TTS 播报结果 ---
                    handling_weather = True
                    try:
                        await _stream_weather_and_speak(organized_text, city, api_key, last_user_query, False)
                    finally:
                        async def _reset_flag():
                            await asyncio.sleep(5)
                            nonlocal handling_weather
                            handling_weather = False
                        asyncio.create_task(_reset_flag())
                
            except Exception as e:
                print(f"[voice_ws] Native weather tool error: {e}")
        else:
            result = json.dumps({"error": f"Unknown function: {function_name}"})

        # 把工具结果发回给模型
        if client:
            # 取消之前可能遗留的响应，以免杂音叠加
            await client.send_event({"type": "response.cancel"})

        await client.send_event({
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": call_id,
                "output": result,
            }
        })
        # 注意：对于天气查询，我们不再调用 response.create，由 TTS 接管语音回答。

    # 使用 extra_event_handlers 挂接工具调用事件
    pending_func: dict = {}

    def on_function_call_arguments_delta(event: dict):
        call_id = event.get("call_id", "")
        delta = event.get("delta", "")
        if call_id not in pending_func:
            pending_func[call_id] = {"name": "", "arguments": ""}
        pending_func[call_id]["arguments"] += delta

    def on_response_output_item_added(event: dict):
        item = event.get("item", {})
        if item.get("type") == "function_call":
            call_id = item.get("call_id", "")
            name = item.get("name", "")
            if call_id not in pending_func:
                pending_func[call_id] = {"name": name, "arguments": ""}
            else:
                pending_func[call_id]["name"] = name

    def on_response_done(event: dict):
        # 当整个 response 完成时，执行所有待处理的工具调用
        for call_id, func_info in list(pending_func.items()):
            if func_info.get("name"):
                try:
                    args = json.loads(func_info["arguments"]) if func_info["arguments"] else {}
                except json.JSONDecodeError:
                    args = {}
                asyncio.run_coroutine_threadsafe(
                    handle_function_call(client_ref[0], func_info["name"], args, call_id),
                    loop
                )
        pending_func.clear()
        
        # 调试测：保存大模型原生语音为 wav (已注释)
        # if len(omni_audio_buffer) > 0:
        #     try:
        #         import wave
        #         with wave.open("omni_debug_output.wav", "wb") as wf:
        #             wf.setnchannels(1)
        #             wf.setsampwidth(2)
        #             wf.setframerate(24000) # Omni原生输出为24kHz
        #             wf.writeframes(omni_audio_buffer)
        #         print(f"[voice_ws] Saved {len(omni_audio_buffer)} bytes to omni_debug_output.wav")
        #     except Exception as e:
        #         print(f"[voice_ws] Failed to save omni debug wav: {e}")
        #     omni_audio_buffer.clear()

    client_ref = [None]  # mutable reference for closures

    # 定义工具 schema
    tools = [
        {
            "type": "function",
            "name": "get_weather",
            "description": "获取指定地点的实时及预报天气。所有气象数据、气温预估、以及对任何户外活动（如游泳、爬山、露营、打球）、穿衣、洗车等涉及环境研判的询问，都必须首先调用此工具获取真实数据，绝不可自行编造温度或瞎猜！",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "要查询天气的地理位置，必须使用标准的简体中文名称，可以精确到县级单位（如：北京、双流、纽约）。如果用户完全没说具体地点（比如只说了“露天球场”、“今天适合穿什么”），此处必须传空字符串 ''，切不可乱填非地名字符！系统会自动使用默认所在地。"
                    }
                },
                "required": ["city"]
            }
        }
    ]

    # 心跳任务
    async def send_heartbeat():
        while True:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                await websocket.send_text(json.dumps({"type": "ping"}))
            except Exception:
                break

    # 15秒超时退出任务
    async def check_timeout():
        nonlocal websocket_active, last_interaction_time, tts_state
        while websocket_active:
            await asyncio.sleep(1)
            
            # 如果大模型正在生成/说话，或者正在跑天气回调播报，强制重置超时时间
            is_omni_responding = client_ref[0] and getattr(client_ref[0], '_is_responding', False)
            is_tts_playing = tts_state.get("playing", False)
            if is_omni_responding or is_tts_playing:
                last_interaction_time = time.time()
                continue
                
            # 超过30秒没互动（既没听见用户说，AI也没在输出）就自动挂断
            if websocket_active and time.time() - last_interaction_time > 30:
                print("[voice_ws] 30 seconds of silence detected. Hanging up.")
                try:
                    await websocket.send_text(json.dumps({"type": "timeout_hangup"}))
                except Exception:
                    pass
                
                # 取消模型回调和底层引擎以干净地退出
                await on_interrupt()
                if client_ref[0]:
                    try:
                        # 跑在线程安全模式下关闭
                        asyncio.run_coroutine_threadsafe(client_ref[0].close(), loop)
                    except Exception:
                        pass
                        
                websocket_active = False
                break

    heartbeat_task = asyncio.create_task(send_heartbeat())
    timeout_task = asyncio.create_task(check_timeout())
    client: Optional[OmniRealtimeClient] = None
    message_task = None

    # 天气关键词检测（用于自动触发天气查询）
    import re
    _WEATHER_RE = re.compile(r'天气|气温|温度|下雨|下雪|预报|穿衣|降水|风力|冷不冷|热不热|爬山|打球|徒步|露营|出差|出门|室外|户外|防晒|带伞|游泳|下水|玩水|洗车|晾晒')
    _CITY_RE = re.compile(r'([^\s，,。！？]{2,6}?)[的]?(?:天气|气温|温度|下雨|下雪|预报|穿衣|降水|风力|冷不冷|热不热|爬山|打球|徒步|露营|出差|室外|户外|游泳|下水|玩水|洗车|晾晒)')
    _HANGUP_RE = re.compile(r'^(退出|退下|结束|挂断|再见|拜拜|退朝).*', re.IGNORECASE)

    try:
        client = OmniRealtimeClient(
            base_url="wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
            api_key=api_key,
            model="qwen3-omni-flash-realtime",
            # 回退到稳定版本以修复 1007 Access Denied 报错（该版本也支持 enable_search）
            on_audio_delta=lambda d: asyncio.create_task(on_audio(d)),
            on_interrupt=lambda: asyncio.create_task(on_interrupt()),
            on_input_transcript=on_input_transcript,
            on_output_transcript=on_output_transcript,
            turn_detection_mode=TurnDetectionMode.SERVER_VAD,
            extra_event_handlers={
                "response.function_call_arguments.delta": on_function_call_arguments_delta,
                "response.output_item.added": on_response_output_item_added,
                "response.done": on_response_done,
            }
        )
        client_ref[0] = client
        await client.connect()
        
        # 针对 qwen3.5-omni-plus-realtime 更新会话配置
        await client.update_session({
            "tools": tools,
            "enable_search": True,  # [V3.5+ 特性] 开启原生联网搜索，消除幻觉
            "instructions": (
                "你是一个专业、精炼且自然的语音助手。你精通气象并能洞察其对生活的影响，风格像有温度的老朋友，严禁自称管家或使用任何尴尬的开场白问候。\n"
                "1. **直接回复（无思考无排版）**：必须直接给出最终回答，严禁输出 [THINK] 标签或内心独白；严禁使用星号、横线等任何 Markdown 符号，输出必须是纯净的语音文本。\n"
                "2. **强制调用（绝不伪造数据）**：涉及天气、气温、降水及户外活动决策（如打球、徒步、穿衣等），严禁依靠记忆瞎猜或凑数，必须立刻且仅调用 `get_weather` 工具获取真实数据。\n"
                "3. **静默执行（Zero-chatting）**：判定需要调用工具时，必须直接静默调用。严禁在调用前输出“好的”、“查询中”等任何垫片词，保持交互的瞬时感。\n"
                "4. **极致精简（100字上限）**：单次回复绝对严禁超过100字，逻辑控制在 3 句以内。直接给出数据结果与体感建议，惜字如金，拒绝任何形式的废话。\n"
                "5. **多轮追踪与缺省**：若地点不详，默认使用定位 '{DEFAULT_CITY}'（回复中用“咱这儿”带出）；追问（如“那后天呢”）必须继承地点并静默调用工具后再作答。\n"
                "6. **深度口语化**：拒绝“预计”、“降水概率”等书面词。多用“会有点”、“建议带上”、“记得哦”。雨天给予暖心关心，极端天气使用警示语气。\n"
                "7. **联网优先**：当你对某个实时事实、最新的天气趋势或户外建议不确定时，请优先通过原生搜索或 `get_weather` 工具确认，坚决杜绝编造数据。\n"
                "8. **异常处理**：若工具报错或无返回，请温柔告知“气象站好像暂时断线了，建议您等下再问我”。"
            )
        })
        
        message_task = asyncio.create_task(client.handle_messages())

        WEBSOCKET_TIMEOUT = 1.0
        while websocket_active:
            try:
                message = await asyncio.wait_for(websocket.receive(), timeout=WEBSOCKET_TIMEOUT)
                if message["type"] == "websocket.disconnect":
                    websocket_active = False
                    break
                if message["type"] == "websocket.receive":
                    if "bytes" in message and message["bytes"]:
                        data = message["bytes"]
                        # 协议：首字节标识流类型 0=audio
                        if len(data) > 1:
                            stream_type = data[0]
                            content = data[1:]
                            if stream_type == 0:  # audio
                                mute_llm_audio = False
                                if tts_state.get("playing", False):
                                    continue # 静音：丢弃这段时间拾取的录音
                                # input_audio_buffer.extend(content)  # 调试：累积输入音频
                                encoded = base64.b64encode(content).decode()
                                await client.send_event({
                                    "event_id": "e" + str(int(time.time() * 1000)),
                                    "type": "input_audio_buffer.append",
                                    "audio": encoded,
                                })
                    elif "text" in message:
                        text_data = message["text"]
                        # 前端发来的转录文本，检测天气意图
                        if text_data not in ("pong", '{"type":"pong"}'):
                            try:
                                msg_obj = json.loads(text_data)
                                if msg_obj.get("type") == "query" and msg_obj.get("text"):
                                    query_text = msg_obj["text"]
                                    no_audio = msg_obj.get("no_audio", False)
                                    if _WEATHER_RE.search(query_text) or _HANGUP_RE.search(query_text.strip()):
                                        # 如果匹配到天气或退出，走本地拦截和统一业务链路
                                        on_input_transcript(query_text, is_text=True, no_audio=no_audio)
                                    else:
                                        # 如果是普通聊天，直接通过LLM处理
                                        if client:
                                            # 设置音频屏蔽标志
                                            mute_llm_audio = no_audio
                                            
                                            await client.send_event({
                                                "type": "conversation.item.create",
                                                "item": {
                                                    "type": "message",
                                                    "role": "user",
                                                    "content": [{"type": "input_text", "text": query_text}]
                                                }
                                            })
                                            
                                            await client.send_event({"type": "response.create"})
                            except Exception:
                                pass
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                print("[voice_ws] Frontend client gracefully disconnected")
                break
    except Exception as e:
        print(f"[voice_ws] EXCEPTION causing disconnect: {type(e).__name__}: {e}")
        print(f"[voice_ws] EXCEPTION: {type(e).__name__}: {e}")
        traceback.print_exc()
    finally:
        websocket_active = False
        heartbeat_task.cancel()
        timeout_task.cancel()
        if message_task:
            message_task.cancel()
        
        # # 调试：保存输入音频为 wav
        # if len(input_audio_buffer) > 0:
        #     try:
        #         import wave
        #         with wave.open("input_audio_debug.wav", "wb") as wf:
        #             wf.setnchannels(1)
        #             wf.setsampwidth(2)
        #             wf.setframerate(16000)
        #             wf.writeframes(input_audio_buffer)
        #         print(f"[voice_ws] Saved {len(input_audio_buffer)} bytes to input_audio_debug.wav")
        #     except Exception as e:
        #         print(f"[voice_ws] Failed to save input audio wav: {e}")
        
        if client:
            try:
                await client.close()
            except Exception:
                pass


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8765, reload=True)
