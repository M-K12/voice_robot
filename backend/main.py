"""
Voice Robot Backend — FastAPI 主入口

运行方式:
  uv run python backend/main.py --reload
"""

from __future__ import annotations

import os
import json
import asyncio
import base64
import logging
import traceback
from pathlib import Path
from typing import List, Optional
from contextlib import asynccontextmanager

import uvicorn
import httpx
from dotenv import load_dotenv
from pydantic import BaseModel

import sys

# 彻底清除所有网络代理环境变量，防止继承系统/用户环境及.env文件中的代理干扰
for _proxy_key in ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:
    os.environ.pop(_proxy_key, None)

# 智能多路径加载 .env 密钥配置文件 (支持可执行文件同级、_internal 目录及当前工作目录)
_env_candidates = [
    Path.cwd() / ".env",
    Path(sys.executable).parent / ".env",
    Path(sys.executable).parent / "_internal" / ".env",
    Path(__file__).parent / ".env",
    Path(__file__).parent.parent / ".env",
]
for _env_path in _env_candidates:
    if _env_path.exists():
        load_dotenv(dotenv_path=_env_path)

for _proxy_key in ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:
    os.environ.pop(_proxy_key, None)

# Sanitize NO_PROXY to prevent httpx parsing errors with IPv6 addresses like ::1/128
no_proxy = os.environ.get("NO_PROXY", "")
if no_proxy:
    parts = []
    for part in no_proxy.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            # httpx does not support brackets or CIDR suffixes for IPv6 in NO_PROXY
            part = part.replace("[", "").replace("]", "")
            if "/" in part:
                part = part.split("/", 1)[0]
        if part and part not in parts:
            parts.append(part)
    os.environ["NO_PROXY"] = ",".join(parts)


# Configure logging at the module level
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logging.getLogger("xiaoan").setLevel(logging.INFO)
logger = logging.getLogger("xiaoan.main")

# Filter out repetitive health check access logs to keep terminal clean
class HealthCheckFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "GET /health" not in record.getMessage()

logging.getLogger("uvicorn.access").addFilter(HealthCheckFilter())

from fastapi import FastAPI, Request, Response, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks
from starlette.websockets import WebSocketState
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse



from sse_hub import sse_hub
from utils import fetch_default_city, get_tool_calling_mode, get_tool_calling_style, normalize_tool_name
from tools import GLOBAL_TOOLS_SCHEMA, get_instructions, ToolContext, execute_tool
from weather_router import router as weather_router

# FastAPI 初始化
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：替代已废弃的 on_event startup/shutdown。"""
    # ── startup ──
    global DEFAULT_CITY
    DEFAULT_CITY = await fetch_default_city()

    from utils import load_config
    cfg = load_config()
    console_lvl = cfg.get("log_level", "INFO")
    file_lvl = cfg.get("log_file_level", "WARNING")

    from logger_setup import setup_logging
    logging.info(f"🚀 [Backend Service Started] Voice Robot Backend v2.0 | 默认城市: {DEFAULT_CITY}")

    # ── 语音静态文件挂载 (在 worker 进程 startup 时挂载，确保只执行一次) ──
    from fastapi.staticfiles import StaticFiles
    _assets_candidates = [
        Path(sys.executable).parent / "assets",
        Path.cwd() / "assets",
        Path.cwd() / "backend" / "assets",
        Path(__file__).parent / "assets",
        Path(sys.executable).parent / "_internal" / "assets",
    ]
    _valid_assets_dir = None
    for _p in _assets_candidates:
        if _p.exists() and _p.is_dir() and any(_p.iterdir()):
            _valid_assets_dir = _p
            break
    if _valid_assets_dir:
        app.mount("/assets", StaticFiles(directory=str(_valid_assets_dir)), name="assets")
        logging.info(f"✅ 成功挂载语音静态资源目录 /assets -> {_valid_assets_dir}")
    else:
        logging.warning("⚠️ 未找到 assets 语音静态资源目录，/assets/ 将无法访问！")

    # ── 声纹预加载：仅当配置模型为 Qwen-Audio 且为 static 模式时异步预加载指定角色的采样 ──
    voice_model = cfg.get("voice_model_name", "")
    if voice_model and "qwen-audio" in voice_model.lower():
        from qwen_audio_realtime_handler import preload_static_voiceprints
        asyncio.create_task(preload_static_voiceprints(cfg))





    yield  # 应用正常运行期间

    # ── shutdown ──
    pass


app = FastAPI(title="Voice Robot Backend", version="2.0.0", lifespan=lifespan)

# 挂载 CORS 中间件与路由
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(weather_router)







from visual_manager import visual_broadcast_manager

# ──────────────────────────────────────────────
# 前端日志异步收集 API
# ──────────────────────────────────────────────
@app.post("/api/logs/frontend")
async def receive_frontend_logs(request: Request):
    try:
        data = await request.json()
        level = (data.get("level") or "info").lower()
        msg = data.get("message", "")
        context = data.get("context", "")
        log_line = f"[{context}] {msg}" if context else msg

        from logger_setup import frontend_logger
        if level == "error":
            frontend_logger.error(log_line)
        elif level == "warn" or level == "warning":
            frontend_logger.warning(log_line)
        else:
            frontend_logger.info(log_line)
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ──────────────────────────────────────────────
# WebSocket 视觉大屏同步推送路由 (独立大屏连接)
# ──────────────────────────────────────────────
@app.websocket("/ws/visual")
async def ws_visual_endpoint(websocket: WebSocket):
    await websocket.accept()
    await visual_broadcast_manager.register(websocket)
    
    # 🌐 当大屏连接初次建立时，主动向该大屏推送当前的默认地理坐标信息
    try:
        from utils import load_config, FALLBACK_DEFAULT_CITY
        from amap_service import amap_service
        config = load_config()
        ui_type = config.get("visual_terminal") or config.get("ui_type") or "demo_ui"
        await websocket.send_json({"type": "system_config", "config": {"visual_terminal": ui_type}})
        city = config.get("default_city") or FALLBACK_DEFAULT_CITY
        real_lon, real_lat = None, None
        if amap_service:
            real_lon, real_lat, area_name, _, _, _, _ = await amap_service.get_poi_coordinates(city)
            if area_name:
                city = area_name
        ctrl_data = {
            "place": city,
            "lng": real_lon,
            "lat": real_lat,
            "elements": "",
            "elements_colloquial": ""
        }
        await websocket.send_json({"type": "control_command", "data": ctrl_data, "visual_terminal": ui_type})
        if real_lon and real_lat:
            await websocket.send_json({"type": "query_info", "data": {"lonLat": [real_lon, real_lat], "address": city}, "visual_terminal": ui_type})
        logging.info(f"[WS-Visual] 大屏初次连接成功(模式:{ui_type})，已主动推送初始地理坐标: [{city}] ({real_lon}, {real_lat})")
    except Exception as e:
        logger.warning(f"[WS-Visual] 大屏初次连接主动下发地理坐标失败: {e}")

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"[WS-Visual] 连接异常: {e}")
    finally:
        visual_broadcast_manager.unregister(websocket)

from utils import FALLBACK_DEFAULT_CITY
DEFAULT_CITY = FALLBACK_DEFAULT_CITY
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")

# ──────────────────────────────────────────────
# WebSocket 语音路由 (前端接入麦克风与播放)
# ──────────────────────────────────────────────
@app.websocket("/voice_ws")
async def voice_websocket_endpoint(websocket: WebSocket, voice: str = "Tina"):
    await websocket.accept()
    logger.info("[WS] 前端语音通话 WebSocket 已连接")
    
    from utils import load_config
    config = load_config()
    voice_model = config.get("voice_model_name")
    
    if voice_model == "sherpa-local":
        from local_voice_handler import handle_local_voice_session
        await handle_local_voice_session(
            websocket=websocket,
            voice=voice,
            config=config,
            run_chat_workflow_fn=run_chat_workflow,
            visual_broadcast_manager=visual_broadcast_manager
        )
        return
    elif voice_model == "xunfei-realtime":
        from xunfei_realtime_handler import handle_xunfei_realtime_session
        await handle_xunfei_realtime_session(
            websocket=websocket,
            voice=voice,
            config=config,
            run_chat_workflow_fn=run_chat_workflow,
            visual_broadcast_manager=visual_broadcast_manager
        )
        return
    elif voice_model and "qwen-audio" in voice_model.lower():
        from qwen_audio_realtime_handler import handle_qwen_audio_realtime_session
        await handle_qwen_audio_realtime_session(
            websocket=websocket,
            voice=voice,
            config=config,
            visual_broadcast_manager=visual_broadcast_manager
        )
        return

    else:
        # 默认或 Qwen-Omni 实时多模态模型 (qwen3.5-omni-plus-realtime / qwen3.5-omni-flash-realtime)
        from qwen_omni_realtime_handler import handle_qwen_omni_realtime_session
        await handle_qwen_omni_realtime_session(
            websocket=websocket,
            api_key=DASHSCOPE_API_KEY,
            voice_model=voice_model or "qwen3.5-omni-plus-realtime",
            voice=voice,
            default_city_cfg=DEFAULT_CITY,
            config=config,
            visual_broadcast_manager=visual_broadcast_manager,
        )
        return

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
    "6. hangup (当且仅当用户表达明确的结束对话、挂断、告别意图时选择，如'再见'/'挂断'/'退下'。注意：当用户询问气象灾情、水退、撤退或询问系统操作等业务问题时，绝对不能选择 hangup！)\n"
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

async def run_chat_workflow(message: str, history: List[ChatMessage] | List[dict], system: Optional[str] = None, is_voice: bool = False):
    # 1. 统一历史消息格式为 dict
    normalized_history = []
    for msg in history:
        if isinstance(msg, dict):
            normalized_history.append(msg)
        else:
            normalized_history.append({"role": msg.role, "content": msg.content})

    async def event_generator():
        # 1. 广播聆听状态以重置上一轮大屏字幕与状态，再下发 ASR 与思考状态
        try:
            await visual_broadcast_manager.broadcast({"type": "state_change", "state": "listening"})
            await visual_broadcast_manager.broadcast({"type": "asr_result", "text": message, "is_final": True})
            await visual_broadcast_manager.broadcast({"type": "state_change", "state": "thinking"})
        except Exception:
            pass

        # 1. Simulate speech transcription to align workflow (Step 1: stt)
        yield f'data: {json.dumps({"type": "debug_event", "step": "stt", "content": message}, ensure_ascii=False)}\n\n'
        
        from datetime import datetime
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        # 决定大模型参数与渠道
        from utils import load_config
        config = load_config()
        
        if is_voice:
            model_name = config.get("voice_cascade_model_name") or config.get("text_model_name")
            tool_mode = config.get("voice_cascade_model_tool_mode") or "serial"
            tool_style = config.get("voice_cascade_model_tool_style") or "native"
        else:
            model_name = config.get("text_model_name")
            tool_mode = config.get("text_model_tool_mode") or "serial"
            tool_style = config.get("text_model_tool_style") or "native"

        print(f"\033[93m[LLM Brain Choice] Channel={'voice_cascade' if is_voice else 'text'}, Model={model_name} -> Mode={tool_mode}, Style={tool_style}\033[0m")
        is_openai_model = (tool_style == "native")
        
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
            chat_prompt_prefix = (
                "【绝对指令】：你自身没有任何实时的天气、灾情和资源数据。每当用户询问任何关于天气、冷热、下雨、风力、预警、展示大屏图层、避难所、物资、历史灾情等问题时，"
                "你必须且只能选择调用相应的工具函数（如 get_weather_forecast、show_screen_layer 等），绝对禁止你直接猜测或脑补回答！\n\n"
            )
            system_instruction = (
                chat_prompt_prefix + get_instructions(DEFAULT_CITY) +
                f"\n今天是 {today_str}。\n"
                "请根据用户提问，按需使用工具；如不需要工具则直接精简中文回答（在3句以内，且绝对不要提供 any 出行、穿衣或运动建议，也不要输出死板的表格）。"
            )
            formatted_messages = [
                {"role": "system", "content": system_instruction}
            ]
            for msg in normalized_history:
                formatted_messages.append({"role": msg["role"], "content": msg["content"]})
            formatted_messages.append({"role": "user", "content": message})
        else:
            formatted_messages = [
                {"role": "system", "content": ROUTER_SYSTEM_PROMPT}
            ]
            for msg in normalized_history:
                formatted_messages.append({"role": msg["role"], "content": msg["content"]})
            formatted_messages.append({"role": "user", "content": message})

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # 1. 无论是串行还是并行模式，都通过第一轮非流式请求获取所需全部工具列表
                if tool_style == "native":
                    payload = {
                        "model": model_name,
                        "messages": formatted_messages,
                        "tools": GLOBAL_TOOLS_SCHEMA,
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
                            focused_message = message
                            import re
                            clauses = re.split(r"[，。？！；,\?\!\;]|顺便|另外|以及|还有", message)
                            clauses = [c.strip() for c in clauses if c.strip()]
                            
                            tool_keywords = {
                                "get_weather_forecast": ["天气", "雨", "雪", "度", "阴", "晴", "风", "冷", "热", "预警", "下雨", "刮风", "暴雨", "台风"],
                                "query_history_disasters": ["历史灾情", "受灾情况", "历年自然灾害", "以前的灾害", "历史受灾", "灾情", "灾害"],
                                "show_screen_layer": ["图层", "雷达", "卫星", "路径", "积水", "内涝", "视频监控", "无人机", "消防通道", "图", "展示", "大屏"],
                                "query_emergency_knowledge": ["避灾", "避难", "隐患点", "救援", "物资", "安全隐患", "储备"],
                                "zoom_map": ["放大", "缩小"],
                                "hangup": ["挂断", "再见", "拜拜", "退下", "去休息吧", "退出", "别说了", "闭嘴", "滚蛋"]
                            }
                            
                            keywords = tool_keywords.get(t_name, [])
                            matched_clauses = []
                            from utils import is_exit_intent
                            for clause in clauses:
                                if t_name == "hangup":
                                    if is_exit_intent(clause):
                                        matched_clauses.append(clause)
                                else:
                                    if any(kw in clause for kw in keywords):
                                        matched_clauses.append(clause)
                            
                            if matched_clauses:
                                focused_message = "，".join(matched_clauses)
                                print(f"\033[93m[Parameter Focus Window] 工具 {t_name} 匹配到聚焦子句: '{focused_message}' (原句: '{message}')\033[0m")
                            
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
                            args = _guard_tool_args(name, args, message, today_str)
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
                            args = _guard_tool_args(name, args, message, today_str)
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
                            f"你是一个智能气象应急助手。用户的问题是：“{message}”。\n"
                            f"系统已经为你执行了以下工具并返回了最新原始数据：\n"
                            f"{chr(10).join(combined_results)}\n"
                            "【指令】请严格根据上面的原始数据，直接、正面、精准地回答用户的问题（例如说出具体温度、天气状况等）。直接切入正题，不要提供 any 出行、穿衣或运动建议，也不要输出死板的表格。"
                        )

                        second_messages = []
                        if system:
                            second_messages.append({"role": "system", "content": system})
                        else:
                            second_messages.append({"role": "system", "content": f"你是一个智能气象应急助手。今天是 {today_str}。当前默认聚焦的城市是：{DEFAULT_CITY}。"})
                        for msg in normalized_history:
                            second_messages.append({"role": msg["role"], "content": msg["content"]})
                        second_messages.append({"role": "user", "content": tool_summary_prompt})

                        second_payload = {
                            "model": model_name,
                            "messages": second_messages,
                            "stream": True
                        }

                    accumulated_content = ""
                    has_broadcasted_speaking = False
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
                                        if not has_broadcasted_speaking:
                                            has_broadcasted_speaking = True
                                            try:
                                                await visual_broadcast_manager.broadcast({"type": "state_change", "state": "speaking"})
                                            except Exception:
                                                pass
                                        accumulated_content += content
                                        if content:
                                            try:
                                                await visual_broadcast_manager.broadcast({"type": "subtitle", "text": content})
                                            except Exception:
                                                pass
                                        yield f'data: {json.dumps({"type": "delta", "content": content}, ensure_ascii=False)}\n\n'
                                else:
                                    if "message" in data and "content" in data["message"]:
                                        content = data["message"]["content"]
                                        if not has_broadcasted_speaking:
                                            has_broadcasted_speaking = True
                                            try:
                                                await visual_broadcast_manager.broadcast({"type": "state_change", "state": "speaking"})
                                            except Exception:
                                                pass
                                        accumulated_content += content
                                        if content:
                                            try:
                                                await visual_broadcast_manager.broadcast({"type": "subtitle", "text": content})
                                            except Exception:
                                                pass
                                        yield f'data: {json.dumps({"type": "delta", "content": content}, ensure_ascii=False)}\n\n'
                                    if data.get("done", False):
                                        yield f'data: {json.dumps({"type": "debug_event", "step": "tts", "content": accumulated_content}, ensure_ascii=False)}\n\n'
                                        yield f'data: {json.dumps({"type": "done"})}\n\n'
                                        break
                            except Exception:
                                pass
                        
                            yield f'data: {json.dumps({"type": "done"})}\n\n'
                else:
                    # 无需调用工具，直接回复
                    yield f'data: {json.dumps({"type": "debug_event", "step": "intent", "content": "无需调用工具，直接回复"}, ensure_ascii=False)}\n\n'
                    
                    if tool_style == "native":
                        chunk_size = 5
                        try:
                            await visual_broadcast_manager.broadcast({"type": "state_change", "state": "speaking"})
                            await visual_broadcast_manager.broadcast({"type": "subtitle", "text": content_raw})
                        except Exception:
                            pass
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
                        for msg in normalized_history:
                            chat_messages.append({"role": msg["role"], "content": msg["content"]})
                        chat_messages.append({"role": "user", "content": message})
                        
                        chat_payload = {
                            "model": model_name,
                            "messages": chat_messages,
                            "stream": True
                        }
                        
                        accumulated_content = ""
                        has_broadcasted_speaking = False
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
                                        if not has_broadcasted_speaking:
                                            has_broadcasted_speaking = True
                                            try:
                                                await visual_broadcast_manager.broadcast({"type": "state_change", "state": "speaking"})
                                            except Exception:
                                                pass
                                        accumulated_content += content
                                        if content:
                                            try:
                                                await visual_broadcast_manager.broadcast({"type": "subtitle", "text": content})
                                            except Exception:
                                                pass
                                        yield f'data: {json.dumps({"type": "delta", "content": content}, ensure_ascii=False)}\n\n'
                                    if data.get("done", False):
                                        break
                                except Exception:
                                    pass
                        yield f'data: {json.dumps({"type": "debug_event", "step": "tts", "content": accumulated_content}, ensure_ascii=False)}\n\n'
                        yield f'data: {json.dumps({"type": "done"})}\n\n'

        except Exception as e:
            yield f'data: {json.dumps({"type": "error", "message": str(e)})}\n\n'
        finally:
            try:
                await visual_broadcast_manager.broadcast({"type": "state_change", "state": "idle"})
            except Exception:
                pass

    async for event in event_generator():
        yield event








@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    print(f"\033[96m[Chat] 用户文字提问: '{request.message}'\033[0m")
    return StreamingResponse(run_chat_workflow(request.message, request.history, request.system, is_voice=False), media_type="text/event-stream")

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
def get_config_endpoint(sherpa_model_dir: str = None):
    from utils import load_config, read_wake_word_from_model
    cfg = load_config()
    # 如果接口传了特定的 sherpa_model_dir，则使用该 sherpa_model_dir 查询，否则使用当前配置中的 sherpa_model_dir
    target_dir = sherpa_model_dir if sherpa_model_dir else cfg.get("sherpa_model_dir")
    cfg["wake_word"] = read_wake_word_from_model(target_dir)
    if sherpa_model_dir:
        # 如果是专门查询特定模型的 wake_word，返回以特定格式
        return {"wake_word": cfg["wake_word"], "sherpa_model_dir": target_dir}
    return cfg

@app.post("/config")
def update_config_endpoint(new_config: dict):
    from utils import save_config_split, write_wake_word_to_model
    from logger_setup import update_logging_levels
    
    # 提取 wake_word 和 sherpa_model_dir 写入对应的 keywords.txt 词表
    wake_word = new_config.get("wake_word")
    model_dir = new_config.get("sherpa_model_dir")
    if wake_word and model_dir:
        try:
            write_wake_word_to_model(model_dir, wake_word)
        except Exception as e:
            logger.error(f"[POST /config] Failed to write wake_word to keywords.txt: {e}")
            
    try:
        merged_config = save_config_split(new_config)
        
        # 实时推算并切升级别
        console_lvl = merged_config.get("log_level", "INFO")
        file_lvl = merged_config.get("log_file_level", "WARNING")
        update_logging_levels(console_level=console_lvl, file_level=file_lvl)

        # 实时触发声纹预加载缓存更新（仅当配置为 qwen-audio 模型时）
        voice_model_name = merged_config.get("voice_model_name", "")
        if voice_model_name and "qwen-audio" in voice_model_name.lower():
            try:
                from qwen_audio_realtime_handler import preload_static_voiceprints
                asyncio.create_task(preload_static_voiceprints(merged_config))
            except ImportError:
                pass

        return {"status": "success", "config": merged_config}
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

@app.get("/device_id")
async def get_device_id():
    """获取设备唯一ID"""
    import uuid
    import socket
    device_id = uuid.uuid5(uuid.NAMESPACE_DNS, socket.gethostname() + uuid.getnode().__str__()).hex
    return {"device_id": device_id}





# ──────────────────────────────────────────────
# 用户信息 (含聚焦城市/地区、租户、组织、用户等) 动态接口
# ──────────────────────────────────────────────
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

@app.post("/api/user_info")
async def update_user_info(req: UserInfoUpdateRequest):
    global OVERRIDE_CITY, USER_INFO_OVERRIDE

    req_dict = req.model_dump(exclude_unset=True)
    USER_INFO_OVERRIDE.update(req_dict)

    # 优先提取 areaName 作为聚焦城市
    target_city = req.areaName.strip() if req.areaName and req.areaName.strip() else None
    if target_city:
        OVERRIDE_CITY = target_city

    effective_city, priority_source = await resolve_effective_city()
    logger.info(f"👤 [用户信息接口] 收到 POST 更新请求: areaName='{req.areaName}', userName='{req.userName}', orgName='{req.orgName}', effective_city='{effective_city}'")

    # 1. 广播全量用户信息消息
    info_payload = {
        "type": "user_info_update",
        **USER_INFO_OVERRIDE,
        "effective_city": effective_city,
        "priority_source": priority_source
    }
    await visual_broadcast_manager.broadcast(info_payload)

    # 2. 若更新了区域/城市，自动联动触发天气刷新广播
    if target_city:
        try:
            from weather_router import get_weather
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



# ──────────────────────────────────────────────
# 启动与关闭已迁移至顶部 lifespan() 函数
# ──────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        app,          # 直接传对象，避免 uvicorn 二次 import main 模块导致模块级代码重复执行
        host="0.0.0.0",
        port=10850,
        log_level="info"
    )
