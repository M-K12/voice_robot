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

import threading
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
        base_dir = Path(__file__).resolve().parent.parent
        sherpa_dir = base_dir / "sherpa"
        model_dir = sherpa_dir / "models" / "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"

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
LOGIC_MODEL = "qwen-plus"  # 推荐使用 plus，速度更快且足智多谋

# Global instances
audio_manager = AudioManager()

# Conversation state
_conversation_active = False # 控制语音会话生命周期
_last_ai_summary = ""          # 记录机器人上一次播报的文本，用于消除回波干扰
_current_session_id = None
_last_interaction_time = 0     # 用于超时挂断逻辑
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

def clean_echo_text(text: str) -> str:
    """简单回波消除工具"""
    if _last_ai_summary and len(text) > 5:
        # 检查输入是否包含上一轮回答的片段
        if _last_ai_summary in text:
            return text.replace(_last_ai_summary, "").strip()
        # 检查末尾重叠
        for i in range(min(len(text), 15), 2, -1):
            if _last_ai_summary.endswith(text[:i]):
                return text[i:].strip()
    return text

_WOZAI_AUDIO_PATH = Path("backend/static/audio/wozai.wav")
_wozai_audio_cache = None

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

# ──────────────────────────────────────────────
# TTS 播报（通过 AudioManager 扬声器播放）
# ──────────────────────────────────────────────
_active_tts_stop_event: Optional[threading.Event] = None
_tts_lock = threading.Lock()

def _speak_text_to_speaker(text: str | queue.Queue, api_key: str = ""):
    global _active_tts_stop_event
    
    this_stop_event = threading.Event()
    
    with _tts_lock:
        if _active_tts_stop_event:
            _active_tts_stop_event.set()
        _active_tts_stop_event = this_stop_event

    def _run_tts():
        try:
            import dashscope
            done_event = threading.Event()
            class _TTSCallback(QwenTtsRealtimeCallback):
                def on_open(self): print("  \033[94m[TTS] 已连接至阿里语音合成服务。\033[0m")
                def on_close(self, code, msg): done_event.set()
                def on_event(self, event):
                    if not isinstance(event, dict): return
                    if this_stop_event.is_set(): return
                        
                    if event.get('type') == 'response.audio.delta':
                        delta = event.get('delta')
                        if delta:
                            audio_manager.play_audio(base64.b64decode(delta))
                    elif event.get('type') == 'response.done':
                        done_event.set()
                def on_error(self, msg):
                    print(f"  \033[91m[TTS] SSE 错误: {msg}\033[0m")
                    done_event.set()

            dashscope.api_key = api_key if api_key else os.getenv("DASHSCOPE_API_KEY", "")
            tts_client = QwenTtsRealtime(model='qwen3-tts-flash-realtime', callback=_TTSCallback())
            tts_client.connect()
            tts_client.update_session(voice="Cherry")
            
            if isinstance(text, str):
                cleaned = re.sub(r'\s+', '', text)
                if cleaned and not this_stop_event.is_set(): 
                    tts_client.append_text(cleaned)
            else:
                while not this_stop_event.is_set():
                    try:
                        chunk = text.get(timeout=0.05)
                    except queue.Empty:
                        continue
                        
                    if chunk is None: break
                    cleaned = re.sub(r'\s+', '', chunk)
                    if cleaned: tts_client.append_text(cleaned)
            
            if this_stop_event.is_set():
                try: tts_client.close()
                except Exception: pass
                return

            tts_client.finish()
            done_event.wait(timeout=30.0)
            
            try: tts_client.close()
            except Exception: pass
        except Exception as e:
            print(f"  \033[91m[TTS] 运行时错误: {e}\033[0m")
    threading.Thread(target=_run_tts, daemon=True).start()

# ──────────────────────────────────────────────
# 天气处理（后端内部调用，结果通过 SSE 推送）
# ──────────────────────────────────────────────
async def _handle_weather_query(transcript: str, history: list = None):
    try:
        print(f"  \033[94m[TEXT LLM] 开始处理请求: {transcript}\033[0m")
        
        city_match = re.search(r'([^\s，,。！？]{2,6}?)(?:天气|气温|温度|下雨|下雪)', transcript)
        potential_city = city_match.group(1) if city_match else DEFAULT_CITY
        lonlat = get_city_lonlat(potential_city)
        if lonlat:
            await sse_hub.broadcast("query_info", {"lonLat": lonlat, "address": potential_city})

        tts_queue = queue.Queue()
        summary_chunks = []
        
        def _tts_wrapper(q):
            _speak_text_to_speaker(q, DASHSCOPE_API_KEY)
        
        _tts_wrapper(tts_queue)

        tools = [{
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "获取指定城市的天气信息",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "城市名称，如北京、上海"}
                    },
                    "required": ["city"]
                }
            }
        }]

        anti_echo_prompt = (
            "【重要指令】你是一个语音助手的核心大脑。用户输入中可能包含你上一轮回答的回波转写。"
            "如果输入内容的前半部分看起来是你刚说过的陈述句，请直接忽略，仅针对末尾最新的城市提问、新指令或补全信息进行回应。"
            "严禁重复回答已经回答过的内容。"
        )

        messages = [
            {"role": "system", "content": f"你是一个专业的智能语音助手。{anti_echo_prompt} 总结气象建议，纯文本3句内。负温度必须说'零下X度'。当前默认城市：{DEFAULT_CITY}"}
        ]
        if history:
            messages.extend(history[-6:])
        messages.append({"role": "user", "content": transcript})

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{QWEN_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {DASHSCOPE_API_KEY}"},
                json={
                    "model": LOGIC_MODEL,
                    "messages": messages,
                    "tools": tools,
                    "tool_choice": "auto"
                },
                timeout=10.0
            )
            resp_json = response.json()
            if "choices" not in resp_json:
                tts_queue.put(None)
                return None

            message = resp_json["choices"][0]["message"]

            if "tool_calls" in message:
                for tool_call in message["tool_calls"]:
                    if tool_call["function"]["name"] == "get_weather":
                        args = json.loads(tool_call["function"]["arguments"])
                        city = args.get("city", potential_city)
                        weather_raw = await _run_weather_script(city)
                        weather_data = _parse_weather_text(weather_raw, city)
                        
                        if weather_data:
                            await sse_hub.broadcast("weather_data", {"city": city, "data": weather_data})
                        
                        messages.append(message)
                        messages.append({
                            "role": "tool",
                            "content": weather_raw,
                            "tool_call_id": tool_call["id"]
                        })

            async with client.stream(
                "POST", f"{QWEN_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {DASHSCOPE_API_KEY}"},
                json={
                    "model": LOGIC_MODEL,
                    "messages": messages,
                    "stream": True,
                    "temperature": 0.5
                },
                timeout=15.0
            ) as resp:
                full_content = ""
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        if "[DONE]" in line: break
                        try:
                            delta = json.loads(line[6:])["choices"][0]["delta"].get("content", "")
                            if delta:
                                full_content += delta
                                summary_chunks.append(delta)
                                tts_delta = re.sub(r'(?<![\d])-([\d]+\.?[\d]*)', r'零下\1', delta)
                                tts_queue.put(tts_delta)
                        except: pass
                
                # 播报结束后，保存汇总摘要用于下一轮去噪
                if summary_chunks:
                    global _last_ai_summary
                    _last_ai_summary = "".join(summary_chunks)
                    # print(f"  \033[90m[Anti-Echo] 已存储上轮摘要: {_last_ai_summary[:20]}...\033[0m")

                tts_queue.put(None)
                
                if full_content:
                    await sse_hub.broadcast("output_transcript", {"text": full_content, "response_id": f"max_{int(time.time())}"})
                    return full_content

    except Exception as e:
        print(f"[_handle_weather_query] 错误: {e}")
        traceback.print_exc()
        if 'tts_queue' in locals(): tts_queue.put(None)
    return None

_kws_interrupt_event: Optional[asyncio.Event] = None

async def kws_loop(kws_queue: asyncio.Queue):
    global _kws_interrupt_event

    if not KWS_SPOTTER:
        print("[KWS] No spotter loaded, kws_loop exiting.")
        return

    stream = KWS_SPOTTER.create_stream()
    print("[KWS] 唤醒监听已启动，等待唤醒词...")
    await sse_hub.broadcast("state_change", {"state": "idle"})

    async def _run_conversation():
        """Wrapper to run conversation and broadcast state when done."""
        try:
            await start_conversation()
        finally:
            print("[KWS] 对话结束，恢复唤醒监听。")
            await sse_hub.broadcast("state_change", {"state": "idle"})

    while True:
        try:
            pcm_bytes = await kws_queue.get()
            samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            stream.accept_waveform(16000, samples)

            while KWS_SPOTTER.is_ready(stream):
                KWS_SPOTTER.decode_stream(stream)

            result = KWS_SPOTTER.get_result(stream)
            if result:
                text = getattr(result, 'keyword', str(result))
                if text.strip():
                    print(f"\n\033[92m✨ [WAKE] 检测到唤醒词: {text.strip()} ({datetime.now().strftime('%H:%M:%S')})\033[0m")
                    KWS_SPOTTER.reset_stream(stream)

                    global _wozai_audio_cache
                    if not _wozai_audio_cache and _WOZAI_AUDIO_PATH.exists():
                        with open(_WOZAI_AUDIO_PATH, "rb") as _f:
                            _wozai_audio_cache = _f.read()[44:]

                    if _conversation_active:
                        print(f"\033[93m⚡ [INTERRUPT] 对话中再次唤醒 -> 打断 AI 播放\033[0m")
                        global _active_tts_stop_event
                        if _active_tts_stop_event:
                            _active_tts_stop_event.set()
                        audio_manager.stop_playback()
                        if _wozai_audio_cache:
                            audio_manager.play_audio(_wozai_audio_cache)
                        if _kws_interrupt_event:
                            _kws_interrupt_event.set()
                    else:
                        print(f"\033[96m🚀 [SESSION] 启动新对话会话\033[0m")
                        await sse_hub.broadcast("wake", {})
                        await sse_hub.broadcast("state_change", {"state": "listening"})
                        if _wozai_audio_cache:
                            audio_manager.play_audio(_wozai_audio_cache)
                        asyncio.create_task(_run_conversation())

        except asyncio.CancelledError:
            break
        except Exception as e:
            await asyncio.sleep(1)

async def start_conversation():
    global _conversation_active, _kws_interrupt_event

    async with _conversation_lock:
        if _conversation_active:
            return
        _conversation_active = True
        _kws_interrupt_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    api_key = DASHSCOPE_API_KEY
    omni_queue = audio_manager.subscribe()

    last_interaction_time = time.time()
    session_active = True
    _current_intent_task: Optional[asyncio.Task] = None  # 当前正在执行的意图任务
    input_transcript_stream = ""
    tag_parsed = False
    current_intent = None
    client_ref = [None]
    session_history = []
    
    def stop_for_interruption(intent=None):
        nonlocal last_interaction_time
        if intent == "IGNORE":
            return False
            
        if audio_manager.is_running:
            print(f"\033[93m[Semantic Interrupt] 意图={intent} -> 停止当前 TTS 播报\033[0m")
            if _active_tts_stop_event:
                _active_tts_stop_event.set()
            audio_manager.stop_playback()
            last_interaction_time = time.time()
            return True
        return False

    def on_text_delta(delta: str):
        nonlocal input_transcript_stream, tag_parsed, current_intent
        input_transcript_stream += delta
        
        if not tag_parsed and "]" in input_transcript_stream:
            match = re.search(r'\[(WEATHER|EXIT|IGNORE|OTHER)\]', input_transcript_stream)
            if match:
                current_intent = match.group(1)
                tag_parsed = True
                print(f"\033[95m[Router] 流式识别到意图: {current_intent}\033[0m")
                if current_intent != "IGNORE":
                    stop_for_interruption(current_intent)

    def on_response_done(response):
        """模型输出完成：从 input_transcript_stream 读取已解析的意图并分发。"""
        nonlocal current_intent, input_transcript_stream, tag_parsed, last_interaction_time, _current_intent_task, session_active
        global _last_ai_summary

        # 使用 on_text_delta 已经流式累积的文本（包含标签）
        full_text = input_transcript_stream.strip()

        # 如果流式解析没捕到标签，从完整文本再找一次
        if current_intent is None and full_text:
            match = re.search(r'\[(WEATHER|EXIT|IGNORE|OTHER)\]', full_text)
            if match:
                current_intent = match.group(1)

        # 去掉标签，得到干净的用户请求文本
        intent_text = re.sub(r'\[.*?\]', '', full_text).strip()

        print(f"\033[94m[Final Router] Intent: {current_intent}, Text: {intent_text}\033[0m")

        if current_intent == "EXIT":
            print("\033[91m[Router] 收到退出指令，挂断会话。\033[0m")
            session_active = False
            asyncio.run_coroutine_threadsafe(sse_hub.broadcast("hangup", {}), loop)

        elif current_intent == "IGNORE":
            # 噪音/语气词：不打断、不刷新超时，静默忽略
            print("\033[90m[Router] 意图为 IGNORE，跳过处理。\033[0m")

        elif intent_text and current_intent in ("WEATHER", "OTHER"):
            # 若上一个任务仍在运行，先取消它（中断 TTS + 网络请求）
            if _current_intent_task and not _current_intent_task.done():
                print("\033[93m[Router] 新请求到来，取消上一个未完成的查询。\033[0m")
                _current_intent_task.cancel()
            last_interaction_time = time.time()
            _current_intent_task = asyncio.run_coroutine_threadsafe(
                _run_intent_handler(intent_text), loop
            )

        # 重置本轮解析状态
        current_intent = None
        input_transcript_stream = ""
        tag_parsed = False

    async def on_interrupt():
        """VAD 检测到声音：仅记录日志，不做任何打断。打断由语义标签驱动。"""
        print(f"\033[90m[VAD] 检测到声音输入，等待语义确认...\033[0m")

    def on_input_transcript(transcript: str, is_text: bool = False, no_audio: bool = False):
        """这是语音转写 (STT) 回调，仅用于前端气泡显示。不再刷新倒计时标签。"""
        if not transcript.strip(): return
        
        print(f"\033[94m[STT] User: {transcript}\033[0m")
        # 将用户的原始语音文字显示在气泡中（仅作为视觉反馈）
        asyncio.run_coroutine_threadsafe(sse_hub.broadcast("input_transcript", {"text": transcript}), loop)

    async def _run_intent_handler(transcript):
        """处理天气/OTHER 逻辑，transcript 已由 Omni 归一化。"""
        nonlocal session_active, last_interaction_time
        try:
            last_interaction_time = time.time()
            await _handle_weather_query(transcript, session_history)
            session_history.append({"role": "user", "content": transcript})
        except asyncio.CancelledError:
            print(f"\033[90m[IntentHandler] 查询已被新请求取消: {transcript[:15]}...\033[0m")
            # 停止当前 TTS 播报，避免旧内容继续播放
            if _active_tts_stop_event:
                _active_tts_stop_event.set()
            audio_manager.stop_playback()
        except Exception as e:
            print(f"[IntentHandler] Error: {e}")

    # ── Start Omni session ──
    client = None
    instructions = (
        "你是一个实时的语音助理路由器，工作在全双工模式（扬声器和麦克风同时开启）。\n"
        "【重要】：你可能会同时听到用户说话和扬声器播放的天气播报回声。\n"
        "区分规则：\n"
        "  - 【回声/陈述句】如：'成都明天小雨，气温20度，建议带雨伞。' → 判定为 [IGNORE]\n"
        "  - 【用户提问】如：'成都明天冷不冷？' / '上海下雨吗？' → 判定为 [WEATHER]\n"
        "  - 陈述句=回声，疑问句/祈使句=用户指令。这是最核心的判定规则。\n\n"
        "你的唯一任务是：在输出流的最开始输出一个意图标签和归一化请求，格式为：[标签] 归一化请求。\n"
        "标签分类：\n"
        "- [WEATHER]：用户以疑问句询问天气（含城市、时间等气象要素）。\n"
        "- [EXIT]：用户表示想结束对话、挂断、再见等。\n"
        "- [IGNORE]：扬声器回声（陈述句天气播报）、噪音、语气词（嗯、好的、知道了）、或无意义的碎碎念。\n"
        "- [OTHER]：其他非天气的有效提问或闲聊，需要生成响应的情况。\n\n"
        "注意：除了标签和归一化请求，严禁输出任何额外字符、解释或标点符号。严禁生成语音回复。"
    )
    
    try:
        client = OmniRealtimeClient(
            base_url="wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
            api_key=api_key,
            model="qwen3-omni-flash-realtime",
            on_interrupt=lambda: asyncio.create_task(on_interrupt()),
            on_input_transcript=on_input_transcript,
            on_text_delta=on_text_delta,  # 新增实时文本回调
            turn_detection_mode=TurnDetectionMode.SERVER_VAD,
            extra_event_handlers={
                "response.done": on_response_done, # 数据生成完毕后的总线入口
                "conversation.item.input_audio_transcription.delta": lambda e: None
            }
        )
        client_ref[0] = client
        await client.connect()
        await client.update_session({
            "modalities": ["text"],
            "instructions": instructions,
            "turn_detection": {
                "type": "server_vad",
                "threshold": 0.85,        # 全双工下回声可控，适当放宽灵敏度
                "prefix_padding_ms": 300, # 从 500ms 压缩到 300ms
                "silence_duration_ms": 700, # 从 1200ms 压缩到 700ms，节省约 500ms 延迟
                "create_response": True
            }
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
            nonlocal session_active, last_interaction_time
            while session_active:
                await asyncio.sleep(1)
                
                # 若 AI 正在说话，一直重置倒计时
                if audio_manager.is_running and getattr(audio_manager, 'is_speaking', False) or getattr(audio_manager, '_is_speaking', False):
                    # 注意：AudioManager暴露了 is_running，但 _is_speaking被封装，如果需要可以用 _is_speaking
                     pass
                
                if getattr(audio_manager, '_is_speaking', False):
                    last_interaction_time = time.time()

                if time.time() - last_interaction_time > 30:
                    print("\033[91m⌛ [TIMEOUT] 30秒无交互，自动挂断对话。\033[0m")
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
