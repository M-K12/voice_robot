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
            model="qwen-max",
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
            model="qwen-max",
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
# 天气工具（供语音接口调用）
# ──────────────────────────────────────────────
import shutil
_WEATHER_SCRIPT = (
    Path(__file__).parent.parent / "spd-weather" / "scripts" / "spd_weather.py"
).resolve()
_UV = shutil.which("uv") or "uv.exe"

def _run_weather_script(city: str) -> str:
    if not _WEATHER_SCRIPT.exists():
        return json.dumps({"error": f"spd_weather.py 未找到: {_WEATHER_SCRIPT}"})
    try:
        proc = subprocess.run(
            [_UV, "run", "--no-sync", str(_WEATHER_SCRIPT), city],
            capture_output=True, timeout=30.0, text=False,
        )
        raw = proc.stdout.decode("utf-8", errors="replace").strip()
        if not raw or "[错误]" in raw:
            err = raw or proc.stderr.decode("utf-8", errors="replace").strip()
            return json.dumps({"error": err})
        return raw
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "天气查询超时"})
    except Exception as e:
        return json.dumps({"error": str(e)})


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
                            asyncio.run_coroutine_threadsafe(
                                websocket.send_bytes(audio_bytes),
                                loop
                            )
                    elif etype == 'response.done':
                        print("[WeatherTTS] Synthesis done.")
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
            tts_client.update_session(voice="Cherry")

            # 发送要合成的文本
            tts_client.append_text(text)

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

@app.websocket("/voice_ws")
async def voice_ws(websocket: WebSocket, voice: str = "loongchen-v2", token: Optional[str] = None):
    await websocket.accept()
    websocket_active = True
    loop = asyncio.get_running_loop()
    tts_state = {"playing": False}
    handling_weather = False  # 新增：用于屏蔽大模型多余的语音干扰
    last_user_query = ""      # 新增：记录用户最后的提问，用于增强天气总结的上下文
    last_processed_transcript = ""
    last_processed_time = 0
    api_key = token if token else os.getenv("DASHSCOPE_API_KEY", "")
    # voice already passed from query param

    HEARTBEAT_INTERVAL = 25  # seconds

    # --- 音频回调 ---
    async def on_audio(audio_data: bytes):
        nonlocal websocket_active, handling_weather
        if not websocket_active or handling_weather:
            return
        try:
            if isinstance(audio_data, str):
                audio_bytes = base64.b64decode(audio_data)
            else:
                audio_bytes = audio_data
            await websocket.send_bytes(audio_bytes)
        except Exception:
            pass

    async def on_interrupt():
        nonlocal websocket_active
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
                model="qwen-max",
                messages=[
                    {"role": "system", "content": "你是一个地名抓取机器。请将用户句子中提到的地点转换为地级市或直辖市（例如：查一下萧山的天气 -> 杭州，北京天气 -> 北京）。只能输出最终的纯中文名字（只需城市名即可，若带市则保留），不要任何标点和废话！如果没找到地名，输出空白即可。"},
                    {"role": "user", "content": text}
                ],
                stream=False,
                temperature=0.1,
                max_tokens=10
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"[_extract_city_llm] Error: {e}")
            return ""

    async def _summarize_weather_llm(raw_weather: str, city: str, api_key: str, user_query: str = ""):
        """使用 Qwen-Max 将原始天气数据总结为一段自然的语音播报文案。"""
        if not api_key:
            print(f"[_summarize_weather_llm] No API Key provided for {city}")
            return f"已为您查到{city}的天气，请看屏幕显示。"
        
        try:
            print(f"[_summarize_weather_llm] Summarizing weather for {city} using qwen-max (Query: {user_query})...")
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=api_key, base_url=QWEN_BASE_URL)
            
            response = await client.chat.completions.create(
                model="qwen-max",
                messages=[
                    {"role": "system", "content": f"""你是一个高效、简洁的气象助手。直接回答用户关于【{city}】的天气询问。
用户的问题是："{user_query}"。
要求：
1. **直接回答**：不要任何寒暄（如"嘿，朋友们"、"大家好"等），直接进入正题。
2. **精准聚焦**：如果用户问了特定的天气现象（如下雨吗、刮风吗、冷不冷），请优先且直接回答该问题。
3. **惜字如金**：一旦问题得到明确回答，不要罗列无关的气象参数。例如问"下雨吗"，只需回答是否下雨及相关阴晴即可，无需提及风力。
4. **自然口语**：使用自然的人类对白，拒绝报表式列举。控制在 50 字以内。"""},
                    {"role": "user", "content": f"城市：{city}\n原始数据：{raw_weather}"}
                ],
                stream=False,
                temperature=0.7,
                max_tokens=200
            )
            summary = response.choices[0].message.content.strip()
            print(f"[_summarize_weather_llm] Summary generated: {summary[:50]}...")
            return summary
        except Exception as e:
            print(f"[_summarize_weather_llm] Error: {e}")
            import traceback
            traceback.print_exc()
            return f"已为您查到{city}的天气，请看屏幕显示。"

    def on_input_transcript(transcript: str):
        nonlocal websocket_active, last_user_query, handling_weather, last_processed_transcript, last_processed_time
        if not websocket_active:
            return
            
        current_time = time.time()
        # 去重：如果和上一次文本相同且间隔小于1秒，忽略
        if transcript == last_processed_transcript and (current_time - last_processed_time) < 1.0:
            return
            
        last_processed_transcript = transcript
        last_processed_time = current_time

        print(f"[voice_ws] Input Transcript: {transcript}")
        last_user_query = transcript # 记录上下文
        try:
            asyncio.run_coroutine_threadsafe(
                websocket.send_text(json.dumps({"type": "input_transcript", "data": transcript})),
                loop
            )
            
            # 兼容：如果 DashScope 的实时语音大模型不支持 function calling，我们就在这里做 fallback 检测！
            if _WEATHER_RE.search(transcript):
                if handling_weather:
                    return
                print(f"[voice_ws] Fallback intent matched for weather in transcript: {transcript}")
                handling_weather = True # 开始处理天气，屏蔽大模型其他音频
                
                async def _run_fallback_weather(transcript_for_eval):
                    nonlocal handling_weather
                    try:
                        print(f"[Fallback] >>> START for: {transcript_for_eval}")
                        # 立刻取消当前大模型正在进行的或即将开始的语音回答
                        if client_ref[0] and getattr(client_ref[0], 'ws', None):
                            await client_ref[0].send_event({"type": "response.cancel"})
                        
                        # 立刻告知前端停止播放已有音频（掐断）
                        await on_interrupt()

                        # 1. 精准提取城市
                        print(f"[Fallback] Step 1: Extracting city...")
                        city = await _extract_city_llm(transcript_for_eval)
                        if not city:
                            m = _CITY_RE.search(transcript_for_eval)
                            city = m.group(1) if m else DEFAULT_CITY
                            for prefix in ["查一下", "帮我查", "帮我看一下", "看一下"]:
                                if city.startswith(prefix):
                                    city = city[len(prefix):]
                        
                        print(f"[Fallback] Step 2: Calling weather for city: '{city}'")
                        raw = await asyncio.to_thread(_run_weather_script, city)
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
                                await websocket.send_text(json.dumps({
                                    "type": "weather_data",
                                    "city": city,
                                    "data": weather_data
                                }, ensure_ascii=False))
                                print(f"[Fallback] Step 4: Weather data sent for {city}")
                                
                                print(f"[Fallback] Step 5: Summarizing...")
                                summary_msg = await _summarize_weather_llm(organized_text, city, api_key, last_user_query)
                                
                                await websocket.send_text(json.dumps({
                                    "type": "weather_summary",
                                    "data": summary_msg
                                }, ensure_ascii=False))

                                print(f"[Fallback] Step 6: TTS...")
                                _speak_text_realtime(summary_msg, websocket, loop, tts_state, client_ref[0], api_key=api_key)
                            else:
                                msg = await _summarize_weather_llm(organized_text, city, api_key, last_user_query)
                                _speak_text_realtime(msg, websocket, loop, tts_state, client_ref[0], api_key=api_key)
                            
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


    def on_output_transcript(transcript: str):
        nonlocal websocket_active, handling_weather
        if not websocket_active:
            return
        
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
                            await websocket.send_text(json.dumps({
                                "type": "weather_data",
                                "city": city_name,
                                "data": weather_data
                            }, ensure_ascii=False))
                            summary_msg = await _summarize_weather_llm(organized_text, city_name, api_key, last_user_query)
                            await websocket.send_text(json.dumps({
                                "type": "weather_summary",
                                "data": summary_msg
                            }, ensure_ascii=False))
                            _speak_text_realtime(summary_msg, websocket, loop, tts_state, client_ref[0], api_key=api_key)
                        else:
                            msg = await _summarize_weather_llm(organized_text, city_name, api_key, last_user_query)
                            _speak_text_realtime(msg, websocket, loop, tts_state, client_ref[0], api_key=api_key)
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
        try:
            asyncio.run_coroutine_threadsafe(
                websocket.send_text(json.dumps({"type": "output_transcript", "data": transcript})),
                loop
            )
        except Exception:
            pass

    # --- 天气工具函数 ---
    async def handle_function_call(client: OmniRealtimeClient, function_name: str, function_args: dict, call_id: str):
        """执行工具函数并把结果回传给模型"""
        nonlocal handling_weather
        print(f"[voice_ws] --- Calling weather skill (Native Function Call) ---")
        print(f"[voice_ws]   -> Function: {function_name}, Args: {function_args}")
        result = ""
        if function_name == "get_weather":
            city = function_args.get("city", "")
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
                    await websocket.send_text(json.dumps({
                        "type": "weather_data",
                        "city": city,
                        "data": weather_data
                    }, ensure_ascii=False))
                    
                    # --- 使用 LLM 总结并由 TTS 播报结果 ---
                    handling_weather = True
                    try:
                        summary_msg = await _summarize_weather_llm(organized_text, city, api_key, last_user_query)
                        
                        # 发送总结后的文本给前端显示 (使用 weather_summary 类型以便前端替换占位符)
                        await websocket.send_text(json.dumps({
                            "type": "weather_summary",
                            "data": summary_msg
                        }, ensure_ascii=False))

                        _speak_text_realtime(summary_msg, websocket, loop, tts_state, client, api_key=api_key)
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

    client_ref = [None]  # mutable reference for closures

    # 定义工具 schema
    tools = [
        {
            "type": "function",
            "name": "get_weather",
            "description": "获取指定城市的天气预报信息。",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "要查询天气的城市名称，例如：北京"}
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

    heartbeat_task = asyncio.create_task(send_heartbeat())
    client: Optional[OmniRealtimeClient] = None
    message_task = None

    # 天气关键词检测（用于自动触发天气查询）
    import re
    _WEATHER_RE = re.compile(r'天气|气温|温度|下雨|下雪|预报|穿衣|降水|风力|冷不冷|热不热')
    _CITY_RE = re.compile(r'([^\s，,。！？]{2,6}?)[的]?(?:天气|气温|温度|下雨|下雪|预报|穿衣|降水|风力|冷不冷|热不热)')

    try:
        client = OmniRealtimeClient(
            base_url="wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
            api_key=api_key,
            model="qwen3-omni-flash-realtime",
            voice=voice,
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
        
        # 针对 qwen3-omni-flash-realtime 更新会话配置
        await client.update_session({
            "instructions": (
                "你是一个聪明的全能语音助手。请根据用户的输入提供准确的回答。\n"
                "1. **仅当**用户询问天气、气温、下雨、穿衣、室外活动等气象相关信息时，才调用 `get_weather` 工具。\n"
                "2. 调用天气工具时，必须直接调用，严禁任何口头开场白。\n"
                "3. 对于非天气的普通聊天、知识问答或日常对话，请直接口头回答，不要调用天气工具。\n"
                f"4. 默认城市为'{DEFAULT_CITY}'。你的回复应尽量简洁有力。"
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
                                if tts_state.get("playing", False):
                                    continue # 静音：丢弃这段时间拾取的录音
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
                                    if _WEATHER_RE.search(query_text):
                                        m = _CITY_RE.search(query_text)
                                        city = m.group(1) if m else DEFAULT_CITY
                                        raw = await asyncio.to_thread(_run_weather_script, city)
                                        try:
                                            if not raw.startswith('{"error"'):
                                                weather_data = _parse_weather_text(raw, city)
                                                await websocket.send_text(json.dumps({
                                                    "type": "weather_data",
                                                    "city": city,
                                                    "data": weather_data
                                                }, ensure_ascii=False))
                                        except Exception:
                                            pass
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
        heartbeat_task.cancel()
        if message_task:
            message_task.cancel()
        if client:
            try:
                await client.close()
            except Exception:
                pass


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8765, reload=True)
