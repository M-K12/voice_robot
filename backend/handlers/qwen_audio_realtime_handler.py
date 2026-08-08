# -*- coding: utf-8 -*-
"""
qwen-audio-3.0-realtime-plus / qwen-audio-3.0-realtime-flash 独立 WebSocket Handler
"""

import os, re, asyncio, json, base64, time, logging, traceback
from typing import Optional, Callable, Dict, Any, List
from enum import Enum

import httpx
import websockets
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

logger = logging.getLogger("xiaoan.qwen_audio_realtime")


class QwenAudioTurnMode(Enum):
    SERVER_VAD   = "server_vad"    # 声学 VAD 自动检测
    SMART_TURN   = "smart_turn"    # 智能语义轮次（声学+语义融合）
    PUSH_TO_TALK = "push_to_talk"  # 手动控制（turn_detection=null）

STATIC_VOICEPRINT_CACHE: dict[str, list[str]] = {}


def _write_voiceprint_wav(save_path: str, audio_data: bytes):
    import wave
    with wave.open(save_path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)      # 16-bit
        wf.setframerate(16000)  # 16kHz
        wf.writeframes(audio_data)


def _upload_voiceprint_file(public_base_url: str, save_path: str):
    with open(save_path, "rb") as f:
        wav_bytes = f.read()
    import urllib.request, uuid
    boundary = "----WebKitFormBoundary" + uuid.uuid4().hex
    sync_url = f"{public_base_url.rstrip('/')}/api/voiceprints"
    body = []
    body.append(f"--{boundary}".encode())
    body.append(b'Content-Disposition: form-data; name="name"')
    body.append(b'')
    body.append("动态自动首句声纹".encode('utf-8'))
    body.append(f"--{boundary}".encode())
    body.append(b'Content-Disposition: form-data; name="custom_filename"')
    body.append(b'')
    body.append("dynamic_temp.wav".encode('utf-8'))
    body.append(f"--{boundary}".encode())
    body.append(b'Content-Disposition: form-data; name="file"; filename="dynamic_temp.wav"')
    body.append(b'Content-Type: audio/wav')
    body.append(b'')
    body.append(wav_bytes)
    body.append(f"--{boundary}--".encode())
    body.append(b'')
    payload = b'\r\n'.join(body)
    req = urllib.request.Request(
        sync_url, data=payload,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=12) as resp:
        pass


class QwenAudioRealtimeClient:
    def __init__(
        self,
        workspace_id: str,
        api_key: str,
        model: str,
        voice: str = "longanqian",
        instructions: str = "",
        turn_mode: QwenAudioTurnMode = QwenAudioTurnMode.SERVER_VAD,
        vad_threshold: float = 0.5,
        vad_silence_ms: int = 800,
        max_history_turns: int = 20,
        tools: Optional[List[Dict[str, Any]]] = None,
        on_audio_delta: Optional[Callable[[bytes], None]] = None,
        on_input_transcript: Optional[Callable] = None,
        on_output_transcript: Optional[Callable] = None,
        on_output_transcript_completed: Optional[Callable] = None,
        on_interrupt: Optional[Callable] = None,
        on_response_created: Optional[Callable] = None,
        on_response_done: Optional[Callable] = None,
        on_tool_call: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        on_first_turn_completed: Optional[Callable] = None,
        on_state_change: Optional[Callable[[str], None]] = None,
        voiceprint_audio_urls: Optional[List[str]] = None,
        stream_asr_enabled: bool = True,
    ):
        self.workspace_id = workspace_id
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.instructions = instructions
        self.turn_mode = turn_mode
        self.vad_threshold = vad_threshold
        self.vad_silence_ms = vad_silence_ms
        self.max_history_turns = max_history_turns
        self.tools = tools or []
        self.voiceprint_audio_urls = voiceprint_audio_urls or []
        self.stream_asr_enabled = stream_asr_enabled
        self.on_audio_delta = on_audio_delta
        self.on_input_transcript = on_input_transcript
        self.on_output_transcript = on_output_transcript
        self.on_output_transcript_completed = on_output_transcript_completed
        self.on_interrupt = on_interrupt
        self.on_response_created = on_response_created
        self.on_response_done = on_response_done
        self.on_tool_call = on_tool_call
        self.on_error = on_error
        self.on_first_turn_completed = on_first_turn_completed
        self.on_state_change = on_state_change
        self.ws = None
        self._current_response_id: Optional[str] = None
        self._is_responding: bool = False
        self._response_done_event = asyncio.Event()
        self._response_done_event.set()
        self._audio_suppressed: bool = False
        self._manual_interrupt_active: bool = False
        self._dynamic_record_enabled = False
        self._dynamic_record_buffer = bytearray()
        self._current_output_text: str = ""
        self._current_input_item_id: Optional[str] = None
        self._current_input_text: str = ""

    async def connect(self) -> None:
        if not self.workspace_id:
            raise ValueError("[QwenAudio] DASHSCOPE_WORKSPACE_ID 不能为空，必须配置百炼业务空间 ID。")

        url = (
            f"wss://{self.workspace_id}.cn-beijing.maas.aliyuncs.com"
            f"/api-ws/v1/realtime?model={self.model}"
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "x-dashscope-dataInspection": "disable",
        }
        logger.info(f"[RealtimeVoiceEngine] 连接实时语音引擎 (音色={self.voice})")
        self.ws = await websockets.connect(
            url, extra_headers=headers,
            open_timeout=30, ping_interval=20, ping_timeout=20, close_timeout=1,
        )
        session_config: Dict[str, Any] = {
            "modalities": ["text", "audio"],
            "voice": self.voice,
            "instructions": self.instructions,
            "input_audio_format": "pcm",
            "output_audio_format": "pcm",
            "max_history_turns": self.max_history_turns,
        }
        if self.tools:
            session_config["tools"] = self.tools
        if self.turn_mode == QwenAudioTurnMode.SERVER_VAD:
            session_config["turn_detection"] = {
                "type": "server_vad",
                "threshold": self.vad_threshold,
                "silence_duration_ms": self.vad_silence_ms,
            }
        elif self.turn_mode == QwenAudioTurnMode.SMART_TURN:
            turn_detection_config = {
                "type": "smart_turn",
            }
            if self.voiceprint_audio_urls:
                turn_detection_config["voiceprint_audio_urls"] = self.voiceprint_audio_urls
            session_config["turn_detection"] = turn_detection_config

        else:
            session_config["turn_detection"] = None
        await self.ws.send(json.dumps({"type": "session.update", "session": session_config}))

    async def send_event(self, event: Dict[str, Any]) -> None:
        event["event_id"] = "event_" + str(int(time.time() * 1000))
        if event.get("type") != "input_audio_buffer.append":
            logger.debug(f"[QwenAudio] → {event['type']}")
        await self.ws.send(json.dumps(event))

    async def stream_audio(self, pcm_chunk: bytes) -> None:
        if self._dynamic_record_enabled:
            self._dynamic_record_buffer.extend(pcm_chunk)
        try:
            await self.send_event({
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(pcm_chunk).decode(),
            })
        except (websockets.exceptions.ConnectionClosed, AttributeError):
            pass

    async def commit_audio_buffer(self) -> None:
        await self.send_event({"type": "input_audio_buffer.commit"})

    async def create_response(self) -> None:
        await self.send_event({
            "type": "response.create",
            "response": {"modalities": ["audio", "text"]},
        })

    async def wait_for_response_done(self) -> None:
        if self._is_responding:
            await self._response_done_event.wait()

    async def cancel_response(self) -> None:
        await self.send_event({"type": "response.cancel"})

    async def handle_interruption(self) -> None:
        if not self._is_responding:
            return
        logger.info("[QwenAudio] Interruption: suppressing audio + cancelling response")
        self._audio_suppressed = True
        if self._current_response_id:
            try:
                await self.cancel_response()
            except Exception as e:
                logger.warning(f"[QwenAudio] cancel_response 忽略非致命异常: {e}")
        self._is_responding = False
        self._response_done_event.set()
        self._current_response_id = None
        self._current_output_text = ""

    def flush_current_input_as_final(self):
        if not self._current_input_text or not self._current_input_item_id:
            return None
        text, item_id = self._current_input_text, self._current_input_item_id
        self._current_input_item_id = None
        self._current_input_text = ""
        return text, item_id

    async def handle_messages(self) -> None:
        try:
            async for message in self.ws:
                event = json.loads(message)
                event_type = event.get("type")

                if event_type != "response.audio.delta":
                    if event_type == "error":
                        err_obj = event.get("error", {})
                        err_msg = str(err_obj.get("message", "") if isinstance(err_obj, dict) else err_obj)
                        if not ("active response" in err_msg.lower() or "already in progress" in err_msg.lower()):
                            logger.info(f"[QwenAudio] ← {event_type}")
                    else:
                        logger.info(f"[QwenAudio] ← {event_type}")

                if event_type == "error":
                    err_obj = event.get("error", {})
                    err_msg = str(err_obj.get("message", "") if isinstance(err_obj, dict) else err_obj)
                    if "active response" in err_msg.lower() or "already in progress" in err_msg.lower():
                        logger.info(f"[QwenAudio] 忽略阿里云正常打断/并发取消提醒: {err_msg}")
                    else:
                        logger.error(f"[QwenAudio] 服务端错误: {err_obj}")
                        if self.on_error:
                            self.on_error(err_obj)
                    self._is_responding = False
                    self._response_done_event.set()

                elif event_type == "voiceprint_audio_list.in_progress":
                    item_id = event.get("item_id", "")
                    logger.info(f"🎙️ [QwenAudio 声纹注册] 阿里云已接收配置，正在异步下载声纹音频并提取特征... (task_id: {item_id})")

                elif event_type == "voiceprint_audio_list.completed":
                    item_id = event.get("item_id", "")
                    logger.info(f"🎉 [QwenAudio 声纹注册] ✅ 阿里云服务端声纹特征提取成功！声纹锁已真正生效！(task_id: {item_id})")

                elif event_type == "voiceprint_audio_list.failed":
                    item_id = event.get("item_id", "")
                    reason = event.get("reason", "未知原因")
                    logger.error(f"❌ [QwenAudio 声纹注册] 阿里云服务端声纹注册失败！原因: {reason} (task_id: {item_id})")

                elif event_type == "conversation.item.ambient_audio_transcription.completed":
                    text = event.get("text", "")
                    if text.strip():
                        logger.info(f"🗣️ [QwenAudio 旁人/环境音] 过滤非目标说话人人声: 『{text.strip()}』")

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
                    logger.info("🎙️ [QwenAudio VAD] 检测到用户开始说话 (speech_started)")
                    if self.on_state_change:
                        self.on_state_change("listening")
                    if self._is_responding:
                        await self.handle_interruption()
                        if self.on_interrupt:
                            self.on_interrupt()

                elif event_type == "input_audio_buffer.speech_stopped":
                    logger.debug("[QwenAudio] VAD 检测到用户说话结束 (speech_stopped)")
                    if self.on_state_change:
                        self.on_state_change("thinking")
                    if self.turn_mode == QwenAudioTurnMode.PUSH_TO_TALK:
                        await self.commit_audio_buffer()

                elif event_type == "conversation.item.created":
                    item = event.get("item", {})
                    if item.get("role") == "user":
                        contents = item.get("content", [])
                        for c in contents:
                            if isinstance(c, dict):
                                text = c.get("transcript", "") or c.get("text", "")
                                if text and self.stream_asr_enabled and self.on_input_transcript:
                                    item_id = item.get("id", "")
                                    self._current_input_text = text
                                    await self.on_input_transcript(self._current_input_text, is_final=False, item_id=item_id)

                elif event_type == "response.audio.delta":
                    if not self._audio_suppressed and self.on_audio_delta:
                        self.on_audio_delta(base64.b64decode(event["delta"]))

                elif event_type == "response.audio_transcript.delta":
                    self._current_output_text += event.get("delta", "")
                    if self.on_output_transcript:
                        await asyncio.to_thread(
                            self.on_output_transcript,
                            self._current_output_text,
                            self._current_response_id or "",
                        )

                elif event_type == "response.audio_transcript.done":
                    final_text = event.get("transcript", "") or self._current_output_text
                    if final_text.strip() and self.on_output_transcript_completed:
                        await asyncio.to_thread(self.on_output_transcript_completed, final_text.strip())
                    self._current_output_text = ""

                elif event_type == "response.text.done":
                    final_text = event.get("text", "") or self._current_output_text
                    if final_text.strip() and self.on_output_transcript_completed:
                        await asyncio.to_thread(self.on_output_transcript_completed, final_text.strip())
                    self._current_output_text = ""

                elif event_type in (
                    "conversation.item.input_audio_transcription.delta",
                    "conversation.item.input_audio_transcription.text",
                    "conversation.item.input_audio_transcription.partial",
                    "conversation.item.input_audio_transcription",
                    "input_audio_transcription.delta",
                ):
                    delta_text = event.get("delta", "") or event.get("text", "") or event.get("transcript", "")
                    item_id = event.get("item_id") or self._current_input_item_id
                    if delta_text:
                        if delta_text.startswith(self._current_input_text) and len(delta_text) > len(self._current_input_text):
                            self._current_input_text = delta_text
                        elif self._current_input_text.startswith(delta_text):
                            pass
                        else:
                            self._current_input_text += delta_text
                        if self.stream_asr_enabled and self.on_input_transcript:
                            await self.on_input_transcript(self._current_input_text, is_final=False, item_id=item_id or "")

                elif event_type == "conversation.item.input_audio_transcription.completed":
                    transcript = event.get("transcript", "") or self._current_input_text
                    item_id = event.get("item_id") or self._current_input_item_id
                    self._current_input_text = ""
                    self._current_input_item_id = None
                    if transcript and self.on_input_transcript:
                        await self.on_input_transcript(transcript, is_final=True, item_id=item_id or "")

                    if self._dynamic_record_enabled:

                        self._dynamic_record_enabled = False
                        audio_data = bytes(self._dynamic_record_buffer)
                        self._dynamic_record_buffer.clear()
                        if transcript and self.on_first_turn_completed:
                            asyncio.create_task(self.on_first_turn_completed(transcript, audio_data))

                elif event_type == "response.function_call_arguments.done":
                    logger.info(f"🛠️ [QwenAudio 收到工具调用指令] call_id={event.get('call_id')} name={event.get('name')} args={event.get('arguments')}")
                    if self.on_tool_call:
                        self.on_tool_call(event)

        except websockets.exceptions.ConnectionClosed:
            logger.info("[QwenAudio] Connection closed")
        except Exception as e:
            logger.error(f"[QwenAudio] handle_messages error: {e}")
            traceback.print_exc()

    async def close(self) -> None:
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass


async def handle_qwen_audio_realtime_session(
    websocket: WebSocket,
    voice: str,
    config: dict,
    visual_broadcast_manager,
) -> None:
    from utils import get_tool_calling_mode, normalize_tool_name, is_exit_intent, is_wake_word, send_session_hangup
    from tools import GLOBAL_TOOLS_SCHEMA, get_prompt, ToolContext, execute_tool

    default_city = config.get("default_city", "")
    instructions = get_prompt(default_city)
    api_key = os.getenv("DASHSCOPE_API_KEY", "")
    workspace_id = os.getenv("DASHSCOPE_WORKSPACE_ID", "")
    voice_model = config.get("voice_model_name", "qwen-audio-3.0-realtime-plus")
    voice = config.get("current_voice") or config.get("voice") or voice

    if not api_key:
        await websocket.close(code=4000, reason="API Key is missing")
        return

    if not workspace_id:
        try:
            await websocket.send_json({
                "type": "error",
                "message": "后端缺少 DASHSCOPE_WORKSPACE_ID 配置，调用百炼 Qwen-Audio WebSocket 接口必须在 .env 文件中添加业务空间 ID。"
            })
        except Exception:
            pass
        await websocket.close(code=4001, reason="Workspace ID is missing")
        return

    from datetime import datetime
    today_str = datetime.now().strftime("%Y-%m-%d")

    vp_mode = config.get("qwen_audio_voiceprint_mode", "none")
    selected_vp_id = config.get("selected_voiceprint_id", "")
    stream_asr_enabled = bool(config.get("stream_asr_enabled", True))
    
    turn_mode_str = config.get("qwen_audio_turn_mode", "server_vad")
    voiceprint_audio_urls = []
    vp_server_url = config.get("voiceprint_server_url") or os.getenv("VOICEPRINT_SERVER_URL", "http://8.141.83.146:8777").rstrip("/")

    if vp_mode == "static":
        if selected_vp_id in STATIC_VOICEPRINT_CACHE and STATIC_VOICEPRINT_CACHE[selected_vp_id]:
            voiceprint_audio_urls = STATIC_VOICEPRINT_CACHE[selected_vp_id]
            logger.info(f"🎙️ [QwenAudio 声纹] 命中启动预加载缓存【静态绑定角色: 『{selected_vp_id}』】 -> 秒级装载 {len(voiceprint_audio_urls)}/5 份采样矩阵: {voiceprint_audio_urls}")
            turn_mode_str = "smart_turn"
        else:
            voiceprint_audio_urls = await _fetch_role_voiceprint_urls(selected_vp_id, vp_server_url)
            if voiceprint_audio_urls:
                STATIC_VOICEPRINT_CACHE[selected_vp_id] = voiceprint_audio_urls
                logger.info(f"🎙️ [QwenAudio 声纹] 已激活【静态绑定角色: 『{selected_vp_id}』】 -> 动态抓取 {len(voiceprint_audio_urls)}/5 份采样矩阵: {voiceprint_audio_urls}")
                turn_mode_str = "smart_turn"
            else:
                logger.warning(f"⚠️ [QwenAudio 声纹] 选中了静态声纹角色 '{selected_vp_id}'，但未能从声纹服务({vp_server_url})获取到可用采样！本次降级使用【不锁声纹模式】")
                voiceprint_audio_urls = []
                turn_mode_str = "server_vad"

    elif vp_mode == "dynamic":
        turn_mode_str = "server_vad"
        voiceprint_audio_urls = []
        logger.info("🎙️ [QwenAudio 声纹] 已激活【自动首句锁定】 -> 首个回合以 server_vad 捕获特征，回答结束后无感升级 smart_turn 声纹锁定...")
    else:
        urls_raw = config.get("qwen_audio_voiceprint_audio_urls", [])
        if isinstance(urls_raw, list):
            voiceprint_audio_urls = [str(u).strip() for u in urls_raw if str(u).strip()]
        elif isinstance(urls_raw, str):
            split_char = "\n" if "\n" in urls_raw else ","
            voiceprint_audio_urls = [u.strip() for u in urls_raw.split(split_char) if u.strip()]
        if voiceprint_audio_urls:
            log_msg = f"🎙️ [QwenAudio 声纹] 已激活【手动 URL 声纹】 -> 共 {len(voiceprint_audio_urls)} 条参考音频链接，已自动升阶为 smart_turn 模式"
            logger.info(log_msg)
            turn_mode_str = "smart_turn"
        if not voiceprint_audio_urls:
            log_msg = "🎙️ [QwenAudio 声纹] 当前声纹模式: 【无锁定】 (未使用任何声纹参考音频，不限制发言人)"
            logger.info(log_msg)

    turn_mode = {
        "server_vad": QwenAudioTurnMode.SERVER_VAD,
        "smart_turn": QwenAudioTurnMode.SMART_TURN,
        "push_to_talk": QwenAudioTurnMode.PUSH_TO_TALK,
    }.get(turn_mode_str, QwenAudioTurnMode.SERVER_VAD)

    vad_threshold = float(config.get("vad_threshold", 0.5))
    vad_silence_ms = int(config.get("vad_silence_duration_ms", 450))
    max_history_turns = int(config.get("qwen_audio_max_history_turns", 20))
    tool_mode = get_tool_calling_mode("voice", voice_model)
    instructions = get_prompt(default_city)

    logger.info(f"🟢 [QwenAudio 会话开启] 模型={voice_model} | 音色={voice} | 轮次={turn_mode.value} | 工具={tool_mode}")

    session_active = True
    hangup_sent = False
    input_seq = 0
    speech_start_time = 0.0
    expecting_weather_summary = False
    audio_active = False
    is_first_audio_frame = True
    tool_lock = asyncio.Lock()
    input_final_sent: set = set()
    MAX_FINAL_SENT_HISTORY = 100
    loop = asyncio.get_running_loop()
    client: Optional[QwenAudioRealtimeClient] = None

    async def _send_safe(payload: dict):
        nonlocal session_active
        if not session_active or hangup_sent:
            return
        try:
            if websocket.client_state != WebSocketState.CONNECTED:
                return
            await websocket.send_json(payload)
        except Exception as e:
            logger.warning(f"[QwenAudio] _send_safe error: {e}")
            session_active = False

    async def _send_hangup():
        nonlocal hangup_sent, session_active
        if hangup_sent:
            return
        hangup_sent = True
        session_active = False
        logger.info("🤖 [QwenAudio AI 完结] 捕获到退出指令，会话平滑挂断")
        if client:
            client._audio_suppressed = True
            client._manual_interrupt_active = True
            try:
                await client.cancel_response()
            except Exception as e:
                logger.debug(f"[QwenAudio] cancel_response on hangup: {e}")
        await send_session_hangup(
            websocket=websocket,
            visual_broadcast_manager=visual_broadcast_manager,
            client=client
        )

    def on_interrupt():
        nonlocal audio_active, expecting_weather_summary, speech_start_time
        audio_active = False
        expecting_weather_summary = False
        speech_start_time = loop.time()
        logger.info("[QwenAudio] 用户打断 AI 播放")
        asyncio.run_coroutine_threadsafe(
            visual_broadcast_manager.broadcast({"type": "interrupted"}), loop)
        asyncio.run_coroutine_threadsafe(
            visual_broadcast_manager.broadcast({"type": "state_change", "state": "listening"}), loop)
        asyncio.run_coroutine_threadsafe(_send_safe({"type": "state_change", "state": "listening"}), loop)
        asyncio.run_coroutine_threadsafe(_send_safe({"type": "interrupt"}), loop)

    def on_state_change(state: str):
        asyncio.run_coroutine_threadsafe(
            visual_broadcast_manager.broadcast({"type": "state_change", "state": state}), loop)
        asyncio.run_coroutine_threadsafe(
            _send_safe({"type": "state_change", "state": state}), loop)

    async def on_input_transcript(text: str, is_final: bool = True, item_id: str = ""):
        nonlocal input_seq, session_active, hangup_sent
        if not text.strip() or not session_active or hangup_sent:
            return
        if not is_final:
            return

        if is_final and is_exit_intent(text):
            logger.info(f"[QwenAudio] 捕获完结句退出指令 (is_final=True): '{text}'")
            await _send_hangup()
            return

        if is_wake_word(text):
            logger.info(f"⚡ [QwenAudio ASR 唤醒打断] 捕获到唤醒词 '{text}'，立刻打断并重置为倾听状态（不推送至前端展示）！")
            on_interrupt()
            client._audio_suppressed = True
            client._manual_interrupt_active = True
            await client.cancel_response()
            return

        if is_final and item_id and item_id in input_final_sent:
            return

        input_seq += 1
        seq = input_seq
        tag = "🟢 [QwenAudio-ASR 完结]" if is_final else "🎙️ [QwenAudio-ASR 流式]"
        logger.info(f"{tag} 用户语音识别: '{text}'")
        await _send_safe({"type": "input_transcript", "data": text, "is_final": is_final, "seq": seq, "item_id": item_id})
        await _send_safe({"type": "debug_event", "step": "stt", "content": text, "is_final": is_final, "seq": seq})
        await visual_broadcast_manager.broadcast({"type": "asr_result", "text": text, "is_final": is_final})
        if is_final and speech_start_time:
            latency_ms = int((loop.time() - speech_start_time) * 1000)
            await _send_safe({"type": "debug_event", "step": "stt_latency", "latency_ms": latency_ms})
        if is_final and item_id:
            input_final_sent.add(item_id)
            while len(input_final_sent) > MAX_FINAL_SENT_HISTORY:
                input_final_sent.pop()

    def on_output_transcript(text: str, response_id: str):
        if client._audio_suppressed:
            return
        clean = re.sub(r"<[^>]+>", "", text).strip()
        if not clean:
            return
        logger.info(f"🔊 [QwenAudio AI 流式] {clean}")
        asyncio.run_coroutine_threadsafe(
            visual_broadcast_manager.broadcast({"type": "subtitle", "text": clean}), loop)
        if expecting_weather_summary:
            asyncio.run_coroutine_threadsafe(
                websocket.send_json({"type": "weather_summary", "data": clean}), loop)
        else:
            asyncio.run_coroutine_threadsafe(
                websocket.send_json({"type": "output_transcript", "data": clean}), loop)
        asyncio.run_coroutine_threadsafe(
            websocket.send_json({"type": "debug_event", "step": "tts", "content": clean}), loop)

    def on_output_transcript_completed(text: str):
        nonlocal expecting_weather_summary
        if client._audio_suppressed:
            return
        clean = re.sub(r"<[^>]+>", "", text).strip()
        if not clean:
            return
        logger.info(f"🤖 [QwenAudio AI 完结] {clean}")
        if expecting_weather_summary:
            expecting_weather_summary = False
            asyncio.run_coroutine_threadsafe(
                websocket.send_json({"type": "weather_summary", "data": clean}), loop)
            asyncio.run_coroutine_threadsafe(
                visual_broadcast_manager.broadcast({"type": "subtitle", "text": clean}), loop)
        
        asyncio.run_coroutine_threadsafe(
            websocket.send_json({"type": "output_transcript_done"}), loop)

    def on_audio_delta(audio_bytes: bytes):
        nonlocal is_first_audio_frame, audio_active
        if not audio_active:
            return
        if is_first_audio_frame:
            is_first_audio_frame = False
            asyncio.run_coroutine_threadsafe(
                visual_broadcast_manager.broadcast({"type": "state_change", "state": "speaking"}), loop)
        asyncio.run_coroutine_threadsafe(websocket.send_bytes(b"\x00" + audio_bytes), loop)

    def on_response_created(event):
        nonlocal is_first_audio_frame, audio_active
        audio_active = True
        is_first_audio_frame = True
        if client:
            flushed = client.flush_current_input_as_final()
            if flushed:
                text, item_id = flushed
                asyncio.run_coroutine_threadsafe(
                    on_input_transcript(text, is_final=True, item_id=item_id), loop)
        asyncio.run_coroutine_threadsafe(
            visual_broadcast_manager.broadcast({"type": "state_change", "state": "thinking"}), loop)

    def on_response_done(event):
        nonlocal audio_active
        audio_active = False
        asyncio.run_coroutine_threadsafe(
            visual_broadcast_manager.broadcast({"type": "state_change", "state": "idle"}), loop)
        asyncio.run_coroutine_threadsafe(_send_safe({"type": "state_change", "state": "listening"}), loop)
        if _dynamic_vp_ready and not _switched_to_smart_turn:
            asyncio.run_coroutine_threadsafe(_try_seamless_switch_to_smart_turn(), loop)

    pending_tool_calls_count = 0
    pending_tool_lock = asyncio.Lock()

    async def handle_tool_call(event: dict):
        nonlocal session_active, expecting_weather_summary, pending_tool_calls_count

        async def do_call():
            nonlocal session_active, expecting_weather_summary, pending_tool_calls_count
            call_id = event.get("call_id")
            name = normalize_tool_name(event.get("name"))
            arguments_str = event.get("arguments", "{}")
            try:
                await websocket.send_json({
                    "type": "debug_event", "step": "intent",
                    "content": f"根据您的需求，意图分析决定调用本地工具: {name}",
                })
            except Exception:
                pass
            try:
                ctx = ToolContext(
                    websocket=websocket,
                    default_city=default_city,
                    expecting_weather_summary=expecting_weather_summary,
                    session_active=session_active,
                )
                result_payload = await execute_tool(name, arguments_str, ctx)
                expecting_weather_summary = ctx.expecting_weather_summary
                session_active = ctx.session_active
            except Exception as e:
                logger.error(f"[QwenAudio Tool] execute error: {e}")
                traceback.print_exc()
                result_payload = json.dumps({"error": str(e)})
            try:
                await client.send_event({
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": result_payload,
                    },
                })
                async with pending_tool_lock:
                    pending_tool_calls_count -= 1
                    should_trigger_response = (pending_tool_calls_count == 0)

                if should_trigger_response:
                    await client.create_response()
            except Exception as e:
                logger.error(f"[QwenAudio Tool] send result error: {e}")

        if tool_mode == "serial":
            async with tool_lock:
                await do_call()
        else:
            await do_call()

    def on_tool_call(event: dict):
        nonlocal pending_tool_calls_count
        asyncio.create_task(async_inc_and_run(event))

    async def async_inc_and_run(event: dict):
        nonlocal pending_tool_calls_count
        async with pending_tool_lock:
            pending_tool_calls_count += 1
        await handle_tool_call(event)

    def on_error(error_payload):
        err_msg = ""
        if isinstance(error_payload, dict):
            err_msg = error_payload.get("message", "未知错误")
        else:
            err_msg = str(error_payload)

        non_fatal_keywords = [
            "manual response is already in progress", 
            "Server VAD turn committed", 
            "no active response",
            "Conversation has no active response",
            "Cannot create response while user is speaking",
            "user is speaking"
        ]
        if any(kw in err_msg for kw in non_fatal_keywords):
            logger.debug(f"[QwenAudio] 忽略服务端非致命状态提示: {err_msg}")
            return

        logger.error(f"[QwenAudio Client Error] 服务端错误: {error_payload}")

        asyncio.run_coroutine_threadsafe(
            websocket.send_json({
                "type": "error",
                "message": f"百炼 API 服务端报错: {err_msg}"
            }),
            loop
        )
        asyncio.run_coroutine_threadsafe(_send_hangup(), loop)

    _dynamic_vp_ready = False
    _switched_to_smart_turn = False
    _ready_vp_urls = []

    async def _async_upload_dynamic_vp(audio_data: bytes):
        nonlocal _dynamic_vp_ready, _ready_vp_urls
        public_base_url = os.getenv("VITE_PUBLIC_BASE_URL", "").rstrip("/")
        base_url = public_base_url or vp_server_url
        save_dir = "backend/voiceprints"
        os.makedirs(save_dir, exist_ok=True)
        save_path = os.path.join(save_dir, "dynamic_temp.wav")
        try:
            await asyncio.to_thread(_write_voiceprint_wav, save_path, audio_data)
            print(f"\033[96m[QwenAudio] 动态临时声纹本地保存成功: {save_path}\033[0m")
            
            if public_base_url and "127.0.0.1" not in public_base_url and "localhost" not in public_base_url:
                await asyncio.to_thread(_upload_voiceprint_file, public_base_url, save_path)
                logger.info("[QwenAudio Sync] 动态声纹后台成功同步推送到公网服务器！已就绪。")

            _ready_vp_urls = [f"{base_url}/voiceprints/dynamic_temp.wav"]
            _dynamic_vp_ready = True
            asyncio.create_task(_try_seamless_switch_to_smart_turn())
        except Exception as sync_err:
            logger.warning(f"[QwenAudio Sync Warning] 后台异步推送动态声纹失败: {sync_err}")

    async def _try_seamless_switch_to_smart_turn():
        nonlocal client, msg_task, turn_mode, voiceprint_audio_urls, _switched_to_smart_turn
        if not _dynamic_vp_ready or _switched_to_smart_turn or audio_active:
            return
        _switched_to_smart_turn = True
        logger.info("[QwenAudio] 动态声纹在空闲期静默就绪，开始平滑替换为 smart_turn 锁...")
        voiceprint_audio_urls = _ready_vp_urls
        old_client = client
        old_msg_task = msg_task
        try:
            old_msg_task.cancel()
            await old_client.close()
        except Exception:
            pass
        try:
            client = QwenAudioRealtimeClient(
                workspace_id=workspace_id,
                api_key=api_key,
                model=voice_model,
                voice=voice,
                instructions=instructions,
                turn_mode=QwenAudioTurnMode.SMART_TURN,
                vad_threshold=vad_threshold,
                vad_silence_ms=vad_silence_ms,
                max_history_turns=max_history_turns,
                tools=GLOBAL_TOOLS_SCHEMA,
                on_audio_delta=on_audio_delta,
                on_input_transcript=on_input_transcript,
                on_output_transcript=on_output_transcript,
                on_output_transcript_completed=on_output_transcript_completed,
                on_interrupt=on_interrupt,
                on_response_created=on_response_created,
                on_response_done=on_response_done,
                on_tool_call=on_tool_call,
                on_error=on_error,
                on_state_change=on_state_change,
                voiceprint_audio_urls=voiceprint_audio_urls,
                stream_asr_enabled=stream_asr_enabled,
            )
            await client.connect()
            msg_task = asyncio.create_task(client.handle_messages())
            logger.info("[QwenAudio] 幕后无感升级完成！后续轮次已锁定当前说话人声纹。")
        except Exception as e:
            logger.error(f"[QwenAudio] 静默升级切换声纹 Client 失败: {e}")

    async def on_first_turn_completed(transcript: str, audio_data: bytes):
        if vp_mode != "dynamic" or _dynamic_vp_ready:
            return
            
        logger.info(f"[QwenAudio] 动态声纹捕获：第一轮用户发言已结束。字节: {len(audio_data)}, 转写: '{transcript}'")
        if len(audio_data) < 1000:
            logger.warning("[QwenAudio Warning] 音频太短，跳过动态声纹录制。")
            return

        asyncio.create_task(_async_upload_dynamic_vp(audio_data))

    try:
        client = QwenAudioRealtimeClient(
            workspace_id=workspace_id,
            api_key=api_key,
            model=voice_model,
            voice=voice,
            instructions=instructions,
            turn_mode=turn_mode,
            vad_threshold=vad_threshold,
            vad_silence_ms=vad_silence_ms,
            max_history_turns=max_history_turns,
            tools=GLOBAL_TOOLS_SCHEMA,
            on_audio_delta=on_audio_delta,
            on_input_transcript=on_input_transcript,
            on_output_transcript=on_output_transcript,
            on_output_transcript_completed=on_output_transcript_completed,
            on_interrupt=on_interrupt,
            on_response_created=on_response_created,
            on_response_done=on_response_done,
            on_tool_call=on_tool_call,
            on_error=on_error,
            on_first_turn_completed=on_first_turn_completed,
            on_state_change=on_state_change,
            voiceprint_audio_urls=voiceprint_audio_urls,
            stream_asr_enabled=stream_asr_enabled,
        )
        if vp_mode == "dynamic":
            client._dynamic_record_enabled = True

        await client.connect()
        msg_task = asyncio.create_task(client.handle_messages())
        asyncio.create_task(
            visual_broadcast_manager.broadcast({"type": "state_change", "state": "listening"}))

        while session_active:
            msg = await websocket.receive()
            if "bytes" in msg:
                data = msg["bytes"]
                if len(data) > 1 and data[0] == 0x00:
                    await client.stream_audio(data[1:])
            elif "text" in msg:
                try:
                    payload = json.loads(msg["text"])
                    if payload.get("type") == "hangup":
                        session_active = False
                    elif payload.get("type") == "interrupt":
                        logger.info("⚡ [QwenAudio] 收到前端唤醒词硬打断重置指令，立刻强行重置会话状态！")
                        client._audio_suppressed = True
                        client._manual_interrupt_active = True
                        await client.cancel_response()
                        asyncio.create_task(
                            visual_broadcast_manager.broadcast({"type": "state_change", "state": "listening"})
                        )
                        await _send_safe({"type": "state_change", "state": "listening"})
                        await _send_safe({"type": "interrupt"})
                    elif payload.get("type") == "query":
                        text = payload.get("text", "").strip()
                        exit_kws = ["退下", "去休息吧", "退出", "挂断", "再见", "拜拜", "别说了", "闭嘴", "滚蛋"]
                        if any(kw in text for kw in exit_kws):
                            await _send_safe({"type": "hangup"})
                            session_active = False
                except Exception:
                    pass
        msg_task.cancel()

    except (WebSocketDisconnect, websockets.exceptions.ConnectionClosed):
        logger.info("[QwenAudio] 前端 WebSocket 正常断开")
    except asyncio.CancelledError:
        logger.info("[QwenAudio] 会话任务已被正常取消")
    except RuntimeError as e:
        if "receive" in str(e) or "disconnect" in str(e):
            logger.info(f"[QwenAudio] WebSocket 正常断开 ({e})")
        else:
            logger.error(f"[QwenAudio] 运行时异常: {e}")
    except Exception as e:
        logger.error(f"[QwenAudio] 会话异常: {e}")
    finally:
        session_active = False
        if client:
            try:
                await client.close()
            except Exception:
                pass
        logger.info("🔴 [QwenAudio 会话已关闭]")


async def _fetch_role_voiceprint_urls(role_name: str, base_url: str) -> List[str]:
    if not role_name:
        return []
    target_server = base_url.rstrip("/") if base_url else os.getenv("VOICEPRINT_SERVER_URL", "http://8.141.83.146:8777").rstrip("/")
    api_url = f"{target_server}/api/voiceprints"
    try:
        async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
            resp = await client.get(api_url)
            if resp.status_code == 200:
                roles = resp.json()
                if isinstance(roles, list):
                    for role in roles:
                        if role.get("id") == role_name or role.get("name") == role_name:
                            urls = role.get("urls", [])
                            fixed_urls = []
                            for u in urls[:5]:
                                if "/voiceprints/" in u:
                                    parts = u.split("/voiceprints/")
                                    fixed_urls.append(f"{target_server}/voiceprints/{parts[1]}")
                                else:
                                    fixed_urls.append(u)
                            return fixed_urls
    except Exception as e:
        logger.warning(f"[QwenAudio 声纹] 从 API 获取指定角色『{role_name}』采样失败 ({api_url}): {e}")
    return []


async def preload_static_voiceprints(config: Optional[dict] = None) -> List[str]:
    global STATIC_VOICEPRINT_CACHE
    if config is None:
        try:
            from utils import load_config
            config = load_config()
        except Exception as e:
            logger.warning(f"[QwenAudio 声纹预加载] 读取配置失败: {e}")
    voice_model = config.get("voice_model_name", "")
    if not voice_model or "qwen-audio" not in voice_model.lower():
        return []

    vp_mode = config.get("qwen_audio_voiceprint_mode", "none")
    selected_vp_id = config.get("selected_voiceprint_id", "")

    if vp_mode == "static" and selected_vp_id:
        vp_server_url = config.get("voiceprint_server_url") or os.getenv("VOICEPRINT_SERVER_URL", "http://8.141.83.146:8777").rstrip("/")
        logger.info(f"⚡ [QwenAudio 声纹预加载] 启动立即预加载静态角色『{selected_vp_id}』的声纹采样 (服务端: {vp_server_url})...")
        urls = await _fetch_role_voiceprint_urls(selected_vp_id, vp_server_url)
        if urls:
            STATIC_VOICEPRINT_CACHE[selected_vp_id] = urls
            logger.info(f"🎉 [QwenAudio 声纹预加载完成] ✅ 静态角色『{selected_vp_id}』成功装载 {len(urls)}/5 份采样矩阵: {urls}")
            return urls
        else:
            logger.warning(f"⚠️ [QwenAudio 声纹预加载] 服务端未查到角色『{selected_vp_id}』的可用声纹采样文件。")
    return []


async def maybe_preload_voiceprints(config: dict) -> None:
    """
    门卫包装函数：仅在配置使用 qwen-audio 模型时才触发声纹预加载。
    调用方无需自行判断 voice_model_name 条件，直接调用即可。
    """
    voice_model = config.get("voice_model_name", "")
    if voice_model and "qwen-audio" in voice_model.lower():
        await preload_static_voiceprints(config)
