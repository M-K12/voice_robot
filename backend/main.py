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
import json
import time
import asyncio
import base64
import subprocess
import shutil
import traceback
import re
import httpx
import uvicorn
from pathlib import Path
from typing import AsyncIterator, List, Optional
from datetime import datetime
import numpy as np

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.weather_router import router as weather_router, _parse_weather_text, weather_client
from backend.omni_realtime_client import OmniRealtimeClient, TurnDetectionMode
from dashscope.audio.qwen_tts_realtime import QwenTtsRealtime, QwenTtsRealtimeCallback

# ──────────────────────────────────────────────
# Sherpa-ONNX KWS 唤醒模型初始化
# ──────────────────────────────────────────────
if sys.platform == "win32":
    import importlib.util
    spec_sherpa = importlib.util.find_spec("sherpa_onnx")
    if spec_sherpa and spec_sherpa.origin:
        sherpa_onnx_dir = Path(spec_sherpa.origin).parent
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(str(sherpa_onnx_dir))
            except Exception: pass
        os.environ["PATH"] = str(sherpa_onnx_dir) + os.pathsep + os.environ.get("PATH", "")
    
    spec_ort = importlib.util.find_spec("onnxruntime")
    if spec_ort and spec_ort.origin:
        ort_dir = Path(spec_ort.origin).parent / "capi"
        if ort_dir.exists():
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(str(ort_dir))
                except Exception: pass
            os.environ["PATH"] = str(ort_dir) + os.pathsep + os.environ.get("PATH", "")

try:
    import sherpa_onnx
except ImportError:
    sherpa_onnx = None

KWS_SPOTTER = None
def init_kws_spotter():
    global KWS_SPOTTER
    if not sherpa_onnx:
        return
    
    try:
        base_dir = Path(__file__).resolve().parent.parent.parent
        cl_test_dir = base_dir / "cl_test"
        model_dir = cl_test_dir / "models" / "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"
        
        if not model_dir.exists():
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
        print(f"[KWS] 加载唤醒模型失败: {e}")

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

DEFAULT_CITY = "北京"

async def update_default_city():
    global DEFAULT_CITY
    config_path = (Path(__file__).parent.parent / "config.json").resolve()
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)
                city = config_data.get("default_city")
                if city:
                    DEFAULT_CITY = city
                    return
        except Exception: pass

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get("http://ip-api.com/json/?lang=zh-CN", timeout=5.0)
            data = resp.json()
            if data.get("status") == "success":
                city = data.get("city", "")
                if city:
                    if city.endswith("市"):
                        city = city[:-1]
                    DEFAULT_CITY = city
    except Exception: pass

@app.on_event("startup")
async def startup_event():
    await update_default_city()
    init_kws_spotter()

# ──────────────────────────────────────────────
# 数据模型
# ──────────────────────────────────────────────
class ChatTurn(BaseModel):
    role: str
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

async def _stream_qwen(messages: list[dict], api_key: str) -> AsyncIterator[str]:
    if not api_key:
        yield 'data: {"type": "error", "message": "请填写 API Key"}\n\n'
        return
        
    try:
        from openai import AsyncOpenAI
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
    auth = request.headers.get("Authorization", "")
    api_key = auth[len("Bearer "):].strip() if auth.startswith("Bearer ") else DASHSCOPE_API_KEY
    messages: list[dict] = []
    if req.system: messages.append({"role": "system", "content": req.system})
    for turn in req.history: messages.append({"role": turn.role, "content": turn.content})
    messages.append({"role": "user", "content": req.message})
    return StreamingResponse(_stream_qwen(messages, api_key), media_type="text/event-stream")

@app.get("/health")
def health_check():
    return {"status": "ok", "api_key_set": bool(os.getenv("DASHSCOPE_API_KEY"))}

@app.post("/extract_city")
async def extract_city(req: CityExtractRequest, request: Request):
    auth = request.headers.get("Authorization", "")
    api_key = auth[len("Bearer "):].strip() if auth.startswith("Bearer ") else os.getenv("DASHSCOPE_API_KEY")
    if not api_key: raise HTTPException(status_code=500, detail="Missing API KEY")
    import openai
    client = openai.AsyncOpenAI(api_key=api_key, base_url=QWEN_BASE_URL)
    try:
        response = await client.chat.completions.create(
            model="qwen-turbo",
            messages=[
                {"role": "system", "content": "你是一个地名抓取机器。请将用户句子中提到的地点转换为地级市/直辖市（例如：萧山->杭州），只能输出最终的纯中文名字。"},
                {"role": "user", "content": req.message}
            ],
            stream=False, temperature=0.1
        )
        return {"city": response.choices[0].message.content.strip()}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

# ──────────────────────────────────────────────
# 天气工具与辅助
# ──────────────────────────────────────────────
_WEATHER_FILLER_PATH = Path("backend/static/audio/weather_filler.wav")
_filler_audio_cache = None

async def _play_filler_audio(websocket: WebSocket):
    global _filler_audio_cache
    try:
        if not _filler_audio_cache and _WEATHER_FILLER_PATH.exists():
            with open(_WEATHER_FILLER_PATH, "rb") as f:
                _filler_audio_cache = f.read()[44:]
        if _filler_audio_cache: await websocket.send_bytes(_filler_audio_cache)
    except Exception: pass

async def _run_weather_script(city: str) -> str:
    if not weather_client: return json.dumps({"error": "Weather client not available"})
    try:
        raw = await weather_client.get_city_weather(city)
        if not raw or "[错误]" in raw: return json.dumps({"error": raw or "Unknown error"})
        return raw
    except Exception as e: return json.dumps({"error": str(e)})

_CITY_TO_AREACODE = {}
_AREACODE_TO_STATION = {}
_DICT_LOADED = False

def _load_station_dicts_for_main():
    global _CITY_TO_AREACODE, _AREACODE_TO_STATION, _DICT_LOADED
    if _DICT_LOADED: return
    base_dir = Path(__file__).parent.parent / "spd-weather" / "assets"
    try:
        with open(base_dir / "city_to_areacode.json", "r", encoding="utf-8") as f:
            _CITY_TO_AREACODE = json.load(f)
        with open(base_dir / "areacode_to_station.json", "r", encoding="utf-8") as f:
            _AREACODE_TO_STATION = json.load(f)
        _DICT_LOADED = True
    except Exception: pass

def get_city_lonlat(city: str) -> Optional[list[float]]:
    _load_station_dicts_for_main()
    candidates = [city, city.replace("市", ""), city + "市"]
    area_code = None
    for cand in candidates:
        area_code = _CITY_TO_AREACODE.get(cand)
        if area_code: break
    if not area_code: return None
    station = _AREACODE_TO_STATION.get(area_code)
    if not station: return None
    lat, lon = station.get("lat"), station.get("lon")
    if lat is not None and lon is not None: return [lon, lat]
    return None

def _speak_text_realtime(text: str, websocket: WebSocket, loop: asyncio.AbstractEventLoop, tts_state: dict = None, client=None, api_key: str = ""):
    import threading
    def _run_tts():
        try:
            import dashscope
            if tts_state is not None: tts_state["playing"] = True
            if client is not None:
                asyncio.run_coroutine_threadsafe(client.send_event({"type": "input_audio_buffer.clear"}), loop)
            done_event = threading.Event()
            class _TTSCallback(QwenTtsRealtimeCallback):
                def on_open(self): print("[WeatherTTS] Connected.")
                def on_close(self, code, msg): done_event.set()
                def on_event(self, event):
                    if not isinstance(event, dict): return
                    if event.get('type') == 'response.audio.delta':
                        delta = event.get('delta')
                        if delta:
                            asyncio.run_coroutine_threadsafe(websocket.send_bytes(base64.b64decode(delta)), loop)
                    elif event.get('type') == 'response.done': done_event.set()
            dashscope.api_key = api_key if api_key else os.getenv("DASHSCOPE_API_KEY", "")
            tts_client = QwenTtsRealtime(model='qwen3-tts-flash-realtime', callback=_TTSCallback())
            tts_client.connect()
            tts_client.update_session(voice="Cherry")
            if isinstance(text, str):
                cleaned = re.sub(r'\s+', '', text)
                if cleaned: tts_client.append_text(cleaned)
            else:
                while True:
                    chunk = text.get()
                    if chunk is None: break
                    cleaned = re.sub(r'\s+', '', chunk)
                    if cleaned: tts_client.append_text(cleaned)
            tts_client.finish()
            done_event.wait(timeout=30.0)
            try: tts_client.close()
            except Exception: pass
        except Exception as e: print(f"[WeatherTTS] Error: {e}")
        finally:
            if tts_state is not None: tts_state["playing"] = False
    threading.Thread(target=_run_tts, daemon=True).start()

# ──────────────────────────────────────────────
# WebSocket 端点
# ──────────────────────────────────────────────

@app.websocket("/ws/kws")
async def kws_ws(websocket: WebSocket, token: Optional[str] = None):
    await websocket.accept()
    if not KWS_SPOTTER:
        await websocket.close(reason="KWS Model not loaded")
        return
    stream = KWS_SPOTTER.create_stream()
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect": break
            if "bytes" in message and message["bytes"]:
                samples = np.frombuffer(message["bytes"], dtype=np.int16).astype(np.float32) / 32768.0
                stream.accept_waveform(16000, samples)
                while KWS_SPOTTER.is_ready(stream): KWS_SPOTTER.decode_stream(stream)
                result = KWS_SPOTTER.get_result(stream)
                if result:
                    text = getattr(result, 'keyword', str(result))
                    if text.strip():
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] [KWS] 检测到关键词: {text}")
                        await websocket.send_json({"type": "result", "text": text, "is_final": True})
                        KWS_SPOTTER.reset_stream(stream)
    except WebSocketDisconnect: pass
    except Exception as e: print(f"[ws/kws] EXCEPTION: {e}")

@app.websocket("/voice_ws")
async def voice_ws(websocket: WebSocket, voice: Optional[str] = None, token: Optional[str] = None):
    await websocket.accept()
    websocket_active = True
    loop = asyncio.get_running_loop()
    
    tts_state = {"playing": False}
    handling_weather = False
    weather_triggered = False
    input_transcript_stream = ""
    last_interaction_time = time.time()
    api_key = token if token else os.getenv("DASHSCOPE_API_KEY", "")
    intercept_state = "buffering" 
    intercept_buffer = []
    client_ref = [None]
    
    _WEATHER_RE = re.compile(r'天气|气温|温度|下雨|下雪|预报|穿衣|降水|风力|冷不冷|热不热|爬山|打球|徒步|露营|出差|出门|室外|户外|防晒|带伞|游泳|下水|玩水|洗车|晾晒')
    _CITY_RE = re.compile(r'([^\s，,。！？]{2,6}?)[行]?(?:天气|气温|温度|下雨|下雪|预报|穿衣|降水|风力|冷不冷|热不热|爬山|打球|徒步|露营|出差|室外|户外|游泳|下水|玩水|洗车|晾晒)')
    _HANGUP_RE = re.compile(r'^(退出|退下|结束|挂断|再见|拜拜|退朝).*', re.IGNORECASE)

    tools = [{
        "type": "function", "name": "get_weather",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}
    }]

    async def _extract_city_llm(text: str) -> str:
        if not api_key: return "NONE"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(f"{QWEN_BASE_URL}/chat/completions", headers={"Authorization": f"Bearer {api_key}"},
                    json={"model": "qwen-turbo", "messages": [{"role": "system", "content": "提取地市名，只输出名称，无则显NONE。"}, {"role": "user", "content": text}], "temperature": 0.1}, timeout=2.0)
                return resp.json()["choices"][0]["message"]["content"].strip()
        except: return "NONE"

    async def _stream_weather_and_speak(text: str, city: str, api_key: str, query: str, no_audio: bool, queue=None):
        if no_audio: return
        try:
            async with httpx.AsyncClient() as client:
                async with client.stream("POST", f"{QWEN_BASE_URL}/chat/completions", headers={"Authorization": f"Bearer {api_key}"},
                    json={"model": "qwen-turbo", "messages": [{"role": "system", "content": f"专业天气助手，总结{city}气象建议，纯文本3句内。"}, {"role": "user", "content": f"用户问：{query}\n数据：{text}"}], "stream": True, "temperature": 0.5}, timeout=10.0) as resp:
                    full = ""
                    async for line in resp.aiter_lines():
                        if line.startswith("data: "):
                            if "[DONE]" in line: break
                            try:
                                delta = json.loads(line[6:])["choices"][0]["delta"].get("content", "")
                                if delta:
                                    full += delta
                                    if queue: queue.put(delta)
                            except: pass
                    if queue: queue.put(None)
                    if websocket_active: await websocket.send_text(json.dumps({"type": "output_transcript", "data": full}))
        except:
            if queue: queue.put(None)

    async def on_audio(audio_data: bytes):
        nonlocal websocket_active, last_interaction_time
        if not websocket_active or handling_weather or intercept_state == "intercepted": return
        last_interaction_time = time.time()
        async def _send():
            try:
                b = base64.b64decode(audio_data) if isinstance(audio_data, str) else audio_data
                if websocket_active: await websocket.send_bytes(b)
            except: pass
        if intercept_state == "buffering": intercept_buffer.append(_send)
        else: asyncio.run_coroutine_threadsafe(_send(), loop)

    async def on_interrupt():
        nonlocal intercept_state, last_interaction_time
        intercept_state = "buffering"
        intercept_buffer.clear()
        last_interaction_time = time.time()
        if websocket_active:
            try: await websocket.send_text(json.dumps({"type": "interrupt"}))
            except: pass

    async def _run_fallback_weather(transcript, no_audio=False):
        nonlocal handling_weather
        if handling_weather: return
        handling_weather = True
        try:
            if client_ref[0]: await client_ref[0].send_event({"type": "response.cancel"})
            await on_interrupt()
            filler_task = asyncio.create_task(_play_filler_audio(websocket)) if not no_audio else None
            import queue
            q = queue.Queue() if not no_audio else None
            if not no_audio: _speak_text_realtime(q, websocket, loop, tts_state, client_ref[0], api_key)
            city = await _extract_city_llm(transcript)
            if city == "NONE":
                m = _CITY_RE.search(transcript)
                city = m.group(1) if m else DEFAULT_CITY
            raw = await _run_weather_script(city)
            
            # --- 即时打印天气结果 ---
            print(f"\n[DEBUG] 实时天气工具返回结果 ({city}):\n{raw}\n")
            
            if raw.startswith('{"error"'): organized, weather_data = "天气查询失败", None
            else: organized, weather_data = raw, _parse_weather_text(raw, city)
            if websocket_active and weather_data:
                await websocket.send_text(json.dumps({"type": "weather_data", "city": city, "data": weather_data}))
            if not no_audio: await _stream_weather_and_speak(organized, city, api_key, transcript, False, q)
            if filler_task: await filler_task
        except: pass
        finally:
            await asyncio.sleep(3)
            handling_weather = False

    def on_input_transcript_delta(event: dict):
        nonlocal weather_triggered, input_transcript_stream
        if weather_triggered or handling_weather: return
        delta = event.get("delta", "")
        input_transcript_stream += delta
        if _WEATHER_RE.search(input_transcript_stream):
            weather_triggered = True
            asyncio.run_coroutine_threadsafe(_run_fallback_weather(input_transcript_stream), loop)

    def on_input_transcript(transcript: str, is_text: bool = False, no_audio: bool = False):
        nonlocal last_interaction_time, weather_triggered, intercept_state, input_transcript_stream, websocket_active
        
        # 某些大模型（如DashScope）在 completed 事件中 transcript 字段可能为空，这里采用 delta 拼接的结果作为后备
        final_text = transcript if transcript.strip() else input_transcript_stream
        
        last_interaction_time = time.time()
        input_transcript_stream = ""  # 清理流式累积的缓存，防止上个回合的文本残留导致重复回答
        
        if not final_text.strip():
            # 纯环境噪音触发了VAD但没有任何有效文字，此时主动打断大模型，防止模型产生幻觉重复上一句内容
            if client_ref[0]: asyncio.run_coroutine_threadsafe(client_ref[0].send_event({"type": "response.cancel"}), loop)
            return
        
        # 物理回声消除 (Acoustic Echo Blocking)：当系统正在播放本地方案的天气语音时，
        # 大模型的全双工麦克风会听到系统自己发出的声音。此处过滤掉所有非高优打断的指令。
        if handling_weather and not _HANGUP_RE.search(final_text):
            return
        
        if not is_text and websocket_active:
            asyncio.run_coroutine_threadsafe(
                websocket.send_text(json.dumps({"type": "input_transcript", "data": final_text})), loop
            )

        if _WEATHER_RE.search(final_text) or _HANGUP_RE.search(final_text):
            intercept_state = "intercepted"
            intercept_buffer.clear()
            if client_ref[0]: asyncio.run_coroutine_threadsafe(client_ref[0].send_event({"type": "response.cancel"}), loop)
            asyncio.run_coroutine_threadsafe(websocket.send_text(json.dumps({"type": "retract_bot"})), loop)
            if _HANGUP_RE.search(final_text): 
                asyncio.run_coroutine_threadsafe(websocket.send_text(json.dumps({"type": "hangup"})), loop)
                websocket_active = False # 关闭
            elif not weather_triggered:
                asyncio.run_coroutine_threadsafe(_run_fallback_weather(final_text, no_audio), loop)
            weather_triggered = False
        else:
            intercept_state = "passthrough"
            copy = list(intercept_buffer); intercept_buffer.clear()
            async def _flush(): 
                for fn in copy: await fn()
            asyncio.run_coroutine_threadsafe(_flush(), loop)

    def on_output_transcript(transcript: str, response_id: str = ""):
        nonlocal intercept_state
        if not handling_weather and _WEATHER_RE.search(transcript):
            on_input_transcript(transcript); return
        async def _send():
            if websocket_active: await websocket.send_text(json.dumps({"type": "output_transcript", "data": transcript, "response_id": response_id}))
        if intercept_state == "buffering": intercept_buffer.append(_send)
        else: asyncio.run_coroutine_threadsafe(_send(), loop)

    async def send_heartbeat():
        while websocket_active:
            await asyncio.sleep(25)
            try: await websocket.send_text(json.dumps({"type": "ping"}))
            except: break

    async def check_timeout():
        nonlocal websocket_active
        while websocket_active:
            await asyncio.sleep(1)
            if (client_ref[0] and getattr(client_ref[0], '_is_responding', False)) or tts_state.get("playing"):
                nonlocal last_interaction_time
                last_interaction_time = time.time(); continue
            if time.time() - last_interaction_time > 30:
                try: await websocket.send_text(json.dumps({"type": "timeout_hangup"}))
                except: pass
                websocket_active = False; break

    heartbeat_task = asyncio.create_task(send_heartbeat())
    timeout_task = asyncio.create_task(check_timeout())
    
    try:
        client = OmniRealtimeClient(
            base_url="wss://dashscope.aliyuncs.com/api-ws/v1/realtime", api_key=api_key, model="qwen3-omni-flash-realtime",
            on_audio_delta=lambda d: asyncio.create_task(on_audio(d)),
            on_interrupt=lambda: asyncio.create_task(on_interrupt()),
            on_input_transcript=on_input_transcript, on_output_transcript=on_output_transcript,
            turn_detection_mode=TurnDetectionMode.SERVER_VAD,
            extra_event_handlers={"conversation.item.input_audio_transcription.delta": on_input_transcript_delta}
        )
        client_ref[0] = client
        await client.connect()
        await client.update_session({
            "tools": tools, "enable_search": True,
            "instructions": "精简专业助手。天气查询立即口头确认。禁Markdown，禁THINK。字数限100内。"
        })
        msg_task = asyncio.create_task(client.handle_messages())
        while websocket_active:
            try:
                msg = await asyncio.wait_for(websocket.receive(), timeout=1.0)
                if msg["type"] == "websocket.disconnect": break
                if msg["type"] == "websocket.receive":
                    if "bytes" in msg:
                        data = msg["bytes"]
                        if len(data) > 1 and data[0] == 0 and not tts_state.get("playing"):
                            await client.send_event({"type": "input_audio_buffer.append", "audio": base64.b64encode(data[1:]).decode()})
                    elif "text" in msg:
                        txt = msg["text"]
                        if txt not in ("pong", '{"type":"pong"}'):
                            try:
                                obj = json.loads(txt)
                                if obj.get("type") == "query":
                                    on_input_transcript(obj["text"], is_text=True, no_audio=obj.get("no_audio", False))
                                    if not (_WEATHER_RE.search(obj["text"]) or _HANGUP_RE.search(obj["text"])):
                                        await client.send_event({"type": "conversation.item.create", "item": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": obj["text"]}]}})
                                        await client.send_event({"type": "response.create"})
                            except: pass
            except asyncio.TimeoutError: continue
    except Exception as e: print(f"[voice_ws] EXCEPTION: {e}")
    finally:
        websocket_active = False
        heartbeat_task.cancel(); timeout_task.cancel()
        if client: await client.close()

# --- WebSocket 路由已通过装饰器定义 ---

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8765, reload=True)
