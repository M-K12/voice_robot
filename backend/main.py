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
import sys
import json
import time
import asyncio
import base64
import re
import traceback
import queue
import httpx
import uvicorn
import numpy as np
from pathlib import Path
from typing import Optional
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from backend.weather_router import router as weather_router, _parse_weather_text, weather_client
from backend.omni_realtime_client import OmniRealtimeClient, TurnDetectionMode
from backend.audio_manager import AudioManager
from backend.sse_hub import SSEHub, sse_hub
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
QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# Global instances
audio_manager = AudioManager()

# Conversation state
_conversation_active = False
_conversation_lock = asyncio.Lock()

# ──────────────────────────────────────────────
# 配置与工具
# ──────────────────────────────────────────────
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

_WEATHER_FILLER_PATH = Path("backend/static/audio/weather_filler.wav")
_filler_audio_cache = None

_WEATHER_RE = re.compile(r'天气|气温|温度|下雨|下雪|预报|穿衣|降水|风力|冷不冷|热不热|爬山|打球|徒步|露营|出差|出门|室外|户外|防晒|带伞|游泳|下水|玩水|洗车|晾晒')
_CITY_RE = re.compile(r'([^\s，,。！？]{2,6}?)[行]?(?:天气|气温|温度|下雨|下雪|预报|穿衣|降水|风力|冷不冷|热不热|爬山|打球|徒步|露营|出差|室外|户外|游泳|下水|玩水|洗车|晾晒)')
_HANGUP_RE = re.compile(r'^(退出|退下|结束|挂断|再见|拜拜|退朝).*', re.IGNORECASE)

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

async def _extract_city_llm(text: str) -> str:
    api_key = DASHSCOPE_API_KEY
    if not api_key: return "NONE"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{QWEN_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": "qwen-turbo",
                      "messages": [{"role": "system", "content": "提取地市名，只输出名称，无则显NONE。"},
                                   {"role": "user", "content": text}],
                      "temperature": 0.1},
                timeout=2.0)
            return resp.json()["choices"][0]["message"]["content"].strip()
    except:
        return "NONE"

# ──────────────────────────────────────────────
# TTS 播报（通过 AudioManager 扬声器播放）
# ──────────────────────────────────────────────
def _speak_text_to_speaker(text: str, api_key: str = ""):
    """使用 Qwen TTS 合成语音并通过系统扬声器播放"""
    import threading
    def _run_tts():
        try:
            import dashscope
            done_event = threading.Event()
            class _TTSCallback(QwenTtsRealtimeCallback):
                def on_open(self): print("[TTS] Connected.")
                def on_close(self, code, msg): done_event.set()
                def on_event(self, event):
                    if not isinstance(event, dict): return
                    if event.get('type') == 'response.audio.delta':
                        delta = event.get('delta')
                        if delta:
                            audio_manager.play_audio(base64.b64decode(delta))
                    elif event.get('type') == 'response.done':
                        done_event.set()

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
        except Exception as e:
            print(f"[TTS] Error: {e}")
    threading.Thread(target=_run_tts, daemon=True).start()

# ──────────────────────────────────────────────
# 天气处理（后端内部调用，结果通过 SSE 推送）
# ──────────────────────────────────────────────
async def _handle_weather_query(transcript: str):
    """处理天气相关查询：提取城市 → 查天气 → SSE推送数据 → TTS播报"""
    try:
        # 提取城市
        city = await _extract_city_llm(transcript)
        if city == "NONE":
            m = _CITY_RE.search(transcript)
            city = m.group(1) if m else DEFAULT_CITY

        # 查询天气
        raw = await _run_weather_script(city)
        print(f"\n[Weather] 天气结果 ({city}):\n{raw}\n")

        if raw.startswith('{"error"'):
            organized, weather_data = "天气查询失败", None
        else:
            organized, weather_data = raw, _parse_weather_text(raw, city)

        # SSE 推送天气数据给前端
        if weather_data:
            await sse_hub.broadcast("weather_data", {"city": city, "data": weather_data})

        # SSE 推送地理坐标
        lonlat = get_city_lonlat(city)
        if lonlat:
            await sse_hub.broadcast("query_info", {"lonLat": lonlat, "city": city})

        # 播放天气填充音
        global _filler_audio_cache
        if not _filler_audio_cache and _WEATHER_FILLER_PATH.exists():
            with open(_WEATHER_FILLER_PATH, "rb") as f:
                _filler_audio_cache = f.read()[44:]  # skip WAV header
        if _filler_audio_cache:
            audio_manager.play_audio(_filler_audio_cache)

        # TTS 播报天气总结
        tts_queue = queue.Queue()
        _speak_text_to_speaker(tts_queue, DASHSCOPE_API_KEY)

        # 流式获取总结文本并同时喂给 TTS
        try:
            async with httpx.AsyncClient() as client:
                async with client.stream("POST", f"{QWEN_BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {DASHSCOPE_API_KEY}"},
                    json={"model": "qwen-turbo",
                          "messages": [{"role": "system", "content": f"专业天气助手，总结{city}气象建议，纯文本3句内。"},
                                       {"role": "user", "content": f"用户问：{transcript}\n数据：{organized}"}],
                          "stream": True, "temperature": 0.5},
                    timeout=10.0) as resp:
                    full = ""
                    async for line in resp.aiter_lines():
                        if line.startswith("data: "):
                            if "[DONE]" in line: break
                            try:
                                delta = json.loads(line[6:])["choices"][0]["delta"].get("content", "")
                                if delta:
                                    full += delta
                                    tts_queue.put(delta)
                            except: pass
                    tts_queue.put(None)  # Signal TTS done
                    if full:
                        await sse_hub.broadcast("output_transcript", {"text": full, "response_id": f"weather_{int(time.time())}"})
        except:
            tts_queue.put(None)

    except Exception as e:
        print(f"[Weather] Error: {e}")
        traceback.print_exc()

# Conversation interrupt event: set by KWS when wake word detected during active conversation
_kws_interrupt_event: Optional[asyncio.Event] = None

async def kws_loop(kws_queue: asyncio.Queue):
    """
    Continuously reads PCM from AudioManager and feeds to Sherpa-ONNX KWS.
    KWS always receives real mic data (always_real=True), so it can detect
    wake words even while AI is speaking through the speaker.

    On keyword detection:
      - If no conversation active: start new conversation
      - If conversation active: interrupt current playback (wake word interrupt)
    """
    global _kws_interrupt_event

    if not KWS_SPOTTER:
        print("[KWS] No spotter loaded, kws_loop exiting.")
        return

    stream = KWS_SPOTTER.create_stream()
    print("[KWS] 唤醒监听已启动，等待唤醒词...")
    await sse_hub.broadcast("state_change", {"state": "idle"})

    while True:
        try:
            pcm_bytes = await kws_queue.get()

            # Convert to float32 for Sherpa-ONNX
            samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            stream.accept_waveform(16000, samples)

            while KWS_SPOTTER.is_ready(stream):
                KWS_SPOTTER.decode_stream(stream)

            result = KWS_SPOTTER.get_result(stream)
            if result:
                text = getattr(result, 'keyword', str(result))
                if text.strip():
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] [KWS] 检测到唤醒词: {text}")
                    KWS_SPOTTER.reset_stream(stream)

                    if _conversation_active:
                        # Conversation is active: interrupt playback
                        print("[KWS] 对话中检测到唤醒词 → 打断 AI 播放")
                        audio_manager.stop_playback()
                        if _kws_interrupt_event:
                            _kws_interrupt_event.set()
                        await sse_hub.broadcast("interrupt", {})
                    else:
                        # No conversation: start new one
                        await sse_hub.broadcast("wake", {})
                        await sse_hub.broadcast("state_change", {"state": "listening"})
                        await start_conversation()

                        # After conversation ends, reset and resume
                        stream = KWS_SPOTTER.create_stream()
                        print("[KWS] 对话结束，恢复唤醒监听。")
                        await sse_hub.broadcast("state_change", {"state": "idle"})

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[KWS] Error: {e}")
            traceback.print_exc()
            await asyncio.sleep(1)

# ──────────────────────────────────────────────
# 对话会话（唤醒后启动）
# ──────────────────────────────────────────────
async def start_conversation():
    """
    Start a full-duplex conversation session with Omni Realtime API.
    Audio is sourced from AudioManager, responses played through speaker.
    Session ends on hangup command, timeout, or KWS wake word interrupt.
    """
    global _conversation_active, _kws_interrupt_event

    async with _conversation_lock:
        if _conversation_active:
            print("[Conversation] Already active, skipping.")
            return
        _conversation_active = True
        _kws_interrupt_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    api_key = DASHSCOPE_API_KEY
    omni_queue = audio_manager.subscribe()

    last_interaction_time = time.time()
    session_active = True
    handling_weather = False
    weather_triggered = False
    input_transcript_stream = ""
    client_ref = [None]

    tools = [{
        "type": "function", "name": "get_weather",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}
    }]

    # ── Callbacks ──

    async def on_audio(audio_data: bytes):
        nonlocal last_interaction_time
        if not session_active or handling_weather:
            return
        last_interaction_time = time.time()
        b = base64.b64decode(audio_data) if isinstance(audio_data, str) else audio_data
        audio_manager.play_audio(b)

    async def on_interrupt():
        nonlocal last_interaction_time
        last_interaction_time = time.time()
        audio_manager.stop_playback()
        await sse_hub.broadcast("interrupt", {})

    def on_input_transcript_delta(event: dict):
        nonlocal weather_triggered, input_transcript_stream
        if weather_triggered or handling_weather: return
        delta = event.get("delta", "")
        input_transcript_stream += delta
        if _WEATHER_RE.search(input_transcript_stream):
            weather_triggered = True
            asyncio.run_coroutine_threadsafe(_run_fallback_weather(input_transcript_stream), loop)

    def on_input_transcript(transcript: str, is_text: bool = False, no_audio: bool = False):
        nonlocal last_interaction_time, weather_triggered, input_transcript_stream, session_active
        
        final_text = transcript if transcript.strip() else input_transcript_stream
        last_interaction_time = time.time()
        input_transcript_stream = ""

        if not final_text.strip():
            if client_ref[0]:
                asyncio.run_coroutine_threadsafe(client_ref[0].send_event({"type": "response.cancel"}), loop)
            return

        if handling_weather and not _HANGUP_RE.search(final_text):
            return

        # SSE push user transcript
        asyncio.run_coroutine_threadsafe(
            sse_hub.broadcast("input_transcript", {"text": final_text}), loop
        )

        if _WEATHER_RE.search(final_text) or _HANGUP_RE.search(final_text):
            if client_ref[0]:
                asyncio.run_coroutine_threadsafe(client_ref[0].send_event({"type": "response.cancel"}), loop)

            if _HANGUP_RE.search(final_text):
                asyncio.run_coroutine_threadsafe(sse_hub.broadcast("hangup", {}), loop)
                session_active = False
            elif not weather_triggered:
                asyncio.run_coroutine_threadsafe(_run_fallback_weather(final_text), loop)

            weather_triggered = False

    def on_output_transcript(transcript: str, response_id: str = ""):
        if not handling_weather and _WEATHER_RE.search(transcript):
            on_input_transcript(transcript)
            return
        asyncio.run_coroutine_threadsafe(
            sse_hub.broadcast("output_transcript", {"text": transcript, "response_id": response_id}), loop
        )

    async def _run_fallback_weather(transcript):
        nonlocal handling_weather
        if handling_weather: return
        handling_weather = True
        try:
            if client_ref[0]:
                await client_ref[0].send_event({"type": "response.cancel"})
            audio_manager.stop_playback()
            await _handle_weather_query(transcript)
        except Exception as e:
            print(f"[Weather] Fallback error: {e}")
        finally:
            await asyncio.sleep(3)
            handling_weather = False

    # ── Start Omni session ──
    client = None
    try:
        client = OmniRealtimeClient(
            base_url="wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
            api_key=api_key,
            model="qwen3-omni-flash-realtime",
            on_audio_delta=lambda d: asyncio.create_task(on_audio(d)),
            on_interrupt=lambda: asyncio.create_task(on_interrupt()),
            on_input_transcript=on_input_transcript,
            on_output_transcript=on_output_transcript,
            turn_detection_mode=TurnDetectionMode.SERVER_VAD,
            extra_event_handlers={
                "conversation.item.input_audio_transcription.delta": on_input_transcript_delta
            }
        )
        client_ref[0] = client
        await client.connect()
        await client.update_session({
            "tools": tools,
            "enable_search": True,
            "instructions": "精简专业助手。天气查询立即口头确认。禁Markdown，禁THINK。字数限100内。"
        })

        # Start message handler
        msg_task = asyncio.create_task(client.handle_messages())

        # Audio feeding loop: read from omni_queue and send to Omni
        async def feed_audio_to_omni():
            while session_active:
                try:
                    pcm_bytes = await asyncio.wait_for(omni_queue.get(), timeout=1.0)
                    await client.send_event({
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(pcm_bytes).decode()
                    })
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break

        feed_task = asyncio.create_task(feed_audio_to_omni())

        # Timeout check
        async def check_timeout():
            nonlocal session_active
            while session_active:
                await asyncio.sleep(1)
                if time.time() - last_interaction_time > 30:
                    print("[Conversation] 30s timeout, hanging up.")
                    await sse_hub.broadcast("hangup", {})
                    session_active = False
                    break

        timeout_task = asyncio.create_task(check_timeout())

        # Wait for session to end (also check KWS wake word interrupt)
        while session_active:
            await asyncio.sleep(0.5)
            # Check if KWS detected wake word during playback
            if _kws_interrupt_event and _kws_interrupt_event.is_set():
                print("[Conversation] KWS 唤醒词打断 → 停止播放，恢复对话")
                _kws_interrupt_event.clear()
                audio_manager.stop_playback()
                last_interaction_time = time.time()  # reset timeout

        # Cleanup
        feed_task.cancel()
        timeout_task.cancel()
        msg_task.cancel()

    except Exception as e:
        print(f"[Conversation] Error: {e}")
        traceback.print_exc()
    finally:
        if client:
            try:
                await client.close()
            except Exception:
                pass
        audio_manager.unsubscribe(omni_queue)
        audio_manager.stop_playback()
        _conversation_active = False

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
        "kws_loaded": KWS_SPOTTER is not None,
        "audio_running": audio_manager.is_running,
        "sse_clients": sse_hub.client_count,
    }

# ──────────────────────────────────────────────
# 启动与关闭
# ──────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    await update_default_city()
    init_kws_spotter()

    # Start audio manager (system mic + speaker)
    await audio_manager.start()

    # Subscribe KWS to audio stream (always_real: receives mic data even during AI playback)
    kws_queue = audio_manager.subscribe(always_real=True)
    asyncio.create_task(kws_loop(kws_queue))

    print("=" * 50)
    print("Voice Robot Backend v2.0 — 前后端分离模式")
    print(f"  默认城市: {DEFAULT_CITY}")
    print(f"  KWS 模型: {'已加载' if KWS_SPOTTER else '未加载'}")
    print(f"  SSE 端点: /sse")
    print("=" * 50)

@app.on_event("shutdown")
async def shutdown_event():
    await audio_manager.stop()

if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8765, reload=True)
