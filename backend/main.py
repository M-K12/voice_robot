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
import httpx
import logging
from pydantic import BaseModel
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()

# Configure logging at the module level
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logging.getLogger("xiaoan").setLevel(logging.INFO)

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from backend.weather_router import router as weather_router
from backend.omni_realtime_client import OmniRealtimeClient, TurnDetectionMode
from backend.sse_hub import sse_hub
from backend.utils import fetch_default_city, get_tool_calling_mode, get_tool_calling_style, normalize_tool_name
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
    
    from backend.utils import load_config
    config = load_config()
    voice_model = config.get("voice_model_name", "qwen3.5-omni-plus-realtime")
    
    api_key = token if token else DASHSCOPE_API_KEY
    if not api_key:
        print("[WS] 错误: 缺少 API Key")
        await websocket.close(code=4000, reason="API Key is missing")
        return
        
    client = None
    session_active = True
    expecting_weather_summary = False
    loop = asyncio.get_running_loop()
    tool_lock = asyncio.Lock()
    
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

    def on_output_transcript_completed(text: str):
        if text.strip():
            print(f"\033[92m[WS-TTS] AI: {text.strip()}\033[0m")

    def on_audio_delta(audio_bytes: bytes):
        asyncio.run_coroutine_threadsafe(
            websocket.send_bytes(audio_bytes),
            loop
        )

    # ── Tool call handler ──
    voice_mode = get_tool_calling_mode("voice", voice_model)
    print(f"\033[93m[Tool Mode Choice] Channel=voice, Model={voice_model} -> Mode={voice_mode}\033[0m")

    async def handle_ws_tool_call(event):
        nonlocal session_active, expecting_weather_summary
        
        async def do_call():
            nonlocal session_active, expecting_weather_summary
            call_id = event.get("call_id")
            name = normalize_tool_name(event.get("name"))
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

        if voice_mode == "serial":
            # 串行模式，加锁排队
            async with tool_lock:
                await do_call()
        else:
            # 并行模式，直接运行
            await do_call()

    def on_tool_call(event):
        asyncio.create_task(handle_ws_tool_call(event))

    instructions = get_instructions(DEFAULT_CITY)

    try:
        client = OmniRealtimeClient(
            base_url="wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
            api_key=api_key,
            model=voice_model,
            on_interrupt=lambda: asyncio.create_task(on_interrupt()),
            on_input_transcript=on_input_transcript,
            on_output_transcript=on_output_transcript,
            on_output_transcript_completed=on_output_transcript_completed,
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
    except RuntimeError as e:
        if "receive" in str(e) or "disconnect" in str(e):
            print(f"[WS] 前端语音通话 WebSocket 已断开 ({e})")
        else:
            print(f"[WS] 运行时发生异常: {e}")
            traceback.print_exc()
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
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []
    system: Optional[str] = "你是一个智能语音助手，请用简洁友好的中文回答问题。"

def extract_json_tool_call(text: str) -> Optional[dict]:
    """Extract a single JSON tool call dict from the raw LLM output text."""
    calls = extract_all_tool_calls(text)
    return calls[0] if calls else None

def extract_all_tool_calls(text: str) -> List[dict]:
    """Extract all valid JSON tool calls from the raw LLM output text, supporting multiple tools."""
    import re
    import json
    results = []
    
    # 1. Try to match standard Markdown code block wrap
    code_blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    for block in code_blocks:
        try:
            parsed = json.loads(block.strip())
            if isinstance(parsed, dict) and "tool" in parsed:
                results.append(parsed)
        except Exception:
            pass
            
    # 2. Try character scan with brace balancing to handle messy surrounding text
    first_brace = text.find('{')
    while first_brace != -1:
        brace_count = 0
        for i in range(first_brace, len(text)):
            if text[i] == '{':
                brace_count += 1
            elif text[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    candidate = text[first_brace:i+1]
                    try:
                        parsed = json.loads(candidate)
                        if isinstance(parsed, dict) and "tool" in parsed:
                            if not any(r.get("tool") == parsed.get("tool") and r.get("location_name") == parsed.get("location_name") for r in results):
                                results.append(parsed)
                    except Exception:
                        pass
                    break
        first_brace = text.find('{', first_brace + 1)
        
    return results

def _guard_tool_args(name: str, args: dict, user_msg: str, today_str: str) -> dict:
    """Helper to fill default values and correct date/location parameters from LLM output."""
    if name in ["get_weather_forecast", "show_screen_layer", "query_emergency_knowledge", "query_history_disasters"]:
        model_loc = args.get("location_name", "").strip()
        if model_loc == DEFAULT_CITY and DEFAULT_CITY not in user_msg:
            test_cities = ["绵阳", "德阳", "眉山", "乐山", "雅安", "资阳", "自贡", "宜宾", "内江", "达州", "南充", "巴中", "广安", "遂宁", "泸州", "攀枝花", "广元", "林芝", "嘉善", "杭州", "北京", "上海", "广州", "深圳"]
            for c in test_cities:
                if c in user_msg:
                    args["location_name"] = c
                    model_loc = c
                    break
        if not model_loc:
            args["location_name"] = DEFAULT_CITY

    if name == "get_weather_forecast":
        from datetime import datetime, timedelta
        now_dt = datetime.now()
        expected_today = now_dt.strftime("%Y-%m-%d")
        expected_tomorrow = (now_dt + timedelta(days=1)).strftime("%Y-%m-%d")
        expected_after_tomorrow = (now_dt + timedelta(days=2)).strftime("%Y-%m-%d")
        expected_yesterday = (now_dt - timedelta(days=1)).strftime("%Y-%m-%d")
        
        model_date = args.get("date", "").strip()
        if "明天" in user_msg and model_date != expected_tomorrow and not any(x in user_msg for x in ["号", "日", "月"]):
            args["date"] = "明天"
        elif "后天" in user_msg and model_date != expected_after_tomorrow and not any(x in user_msg for x in ["号", "日", "月"]):
            args["date"] = "后天"
        elif "今天" in user_msg and model_date != expected_today and not any(x in user_msg for x in ["号", "日", "月"]):
            args["date"] = "今天"
        elif "昨天" in user_msg and model_date != expected_yesterday and not any(x in user_msg for x in ["号", "日", "月"]):
            args["date"] = "昨天"
        elif not model_date:
            args["date"] = today_str

        # 智能纠偏 query_types
        query_types = args.get("query_types", None)
        if not query_types:
            qt = []
            if any(x in user_msg for x in ["预警", "警报", "防范", "灾情"]):
                qt.append("alert")
            else:
                if any(x in user_msg for x in ["今天", "现在", "目前", "实时", "外面", "最近", "一段时间"]):
                    qt.append("current")
                if any(x in user_msg for x in ["明天", "后天", "预报", "未来", "几天", "星期", "最近", "一段时间"]):
                    qt.append("forecast")
                if not qt:
                    if args["date"] in ["今天", "现在", today_str]:
                        qt.append("current")
                    else:
                        qt.append("forecast")
            args["query_types"] = qt
            print(f"\033[33m[Location/Query Guard] 智能纠偏: LLM 未传入 query_types，根据问题 '{user_msg}' 自动解析为: {qt}\033[0m")
    return args

ROUTER_SYSTEM_PROMPT = (
    "请根据用户的输入，判断需要调用哪些工具。你只能从以下候选列表中选择，多个工具用英文逗号分隔：\n"
    "1. get_weather_forecast (当用户询问天气、气温、是否下雨、预警等基本气象信息时选择)\n"
    "2. query_history_disasters (当用户查询或提及历年灾害、历史受灾、历史灾情时选择)\n"
    "3. show_screen_layer (当用户明确要求在大屏展示、切换或定位雷达分布、卫星云图、台风路径、积水内涝、视频监控、无人机画面等可视化图层时选择)\n"
    "4. query_emergency_knowledge (当用户查询本地避灾避难场所、隐患点情况、救援队伍分布、储备库物资分布等本地应急防灾资源时选择)\n"
    "5. zoom_map (当用户要求放大地图或缩小地图时选择)\n"
    "6. hangup (当用户表示要再见、挂断、结束对话时选择)\n"
    "7. none (如果不涉及以上任何工具，直接回答即可时选择)\n\n"
    "【极其重要】你必须且只能输出选项对应的英文标识（例如: 'get_weather_forecast' 或 'get_weather_forecast, query_history_disasters' 或 'none'）。"
    "绝对禁止输出任何多余的字词、标点符号、Markdown格式、拼音或解释说明。"
)

EXTRACTION_PROMPTS = {
    "get_weather_forecast": (
        "请从用户的提问中提取天气查询的参数。今天是 {today_str}。默认聚焦城市是 {default_city}。\n"
        "【极其重要】你只能提取提问中与“天气、下雨、气温、风力、预警”等字眼直接绑定的那个城市名称！不要与其他工具要查询的城市混淆。\n"
        "你必须仅输出一个 JSON 对象，包含且仅包含以下字段（禁止包含 any 额外说明或 Markdown）：\n"
        "{{\n"
        "  \"location_name\": \"地点名，若提问中未指明具体城市/地点，必须输出空字符串 \\\"\\\"，禁止瞎编\",\n"
        "  \"date\": \"相对时间词（如 '今天'、'明天'、'后天'、'昨天'）或具体日期（YYYY-MM-DD）。绝对禁止你自行把口语相对时间换算成具体日期\",\n"
        "  \"query_types\": [\"需要查询的数据类型数组，只能在 'current'(实况)、'forecast'(预报)、'alert'(预警) 中选择，可多选\"]\n"
        "}}\n"
        "【示例】\n"
        "用户输入: 成都明天天气怎么样\n"
        "输出: {{\"location_name\": \"成都\", \"date\": \"明天\", \"query_types\": [\"forecast\"]}}"
    ),
    "show_screen_layer": (
        "请从用户的提问中提取展示大屏图层的参数。默认聚焦城市是 {default_city}。\n"
        "【极其重要】你只能提取提问中与“展示大屏、打开图层、雷达图、卫星图”等字眼直接绑定的城市名称！\n"
        "你必须仅输出一个 JSON 对象，包含且仅包含以下字段（禁止包含 any 额外说明或 Markdown）：\n"
        "{{\n"
        "  \"location_name\": \"图层聚焦定位的城市名，若提问中未指明具体城市/地点，必须输出空字符串 \\\"\\\"\",\n"
        "  \"layer_name\": \"必须只能在以下英文图层标识中选择：radar(雷达分布), satellite(卫星云图), typhoon(台风路径), waterlogging(积水内涝), video_surveillance(视频监控), drone_feed(无人机)\"\n"
        "}}\n"
        "【示例】\n"
        "用户输入: 请在大屏上打开成都的雷达分布图\n"
        "输出: {{\"location_name\": \"成都\", \"layer_name\": \"radar\"}}"
    ),
    "query_emergency_knowledge": (
        "请从用户的提问中提取应急知识/物资查询的参数. 默认聚焦城市是 {default_city}。\n"
        "【极其重要】你只能提取提问中与“避难所、物资库、隐患点、救援队”等字眼直接绑定的城市名称！\n"
        "你必须仅输出一个 JSON 对象，包含且仅包含以下字段（禁止包含 any 额外说明或 Markdown）：\n"
        "{{\n"
        "  \"location_name\": \"聚焦定位的城市名，若未指明则输出空字符串 \\\"\\\"\",\n"
        "  \"category\": \"必须且只能在以下四个英文单词中选择之一：'risk_point'(安全隐患点), 'shelters'(避灾避难场所), 'rescue_team'(应急救援队伍), 'supplies'(应急物资储备库)\",\n"
        "  \"query_keyword\": \"可选的过滤关键字，没有则输出空字符串 \\\"\\\"\"\n"
        "}}\n"
        "【示例】\n"
        "用户输入: 查询成都的避难所\n"
        "输出: {{\"location_name\": \"成都\", \"category\": \"shelters\", \"query_keyword\": \"\"}}"
    ),
    "zoom_map": (
        "请从用户的提问中提取地图缩放动作。\n"
        "你必须仅输出一个 JSON 对象，包含且仅包含以下字段（禁止包含 any 额外说明或 Markdown）：\n"
        "{{\n"
        "  \"action\": \"只能在 'zoom_in'(放大) 或 'zoom_out'(缩小) 中选择之一\"\n"
        "}}\n"
        "【示例】\n"
        "用户输入: 放大地图\n"
        "输出: {{\"action\": \"zoom_in\"}}"
    ),
    "query_history_disasters": (
        "请从用户的提问中提取历史灾情查询参数。默认聚焦城市是 {default_city}。\n"
        "【极其重要】你只能提取提问中与“历史灾情、受灾情况、历年灾害”等字眼直接绑定的城市名称！千万不要混淆为天气查询对应的城市！\n"
        "你必须仅输出一个 JSON 对象，包含且仅包含以下字段（禁止包含 any 额外说明或 Markdown）：\n"
        "{{\n"
        "  \"location_name\": \"需要查询历史灾情的城市或地点名称，若提问中未指明具体城市/地点，必须输出空字符串 \\\"\\\"\"\n"
        "}}\n"
        "【示例】\n"
        "用户输入: 查一下北京的历史灾情\n"
        "输出: {{\"location_name\": \"北京\"}}"
    ),
    "hangup": (
        "请输出一个空的 JSON 对象，表示挂断动作。\n"
        "输出: {{}}"
    )
}

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    async def event_generator():
        # 1. Simulate speech transcription to align workflow (Step 1: stt)
        yield f'data: {json.dumps({"type": "debug_event", "step": "stt", "content": request.message}, ensure_ascii=False)}\n\n'
        
        from datetime import datetime
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        # 决定大模型参数与渠道
        from backend.utils import load_config
        config = load_config()
        model_name = config.get("text_model_name", "qwen2.5:1.5b-instruct-q4_K_M")
        tool_mode = get_tool_calling_mode("text", model_name)
        print(f"\033[93m[Tool Mode Choice] Channel=text, Model={model_name} -> Mode={tool_mode}\033[0m")

        is_openai_model = (model_name == "qwen3.5-flash")
        tool_style = get_tool_calling_style(model_name)
        print(f"\033[93m[Tool Style Choice] Model={model_name} -> Style={tool_style}\033[0m")
        
        if is_openai_model:
            api_url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
                "Content-Type": "application/json"
            }
        else:
            api_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/chat"
            headers = {"Content-Type": "application/json"}

        if tool_style == "native":
            system_instruction = (
                get_instructions(DEFAULT_CITY) +
                f"\n今天是 {today_str}。\n"
                "请根据用户提问，按需使用工具；如不需要工具则直接精简中文回答（在3句以内，且绝对不要提供 any 出行、穿衣或运动建议，也不要输出死板的表格）。"
            )
            formatted_messages = [
                {"role": "system", "content": system_instruction}
            ]
            for msg in request.history:
                formatted_messages.append({"role": msg.role, "content": msg.content})
            formatted_messages.append({"role": "user", "content": request.message})
        else:
            formatted_messages = [
                {"role": "system", "content": ROUTER_SYSTEM_PROMPT}
            ]
            for msg in request.history:
                formatted_messages.append({"role": msg.role, "content": msg.content})
            formatted_messages.append({"role": "user", "content": request.message})

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # 1. 无论是串行还是并行模式，都通过第一轮非流式请求获取所需全部工具列表
                if tool_style == "native":
                    openai_tools = []
                    for tool in GLOBAL_TOOLS_SCHEMA:
                        openai_tools.append({
                            "type": "function",
                            "function": {
                                "name": tool["name"],
                                "description": tool.get("description", ""),
                                "parameters": tool.get("parameters", {})
                            }
                        })
                    payload = {
                        "model": model_name,
                        "messages": formatted_messages,
                        "tools": openai_tools,
                        "tool_choice": "auto",
                        "stream": False
                    }
                else:
                    payload = {
                        "model": model_name,
                        "messages": formatted_messages,
                        "stream": False
                    }

                resp = await client.post(api_url, headers=headers, json=payload)
                if resp.status_code != 200:
                    yield f'data: {json.dumps({"type": "error", "message": f"LLM Turn 1 error {resp.status_code}: {resp.text}"}, ensure_ascii=False)}\n\n'
                    return

                resp_json = resp.json()
                assistant_msg = {}
                tool_calls = []
                content_raw = ""

                if tool_style == "native":
                    if is_openai_model:
                        choices = resp_json.get("choices", [])
                        if choices:
                            assistant_msg = choices[0]["message"]
                            content_raw = assistant_msg.get("content", "") or ""
                            raw_tool_calls = assistant_msg.get("tool_calls", [])
                            if raw_tool_calls:
                                for tc in raw_tool_calls:
                                    name = tc["function"]["name"]
                                    args_str = tc["function"]["arguments"]
                                    try:
                                        args = json.loads(args_str)
                                    except Exception:
                                        args = {}
                                    t_data = {"tool": name, "call_id": tc["id"], **args}
                                    tool_calls.append(t_data)
                    else:
                        content_raw = resp_json.get("message", {}).get("content", "").strip()
                        tool_calls = extract_all_tool_calls(content_raw)
                else:
                    if is_openai_model:
                        choices = resp_json.get("choices", [])
                        content_raw = choices[0]["message"].get("content", "").strip() if choices else ""
                    else:
                        content_raw = resp_json.get("message", {}).get("content", "").strip()

                    # 模式 B：语义路由器做选择题
                    choices_text = content_raw.strip().lower()
                    valid_tool_names = ["get_weather_forecast", "query_history_disasters", "show_screen_layer", "query_emergency_knowledge", "zoom_map", "hangup"]
                    
                    selected_tools = []
                    # 按逗号分割，过滤出有效的工具名
                    for part in choices_text.split(","):
                        part_clean = part.strip()
                        normalized = normalize_tool_name(part_clean)
                        if normalized in valid_tool_names:
                            selected_tools.append(normalized)
                    
                    if selected_tools:
                        print(f"\033[92m[Router Selection] 语义选择器选中的工具: {selected_tools}\033[0m")
                        # 步骤二：针对每一个选中的工具进行参数提取
                        for t_name in selected_tools:
                            prompt_tmpl = EXTRACTION_PROMPTS.get(t_name, "请提取参数输出为 JSON。")
                            extraction_prompt = prompt_tmpl.format(today_str=today_str, default_city=DEFAULT_CITY)
                            
                            # 模式 B 聚焦子句，过滤非本工具任务对应的城市干扰
                            focused_message = request.message
                            import re
                            clauses = re.split(r"[，。？！；,\?\!\;]|顺便|另外|以及|还有", request.message)
                            clauses = [c.strip() for c in clauses if c.strip()]
                            
                            tool_keywords = {
                                "get_weather_forecast": ["天气", "雨", "雪", "度", "阴", "晴", "风", "冷", "热", "预警", "下雨", "刮风", "暴雨", "台风"],
                                "query_history_disasters": ["历史灾情", "受灾情况", "历年自然灾害", "以前的灾害", "历史受灾", "灾情", "灾害"],
                                "show_screen_layer": ["图层", "雷达", "卫星", "路径", "积水", "内涝", "视频监控", "无人机", "消防通道", "图", "展示", "大屏"],
                                "query_emergency_knowledge": ["避灾", "避难", "隐患点", "救援", "物资", "安全隐患", "储备"],
                                "zoom_map": ["放大", "缩小"],
                                "hangup": ["挂断", "再见", "拜拜", "退下"]
                            }
                            
                            keywords = tool_keywords.get(t_name, [])
                            matched_clauses = []
                            for clause in clauses:
                                if any(kw in clause for kw in keywords):
                                    matched_clauses.append(clause)
                            
                            if matched_clauses:
                                focused_message = "，".join(matched_clauses)
                                print(f"\033[93m[Parameter Focus Window] 工具 {t_name} 匹配到聚焦子句: '{focused_message}' (原句: '{request.message}')\033[0m")
                            
                            extraction_messages = [
                                {"role": "system", "content": extraction_prompt},
                                {"role": "user", "content": f"用户提问: '{focused_message}'"}
                            ]
                            
                            ext_payload = {
                                "model": model_name,
                                "messages": extraction_messages,
                                "stream": False
                            }
                            ext_resp = await client.post(api_url, headers=headers, json=ext_payload)
                            ext_args = {}
                            if ext_resp.status_code == 200:
                                if is_openai_model:
                                    ext_raw = ext_resp.json().get("choices", [])[0]["message"].get("content", "").strip() if ext_resp.json().get("choices") else ""
                                else:
                                    ext_raw = ext_resp.json().get("message", {}).get("content", "").strip()
                                print(f"\033[36m[Parameter Extraction Raw] 工具 {t_name} 的参数提取原始输出: {ext_raw}\033[0m")
                                import re
                                try:
                                    brace_match = re.search(r"(\{.*\})", ext_raw, re.DOTALL)
                                    if brace_match:
                                        ext_args = json.loads(brace_match.group(1))
                                    else:
                                        ext_args = json.loads(ext_raw)
                                except Exception:
                                    print(f"\033[91m[Parameter Extraction Error] 解析工具 {t_name} 的参数 JSON 失败，使用空字典\033[0m")
                                    ext_args = {}
                            
                            t_data = {"tool": t_name, "call_id": None, **ext_args}
                            tool_calls.append(t_data)

                if tool_calls:
                    combined_results = []
                    results_payloads = []
                    
                    if tool_mode == "serial":
                        print(f"\033[93m[Tool Choice] 串行模式执行，逐个执行工具（数量: {len(tool_calls)}）\033[0m")
                        # 串行模式下，逐个 await 同步阻塞执行，避免物理控制/UI层并发混乱
                        for t_data in tool_calls:
                            name = normalize_tool_name(t_data["tool"])
                            t_data["tool"] = name
                            args = {k: v for k, v in t_data.items() if k not in ["tool", "call_id"]}
                            args = _guard_tool_args(name, args, request.message, today_str)
                            arguments_str = json.dumps(args, ensure_ascii=False)

                            yield f'data: {json.dumps({"type": "debug_event", "step": "intent", "content": f"语义分析决定调用工具(串行): {name}"}, ensure_ascii=False)}\n\n'
                            yield f'data: {json.dumps({"type": "debug_event", "step": "tool_call", "name": name, "arguments": arguments_str}, ensure_ascii=False)}\n\n'

                            ctx = ToolContext(
                                websocket=None,
                                default_city=DEFAULT_CITY,
                                expecting_weather_summary=False,
                                session_active=True
                            )
                            res_payload = await execute_tool(name, arguments_str, ctx)

                            try:
                                result_dict = json.loads(res_payload)
                            except Exception:
                                result_dict = res_payload
                            yield f'data: {json.dumps({"type": "debug_event", "step": "tool_result", "name": name, "result": result_dict}, ensure_ascii=False)}\n\n'
                            
                            results_payloads.append(res_payload)
                            combined_results.append(f"【工具 {name} 执行返回数据】：\n{res_payload}")
                    else:
                        print(f"\033[93m[Tool Choice] 并行模式执行，并发执行工具（数量: {len(tool_calls)}）\033[0m")
                        # 并行模式下，asyncio.gather 并发执行
                        tasks = []
                        for t_data in tool_calls:
                            name = normalize_tool_name(t_data["tool"])
                            t_data["tool"] = name
                            args = {k: v for k, v in t_data.items() if k not in ["tool", "call_id"]}
                            args = _guard_tool_args(name, args, request.message, today_str)
                            arguments_str = json.dumps(args, ensure_ascii=False)

                            yield f'data: {json.dumps({"type": "debug_event", "step": "intent", "content": f"语义分析决定调用工具(并行): {name}"}, ensure_ascii=False)}\n\n'
                            yield f'data: {json.dumps({"type": "debug_event", "step": "tool_call", "name": name, "arguments": arguments_str}, ensure_ascii=False)}\n\n'

                            ctx = ToolContext(websocket=None, default_city=DEFAULT_CITY)
                            tasks.append(execute_tool(name, arguments_str, ctx))

                        results_payloads = await asyncio.gather(*tasks)

                        for t_data, res_payload in zip(tool_calls, results_payloads):
                            name = t_data["tool"]
                            try:
                                result_dict = json.loads(res_payload)
                            except Exception:
                                result_dict = res_payload
                            yield f'data: {json.dumps({"type": "debug_event", "step": "tool_result", "name": name, "result": result_dict}, ensure_ascii=False)}\n\n'
                            combined_results.append(f"【工具 {name} 执行返回数据】：\n{res_payload}")

                    # 进行第二轮汇总总结请求
                    if tool_style == "native" and is_openai_model:
                        second_messages = list(formatted_messages)
                        second_messages.append(assistant_msg)
                        
                        for t_data, res_payload in zip(tool_calls, results_payloads):
                            second_messages.append({
                                "role": "tool",
                                "tool_call_id": t_data["call_id"],
                                "name": t_data["tool"],
                                "content": res_payload
                            })
                        
                        second_payload = {
                            "model": model_name,
                            "messages": second_messages,
                            "stream": True
                        }
                    else:
                        tool_summary_prompt = (
                            f"你是一个智能气象应急助手。用户的问题是：“{request.message}”。\n"
                            f"系统已经为你执行了以下工具并返回了最新原始数据：\n"
                            f"{chr(10).join(combined_results)}\n"
                            "【指令】请严格根据上面的原始数据，直接、正面、精准地回答用户的问题（例如说出具体温度、天气状况等）。直接切入正题，不要提供 any 出行、穿衣或运动建议，也不要输出死板的表格。"
                        )

                        second_messages = []
                        if request.system:
                            second_messages.append({"role": "system", "content": request.system})
                        for msg in request.history:
                            second_messages.append({"role": msg.role, "content": msg.content})
                        second_messages.append({"role": "user", "content": tool_summary_prompt})

                        second_payload = {
                            "model": model_name,
                            "messages": second_messages,
                            "stream": True
                        }

                    accumulated_content = ""
                    async with client.stream("POST", api_url, headers=headers, json=second_payload) as stream_resp:
                        if stream_resp.status_code != 200:
                            yield f'data: {json.dumps({"type": "error", "message": f"LLM Turn 2 error {stream_resp.status_code}"})}\n\n'
                            return
                        async for line in stream_resp.aiter_lines():
                            if not line: continue
                            try:
                                line_str = line.strip()
                                if is_openai_model:
                                    if line_str.startswith("data: "):
                                        line_str = line_str[6:]
                                    if line_str == "[DONE]":
                                        break
                                data = json.loads(line_str)
                                if is_openai_model:
                                    choices = data.get("choices", [])
                                    if choices and "delta" in choices[0] and "content" in choices[0]["delta"]:
                                        content = choices[0]["delta"]["content"]
                                        accumulated_content += content
                                        yield f'data: {json.dumps({"type": "delta", "content": content}, ensure_ascii=False)}\n\n'
                                else:
                                    if "message" in data and "content" in data["message"]:
                                        content = data["message"]["content"]
                                        accumulated_content += content
                                        yield f'data: {json.dumps({"type": "delta", "content": content}, ensure_ascii=False)}\n\n'
                                    if data.get("done", False):
                                        yield f'data: {json.dumps({"type": "debug_event", "step": "tts", "content": accumulated_content}, ensure_ascii=False)}\n\n'
                                        yield f'data: {json.dumps({"type": "done"})}\n\n'
                                        break
                            except Exception:
                                pass
                        
                        if is_openai_model:
                            yield f'data: {json.dumps({"type": "debug_event", "step": "tts", "content": accumulated_content}, ensure_ascii=False)}\n\n'
                            yield f'data: {json.dumps({"type": "done"})}\n\n'
                else:
                    # 无需调用工具，直接回复
                    yield f'data: {json.dumps({"type": "debug_event", "step": "intent", "content": "无需调用工具，直接回复"}, ensure_ascii=False)}\n\n'
                    
                    if tool_style == "native":
                        chunk_size = 5
                        for i in range(0, len(content_raw), chunk_size):
                            chunk = content_raw[i:i+chunk_size]
                            yield f'data: {json.dumps({"type": "delta", "content": chunk}, ensure_ascii=False)}\n\n'
                            await asyncio.sleep(0.01)
                        yield f'data: {json.dumps({"type": "debug_event", "step": "tts", "content": content_raw}, ensure_ascii=False)}\n\n'
                        yield f'data: {json.dumps({"type": "done"})}\n\n'
                    else:
                        # 对于小模型，由于第一步只是输出 "none"，我们在此发起真正的闲聊生成
                        chat_instruction = (
                            f"你是一个智能气象应急助手。今天是 {today_str}。当前默认聚焦的城市是：{DEFAULT_CITY}。\n"
                            "请用简洁友好的中文回答用户的问题，回答控制在3句以内。"
                        )
                        chat_messages = [
                            {"role": "system", "content": chat_instruction}
                        ]
                        for msg in request.history:
                            chat_messages.append({"role": msg.role, "content": msg.content})
                        chat_messages.append({"role": "user", "content": request.message})
                        
                        chat_payload = {
                            "model": model_name,
                            "messages": chat_messages,
                            "stream": True
                        }
                        
                        accumulated_content = ""
                        async with client.stream("POST", api_url, headers=headers, json=chat_payload) as stream_resp:
                            if stream_resp.status_code != 200:
                                yield f'data: {json.dumps({"type": "error", "message": f"LLM Chat error {stream_resp.status_code}"})}\n\n'
                                return
                            async for line in stream_resp.aiter_lines():
                                if not line: continue
                                try:
                                    line_str = line.strip()
                                    data = json.loads(line_str)
                                    if "message" in data and "content" in data["message"]:
                                        content = data["message"]["content"]
                                        accumulated_content += content
                                        yield f'data: {json.dumps({"type": "delta", "content": content}, ensure_ascii=False)}\n\n'
                                    if data.get("done", False):
                                        break
                                except Exception:
                                    pass
                        yield f'data: {json.dumps({"type": "debug_event", "step": "tts", "content": accumulated_content}, ensure_ascii=False)}\n\n'
                        yield f'data: {json.dumps({"type": "done"})}\n\n'

        except Exception as e:
            yield f'data: {json.dumps({"type": "error", "message": str(e)})}\n\n'

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/extract_city")
async def extract_city_endpoint(request: Request):
    try:
        body = await request.json()
        message = body.get("message", "")
        ollama_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/chat"
        prompt = (
            "请从用户的输入中提取他想要查询天气所在的城市名称，并输出该城市的标准中文名称（例如：'北京'、'杭州'、'嘉善'），"
            "只输出城市中文名称，不要包含任何其他说明文字或标点符号。如果找不到，返回空。"
        )
        payload = {
            "model": "qwen2.5:1.5b-instruct-q4_K_M",
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"用户输入: '{message}'"}
            ],
            "stream": False
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(ollama_url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                raw_city = data.get("message", {}).get("content", "").strip()
                import re
                city = re.sub(r'[^\w\u4e00-\u9fa5]', '', raw_city)
                return {"city": city}
    except Exception as e:
        print(f"[extract_city] Error: {e}")
    return {"city": ""}

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

@app.get("/config")
def get_config_endpoint():
    from backend.utils import load_config
    return load_config()

@app.post("/config")
def update_config_endpoint(new_config: dict):
    from backend.utils import load_config
    import json
    from pathlib import Path
    config_path = (Path(__file__).parent.parent / "config.json").resolve()
    current = load_config()
    current.update(new_config)
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=4, ensure_ascii=False)
        return {"status": "success", "config": current}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))

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

    # Configure xiaoan logger explicitly to output to stderr/stdout on startup
    xiaoan_logger = logging.getLogger("xiaoan")
    xiaoan_logger.setLevel(logging.INFO)
    
    # Force level to INFO for all handlers
    for handler in logging.getLogger().handlers:
        handler.setLevel(logging.INFO)
        
    if not xiaoan_logger.handlers:
        sh = logging.StreamHandler()
        sh.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        sh.setFormatter(formatter)
        xiaoan_logger.addHandler(sh)
        xiaoan_logger.propagate = False
    else:
        for handler in xiaoan_logger.handlers:
            handler.setLevel(logging.INFO)

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
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8765, reload=True, log_level="info")
# Reload triggered
