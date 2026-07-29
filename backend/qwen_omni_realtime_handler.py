"""
Qwen-Omni Realtime Handler (qwen3.5-omni-plus-realtime / qwen3.5-omni-flash-realtime)

严格按照阿里云百炼 Qwen-Omni Realtime 官方 WebSocket 协议文档实现。
提供全双工实时（语音/文本）交互、智能工具调用 (Function Calling)、
硬打断防残音泄露屏障、可视化大屏广播支持。
"""

from __future__ import annotations

import os
import json
import time
import base64
import asyncio
import logging
from enum import Enum
from typing import Optional, Callable, List, Dict, Any

import websockets
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from backend.utils import normalize_tool_name
from backend.tools import GLOBAL_TOOLS_SCHEMA, get_instructions, ToolContext, execute_tool

logger = logging.getLogger("xiaoan.qwen_omni")


class DummyBroadcastManager:
    async def broadcast(self, message: dict):
        pass

_dummy_broadcast_manager = DummyBroadcastManager()


class TurnDetectionMode(str, Enum):
    SEMANTIC_VAD = "semantic_vad"  # 语义融合 VAD (Qwen3.5-Omni 系列推荐)
    SERVER_VAD   = "server_vad"    # 声学 VAD
    MANUAL       = "manual"        # 手动/按键触发 (turn_detection=null)


class QwenOmniRealtimeClient:
    """
    与阿里云百炼 Qwen-Omni Realtime WebSocket 服务交互的专属客户端。
    """
    def __init__(
        self,
        workspace_id: str,
        api_key: str,
        model: str = "qwen3.5-omni-plus-realtime",
        voice: str = "Ethan",
        instructions: str = "",
        turn_mode: TurnDetectionMode = TurnDetectionMode.SEMANTIC_VAD,
        vad_threshold: float = 0.5,
        vad_silence_ms: int = 800,
        tools: Optional[List[Dict[str, Any]]] = None,
        region: str = "cn",
        on_audio_delta: Optional[Callable[[bytes], None]] = None,
        on_input_transcript: Optional[Callable[[str, bool, str], None]] = None,
        on_output_transcript: Optional[Callable[[str, str], None]] = None,
        on_output_transcript_completed: Optional[Callable[[str], None]] = None,
        on_interrupt: Optional[Callable[[], None]] = None,
        on_response_created: Optional[Callable[[dict], None]] = None,
        on_response_done: Optional[Callable[[dict], None]] = None,
        on_tool_call: Optional[Callable[[dict], None]] = None,
        on_error: Optional[Callable[[dict], None]] = None,
    ):
        self.workspace_id = workspace_id
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.instructions = instructions
        self.turn_mode = turn_mode
        self.vad_threshold = vad_threshold
        self.vad_silence_ms = vad_silence_ms
        self.tools = tools or []
        self.region = region

        self.on_audio_delta = on_audio_delta
        self.on_input_transcript = on_input_transcript
        self.on_output_transcript = on_output_transcript
        self.on_output_transcript_completed = on_output_transcript_completed
        self.on_interrupt = on_interrupt
        self.on_response_created = on_response_created
        self.on_response_done = on_response_done
        self.on_tool_call = on_tool_call
        self.on_error = on_error

        self.ws = None
        self._current_response_id: Optional[str] = None
        self._is_responding: bool = False
        self._response_done_event = asyncio.Event()
        self._response_done_event.set()
        
        self._audio_suppressed: bool = False
        self._manual_interrupt_active: bool = False
        self._current_output_text: str = ""
        self._current_input_item_id: Optional[str] = None
        self._current_input_text: str = ""

    async def connect(self) -> None:
        """建立 WebSocket 连接并发送配置 updates。"""
        if not self.workspace_id:
            raise ValueError("[QwenOmni] DASHSCOPE_WORKSPACE_ID 不能为空，必须配置百炼业务空间 ID。")

        domain = "cn-beijing.maas.aliyuncs.com" if self.region == "cn" else "ap-southeast-1.maas.aliyuncs.com"
        base_domain = f"{self.workspace_id}.{domain}"
        url = f"wss://{base_domain}/api-ws/v1/realtime?model={self.model}"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        logger.info(f"[QwenOmni] 正在连接服务端: {url}")
        self.ws = await websockets.connect(
            url,
            extra_headers=headers,
            open_timeout=30,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=10,
        )

        # 构建会话初始配置
        session_config: Dict[str, Any] = {
            "modalities": ["text", "audio"] if self.voice else ["text"],
            "input_audio_format": "pcm",
            "output_audio_format": "pcm",
            "voice": self.voice,
            "instructions": self.instructions,
            "enable_search": False,  # 显式关闭联网搜索，强制模型必须使用本地工具 (Function Calling)
            # 启用用户语音转写（需要显式配置，否则服务端不会发送 ASR delta/completed 事件）
            "input_audio_transcription": {
                "model": "qwen3-asr-flash-realtime"
            },
        }

        if self.turn_mode == TurnDetectionMode.MANUAL:
            session_config["turn_detection"] = None
        else:
            session_config["turn_detection"] = {
                "type": self.turn_mode.value,
                "threshold": self.vad_threshold,
                "silence_duration_ms": self.vad_silence_ms,
            }

        if self.tools:
            session_config["tools"] = self.tools

        await self.update_session(session_config)

    async def send_event(self, event: dict) -> None:
        if not self.ws:
            return
        event["event_id"] = "event_" + str(int(time.time() * 1000))
        if event.get("type") != "input_audio_buffer.append":
            logger.debug(f"[QwenOmni] → {event.get('type')}")
        await self.ws.send(json.dumps(event))

    async def update_session(self, config: Dict[str, Any]) -> None:
        await self.send_event({"type": "session.update", "session": config})

    async def stream_audio(self, pcm_chunk: bytes) -> None:
        audio_b64 = base64.b64encode(pcm_chunk).decode("utf-8")
        await self.send_event({"type": "input_audio_buffer.append", "audio": audio_b64})


    async def commit_audio_buffer(self) -> None:
        await self.send_event({"type": "input_audio_buffer.commit"})

    async def create_response(self) -> None:
        await self.send_event({
            "type": "response.create",
            "response": {
                "modalities": ["text", "audio"] if self.voice else ["text"]
            }
        })

    async def cancel_response(self) -> None:
        await self.send_event({"type": "response.cancel"})

    async def handle_interruption(self) -> None:
        self._audio_suppressed = True
        self._manual_interrupt_active = True
        logger.info("[QwenOmni] 用户触发打断: 启用物理静音 + 取消模型响应")
        await self.cancel_response()

    async def handle_messages(self) -> None:
        try:
            async for message in self.ws:
                event = json.loads(message)
                event_type = event.get("type", "")

                if event_type != "response.audio.delta":
                    logger.info(f"[QwenOmni] ← {event_type}")

                if event_type == "error":
                    err_obj = event.get("error", {})
                    err_msg = str(err_obj.get("message", "") if isinstance(err_obj, dict) else err_obj)
                    if "Conversation has no active response" in err_msg or "manual response is already in progress" in err_msg:
                        logger.info(f"[QwenOmni] 忽略阿里云正常打断/并发取消提醒: {err_msg}")
                    else:
                        logger.error(f"[QwenOmni] 服务端错误: {err_obj}")
                        if self.on_error:
                            self.on_error(err_obj)
                    self._is_responding = False
                    self._response_done_event.set()

                elif event_type == "response.created":
                    self._current_response_id = event.get("response", {}).get("id")
                    self._is_responding = True
                    self._response_done_event.clear()
                    if not self._manual_interrupt_active:
                        self._audio_suppressed = False
                    self._current_output_text = ""
                    if self.on_response_created:
                        self.on_response_created(event)

                elif event_type == "response.done":
                    self._is_responding = False
                    self._response_done_event.set()
                    self._current_response_id = None
                    if self.on_response_done:
                        self.on_response_done(event)

                elif event_type == "input_audio_buffer.speech_started":
                    self._current_input_text = ""
                    self._manual_interrupt_active = False
                    if self._is_responding:
                        await self.handle_interruption()
                        if self.on_interrupt:
                            self.on_interrupt()

                elif event_type == "response.audio.delta":
                    if self._audio_suppressed:
                        continue
                    delta_b64 = event.get("delta", "")
                    if delta_b64 and self.on_audio_delta:
                        audio_bytes = base64.b64decode(delta_b64)
                        self.on_audio_delta(audio_bytes)

                elif event_type in ("response.audio_transcript.delta", "response.text.delta"):
                    delta = event.get("delta", "")
                    self._current_output_text += delta
                    if self.on_output_transcript and not self._audio_suppressed:
                        if asyncio.iscoroutinefunction(self.on_output_transcript):
                            await self.on_output_transcript(self._current_output_text, self._current_response_id or "")
                        else:
                            self.on_output_transcript(self._current_output_text, self._current_response_id or "")

                elif event_type in ("response.audio_transcript.done", "response.text.done"):
                    completed_text = self._current_output_text.strip()
                    if completed_text and self.on_output_transcript_completed and not self._audio_suppressed:
                        if asyncio.iscoroutinefunction(self.on_output_transcript_completed):
                            await self.on_output_transcript_completed(completed_text)
                        else:
                            self.on_output_transcript_completed(completed_text)

                elif event_type == "conversation.item.input_audio_transcription.delta":
                    stash = event.get("stash", "")
                    text = event.get("text", "")
                    item_id = event.get("item_id", "")
                    preview = (text + stash).strip()
                    if item_id != self._current_input_item_id:
                        self._current_input_item_id = item_id
                        self._current_input_text = ""
                    if preview and preview != self._current_input_text:
                        self._current_input_text = preview
                        if self.on_input_transcript:
                            if asyncio.iscoroutinefunction(self.on_input_transcript):
                                await self.on_input_transcript(preview, False, item_id)
                            else:
                                self.on_input_transcript(preview, False, item_id)

                elif event_type == "conversation.item.input_audio_transcription.completed":
                    transcript = event.get("transcript", "").strip()
                    item_id = event.get("item_id", "") or self._current_input_item_id or ""
                    self._current_input_item_id = None
                    self._current_input_text = ""
                    if transcript and self.on_input_transcript:
                        if asyncio.iscoroutinefunction(self.on_input_transcript):
                            await self.on_input_transcript(transcript, True, item_id)
                        else:
                            self.on_input_transcript(transcript, True, item_id)

                elif event_type == "response.function_call_arguments.done":
                    logger.info(f"🛠️ [QwenOmni 收到工具调用指令] call_id={event.get('call_id')} name={event.get('name')} args={event.get('arguments')}")
                    if self.on_tool_call:
                        if asyncio.iscoroutinefunction(self.on_tool_call):
                            await self.on_tool_call(event)
                        else:
                            self.on_tool_call(event)

        except websockets.exceptions.ConnectionClosed:
            logger.info("[QwenOmni] 服务端 WebSocket 连接关闭")
        except Exception as e:
            logger.error(f"[QwenOmni] 消息处理轮询异常: {e}")

    async def close(self) -> None:
        if self.ws:
            await self.ws.close()


async def handle_qwen_omni_realtime_session(
    websocket: WebSocket,
    api_key: str,
    voice_model: str,
    voice: str,
    default_city_cfg: str,
    config: dict,
    visual_broadcast_manager: Any = None,
):
    """
    Qwen-Omni Realtime 全双工语音/文本通道主处理程序。
    负责前端 WebSocket 连接透传、语音/文本/唤醒打断处理与可视化广播。
    """
    if visual_broadcast_manager is None:
        visual_broadcast_manager = _dummy_broadcast_manager
    workspace_id = os.getenv("DASHSCOPE_WORKSPACE_ID", "").strip()
    if not workspace_id:
        workspace_id = config.get("workspace_id", "")

    if not workspace_id:
        logger.error("[QwenOmni] 缺少 DASHSCOPE_WORKSPACE_ID，无法建立百炼专属 WebSocket 连接！")
        await websocket.close(code=4000, reason="DASHSCOPE_WORKSPACE_ID is missing")
        return

    today_str = time.strftime("%Y年%m月%d日")
    today_iso = time.strftime("%Y-%m-%d")
    from backend.tools import GLOBAL_TOOLS_SCHEMA, get_instructions, ToolContext, execute_tool

    instructions = get_instructions(default_city_cfg) + f"\n今天是 {today_str}（标准日期格式为 '{today_iso}'）。当用户询问天气等未指定具体日期时，date 必须默认填入今天的日期 '{today_iso}'。强约束：严禁使用通用记忆或外网知识回答天气/应急/大屏等数据，必须发起对应的工具调用！"

    turn_mode_str = config.get("qwen_omni_turn_mode", "semantic_vad")
    try:
        turn_mode = TurnDetectionMode(turn_mode_str)
    except ValueError:
        turn_mode = TurnDetectionMode.SEMANTIC_VAD

    logger.info(f"🟢 [QwenOmni 会话开启] 模型={voice_model} | 音色={voice} | 轮次={turn_mode.value}")

    session_active = True
    hangup_sent = False
    input_seq = 0
    speech_start_time = 0.0
    expecting_weather_summary = False
    audio_active = False
    input_final_sent: set = set()
    loop = asyncio.get_running_loop()
    client: Optional[QwenOmniRealtimeClient] = None

    async def _send_safe(payload: dict):
        nonlocal session_active
        if not session_active or hangup_sent:
            return
        try:
            if websocket.client_state != WebSocketState.CONNECTED:
                return
            await websocket.send_json(payload)
        except Exception as e:
            logger.warning(f"[QwenOmni] _send_safe error: {e}")
            session_active = False

    async def _send_hangup():
        nonlocal hangup_sent, session_active
        if hangup_sent:
            return
        hangup_sent = True
        session_active = False
        await _send_safe({"type": "hangup"})
        await visual_broadcast_manager.broadcast({"type": "interrupted"})
        await visual_broadcast_manager.broadcast({"type": "state_change", "state": "idle"})

    def on_interrupt():
        nonlocal audio_active, expecting_weather_summary, speech_start_time
        audio_active = False
        expecting_weather_summary = False
        speech_start_time = loop.time()
        logger.info("[QwenOmni] 用户打断 AI 播放")
        asyncio.run_coroutine_threadsafe(
            visual_broadcast_manager.broadcast({"type": "interrupted"}), loop
        )
        asyncio.run_coroutine_threadsafe(
            visual_broadcast_manager.broadcast({"type": "state_change", "state": "listening"}), loop
        )
        asyncio.run_coroutine_threadsafe(_send_safe({"type": "interrupt"}), loop)

    async def on_input_transcript(text: str, is_final: bool = True, item_id: str = ""):
        nonlocal input_seq, session_active, hangup_sent
        if not text.strip() or not session_active or hangup_sent:
            return

        exit_keywords = ["退下", "去休息吧", "退出", "挂断", "再见", "拜拜", "别说了", "闭嘴", "滚蛋"]
        if is_final and any(kw in text for kw in exit_keywords):
            logger.info(f"[QwenOmni] 退出指令 '{text}'")
            await _send_hangup()
            return

        wake_words = ["小安小安", "小安小安。", "小安", "小安。"]
        if is_final and text.strip() in wake_words:
            logger.info(f"⚡ [QwenOmni ASR 唤醒打断] 捕获到单句唤醒词 '{text}'，立刻打断并重置为倾听状态！")
            on_interrupt()
            if client:
                client._audio_suppressed = True
                client._manual_interrupt_active = True
                await client.cancel_response()
            return

        if is_final and item_id and item_id in input_final_sent:
            return

        input_seq += 1
        seq = input_seq
        tag = "🟢 [QwenOmni-ASR 完结]" if is_final else "🎙️ [QwenOmni-ASR 流式]"
        logger.info(f"{tag} 用户语音识别: '{text}'")
        await _send_safe({"type": "input_transcript", "data": text, "is_final": is_final, "seq": seq, "item_id": item_id})
        await _send_safe({"type": "debug_event", "step": "stt", "content": text, "is_final": is_final, "seq": seq})
        await visual_broadcast_manager.broadcast({"type": "asr_result", "text": text, "is_final": is_final})
        if is_final and item_id:
            input_final_sent.add(item_id)

    def on_output_transcript(text: str, response_id: str):
        if client and client._audio_suppressed:
            return
        if text.strip():
            logger.info(f"🔊 [QwenOmni AI 流式] {text}")
        asyncio.run_coroutine_threadsafe(
            visual_broadcast_manager.broadcast({"type": "subtitle", "text": text}), loop
        )
        if expecting_weather_summary:
            asyncio.run_coroutine_threadsafe(
                websocket.send_json({"type": "weather_summary", "data": text}), loop
            )
        else:
            asyncio.run_coroutine_threadsafe(
                websocket.send_json({"type": "output_transcript", "data": text}), loop
            )
        asyncio.run_coroutine_threadsafe(
            websocket.send_json({"type": "debug_event", "step": "tts", "content": text}), loop
        )

    def on_output_transcript_completed(text: str):
        nonlocal expecting_weather_summary
        if (client and client._audio_suppressed) or not text.strip():
            return
        logger.info(f"🤖 [QwenOmni AI 完结] {text.strip()}")
        if expecting_weather_summary:
            asyncio.run_coroutine_threadsafe(
                websocket.send_json({"type": "weather_summary_complete", "data": text}), loop
            )
            expecting_weather_summary = False

    def on_audio_delta(audio_bytes: bytes):
        nonlocal audio_active
        if client and client._audio_suppressed:
            return
        if not audio_active:
            audio_active = True
            asyncio.run_coroutine_threadsafe(
                visual_broadcast_manager.broadcast({"type": "state_change", "state": "speaking"}), loop
            )
        try:
            msg = bytearray(b"\x00") + audio_bytes
            asyncio.run_coroutine_threadsafe(websocket.send_bytes(bytes(msg)), loop)
        except Exception as e:
            logger.warning(f"[QwenOmni] 音频帧发送异常: {e}")

    def on_response_done(event: dict):
        nonlocal audio_active
        audio_active = False
        asyncio.run_coroutine_threadsafe(
            visual_broadcast_manager.broadcast({"type": "state_change", "state": "listening"}), loop
        )

    async def handle_tool_call(event: dict):
        nonlocal expecting_weather_summary
        call_id = event.get("call_id", "") or event.get("id", "")
        tool_name = event.get("name", "")
        raw_args = event.get("arguments", "{}")

        norm_name = normalize_tool_name(tool_name)
        logger.info(f"🔨 [QwenOmni Tool Call] {tool_name} (norm={norm_name}) args={raw_args}")

        try:
            await websocket.send_json({
                "type": "debug_event",
                "step": "intent",
                "content": f"语义分析决定调用工具: {norm_name}"
            })
        except Exception:
            pass

        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except Exception:
            args = {}

        if norm_name == "get_weather_forecast":
            expecting_weather_summary = True
        elif norm_name == "hangup":
            nonlocal session_active
            session_active = False

        try:
            ctx = ToolContext(websocket=websocket, default_city=default_city_cfg)
            result_str = await execute_tool(norm_name, args, ctx)
            logger.info(f"🔨 [QwenOmni Tool Result] {norm_name} -> {result_str[:120]}...")

            # 广播天气工具结果
            if norm_name == "get_weather_forecast":
                try:
                    w_json = json.loads(result_str)
                    await visual_broadcast_manager.broadcast({"type": "weather", "data": w_json})
                except Exception as e:
                    logger.warning(f"[QwenOmni] 广播天气失败: {e}")

            # 回传工具执行结果给 Qwen-Omni 并触发二次生成
            if client and client.ws:
                client._audio_suppressed = False
                client._manual_interrupt_active = False
                tool_output_event = {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": result_str
                    }
                }
                await client.send_event(tool_output_event)
                await client.create_response()
        except Exception as e:
            import traceback
            logger.error(f"❌ [QwenOmni Tool Exec Error] {e}\n{traceback.format_exc()}")

    client = QwenOmniRealtimeClient(
        workspace_id=workspace_id,
        api_key=api_key,
        model=voice_model,
        voice=voice,
        instructions=instructions,
        turn_mode=turn_mode,
        vad_threshold=float(config.get("qwen_omni_vad_threshold", 0.5)),
        vad_silence_ms=int(config.get("qwen_omni_silence_duration_ms", 800)),
        tools=GLOBAL_TOOLS_SCHEMA,
        on_audio_delta=on_audio_delta,
        on_input_transcript=on_input_transcript,
        on_output_transcript=on_output_transcript,
        on_output_transcript_completed=on_output_transcript_completed,
        on_interrupt=on_interrupt,
        on_response_done=on_response_done,
        on_tool_call=handle_tool_call,
    )

    try:
        await client.connect()
        msg_task = asyncio.create_task(client.handle_messages())
        asyncio.create_task(
            visual_broadcast_manager.broadcast({"type": "state_change", "state": "listening"})
        )

        while session_active:
            msg = await websocket.receive()
            if "bytes" in msg:
                data = msg["bytes"]
                if len(data) > 1 and data[0] == 0x00:
                    await client.stream_audio(data[1:])
            elif "text" in msg:
                try:
                    payload = json.loads(msg["text"])
                    p_type = payload.get("type")
                    if p_type == "hangup":
                        session_active = False
                    elif p_type == "interrupt":
                        logger.info("⚡ [QwenOmni] 收到前端唤醒硬打断指令，强行重置会话！")
                        client._audio_suppressed = True
                        client._manual_interrupt_active = True
                        await client.cancel_response()
                        asyncio.create_task(
                            visual_broadcast_manager.broadcast({"type": "state_change", "state": "listening"})
                        )
                    elif p_type == "query" or "text" in payload:
                        query_text = payload.get("text", "")
                        if query_text:
                            logger.info(f"💬 [QwenOmni Text Query] 收到前端文本指令: '{query_text}'")
                            item_event = {
                                "type": "conversation.item.create",
                                "item": {
                                    "type": "message",
                                    "role": "user",
                                    "content": [
                                        {
                                            "type": "input_text",
                                            "text": query_text
                                        }
                                    ]
                                }
                            }
                            await client.send_event(item_event)
                            await client.create_response()
                except Exception as e:
                    logger.warning(f"[QwenOmni] JSON parse error: {e}")

        msg_task.cancel()
    except WebSocketDisconnect:
        logger.info("[QwenOmni] 前端 WebSocket 连接切断")
    except Exception as e:
        logger.error(f"[QwenOmni] 会话运行异常: {e}")
    finally:
        session_active = False
        if client:
            await client.close()
        await visual_broadcast_manager.broadcast({"type": "state_change", "state": "idle"})
        logger.info("🔴 [QwenOmni 会话已关闭]")
