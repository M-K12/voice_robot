# -- coding: utf-8 --

import asyncio
import websockets
import json
import base64
import time
import logging
from typing import Optional, Callable, List, Dict, Any
from enum import Enum

logger = logging.getLogger("xiaoan.omni")

class TurnDetectionMode(Enum):
    SERVER_VAD = "server_vad"
    MANUAL = "manual"

class OmniRealtimeClient:
    """
    与 Omni Realtime API 交互的演示客户端。

    该类提供了连接 Realtime API、发送文本和音频数据、处理响应以及管理 WebSocket 连接的相关方法。

    属性说明:
        base_url (str):
            Realtime API 的基础地址。
        api_key (str):
            用于身份验证的 API Key。
        model (str):
            用于聊天的 Omni 模型名称。
        voice (str):
            服务器合成语音所使用的声音。
        turn_detection_mode (TurnDetectionMode):
            轮次检测模式。
        on_text_delta (Callable[[str], None]):
            文本增量回调函数。
        on_audio_delta (Callable[[bytes], None]):
            音频增量回调函数。
        on_input_transcript (Callable[[str], None]):
            输入转录文本回调函数。
        on_interrupt (Callable[[], None]):
            用户打断回调函数，应在此停止音频播放。
        on_output_transcript (Callable[[str], None]):
            输出转录文本回调函数。
        extra_event_handlers (Dict[str, Callable[[Dict[str, Any]], None]]):
            其他事件处理器，事件名到处理函数的映射。
    """
    def __init__(
        self,
        base_url,
        api_key: str,
        model: str = "",
        voice: Optional[str] = None,
        turn_detection_mode: TurnDetectionMode = TurnDetectionMode.SERVER_VAD,
        on_text_delta: Optional[Callable[[str], None]] = None,
        on_audio_delta: Optional[Callable[[bytes], None]] = None,
        on_interrupt: Optional[Callable[[], None]] = None,
        on_input_transcript: Optional[Callable[[str], None]] = None,
        on_output_transcript: Optional[Callable[[str], None]] = None,
        on_output_transcript_completed: Optional[Callable[[str], None]] = None,
        on_conversation_update: Optional[Callable[[str, str], None]] = None,
        extra_event_handlers: Optional[Dict[str, Callable[[Dict[str, Any]], None]]] = None
    ):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.ws = None
        self.on_text_delta = on_text_delta
        self.on_audio_delta = on_audio_delta
        self.on_interrupt = on_interrupt
        self.on_input_transcript = on_input_transcript
        self.on_output_transcript = on_output_transcript
        self.on_output_transcript_completed = on_output_transcript_completed
        self.on_conversation_update = on_conversation_update
        self.turn_detection_mode = turn_detection_mode
        self.extra_event_handlers = extra_event_handlers or {}

        # 当前输入/输出状态
        self._current_input_item_id = None
        self._current_input_text = ""
        self._current_response_id = None
        self._current_item_id = None
        self._is_responding = False
        # 输入/输出转录打印状态
        self._print_input_transcript = False
        self._output_transcript_buffer = ""
        # 对话文本缓存
        self._current_output_text = ""

    async def connect(self) -> None:
        """与 Realtime API 建立 WebSocket 连接。"""
        url = f"{self.base_url}?model={self.model}"
        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }

        self.ws = await websockets.connect(
            url, 
            extra_headers=headers,
            open_timeout=30,   # 增加连接超时到30秒
            ping_interval=20,  # 每20秒发送一次ping
            ping_timeout=20,   # ping超时时间20秒
            close_timeout=10   # 关闭超时时间10秒
        )

        # 设置默认会话配置
        payload = {
            "modalities": ["text", "audio"] if self.voice else ["text"],
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16"
        }
        if self.voice:
            payload["voice"] = self.voice

        if self.turn_detection_mode == TurnDetectionMode.MANUAL:
            payload["turn_detection"] = None
            await self.update_session(payload)
        elif self.turn_detection_mode == TurnDetectionMode.SERVER_VAD:
            payload["turn_detection"] = {
                "type": "server_vad",
                "threshold": 0.92,          # 提高 VAD 触发阈值，加强环境噪音过滤
                "prefix_padding_ms": 500,
                "silence_duration_ms": 1500,
                "create_response": False,    # 禁止 Omni 自动生成回复，只做 STT 转录
                "interrupt_response": False  # 无回复可打断，同步关闭
            }
            await self.update_session(payload)
        else:
            raise ValueError(f"Invalid turn detection mode: {self.turn_detection_mode}")

    async def send_event(self, event) -> None:
        event['event_id'] = "event_" + str(int(time.time() * 1000))
        if event.get('type') != 'input_audio_buffer.append':
            logger.debug(f"Send event: type={event['type']}, event_id={event['event_id']}")
        await self.ws.send(json.dumps(event))

    async def update_session(self, config: Dict[str, Any]) -> None:
        """更新会话配置。"""
        event = {
            "type": "session.update",
            "session": config
        }
        logger.debug(f"update session: {event}")
        await self.send_event(event)

    async def stream_audio(self, audio_chunk: bytes) -> None:
        """向 API 流式发送原始音频数据。"""
        # 仅支持 16bit 16kHz 单声道 PCM
        audio_b64 = base64.b64encode(audio_chunk).decode()

        append_event = {
            "type": "input_audio_buffer.append",
            "audio": audio_b64
        }
        await self.send_event(append_event)

    async def commit_audio_buffer(self) -> None:
        """提交音频缓冲区以触发处理。"""
        event = {
            "type": "input_audio_buffer.commit"
        }
        await self.send_event(event)

    async def append_image(self, image_chunk: bytes) -> None:
        """向视频缓冲区追加图像数据。
        图像数据可以来自本地文件，也可以来自实时视频流。

        注意:
            - 图像格式必须为 JPG 或 JPEG。推荐分辨率为 480P 或 720P，最高支持 1080P。
            - 单张图片大小不应超过 500KB。
            - 本方法会将图像数据编码为 Base64 后再发送。
            - 建议以每秒 2 帧的频率向服务器发送图像。
            - 在发送图像数据之前，需要先发送音频数据。
        """
        image_b64 = base64.b64encode(image_chunk).decode()

        event = {
            "type": "input_image_buffer.append",
            "image": image_b64
        }
        await self.send_event(event)

    async def create_response(self) -> None:
        """向 API 请求生成回复（仅在手动模式下需要调用）。"""
        event = {
            "type": "response.create",
            "response": {
                "instructions": "你是一个有用的助手。",
                "modalities": ["text", "audio"]
            }
        }
        logger.debug(f"create response: {event}")
        await self.send_event(event)

    async def cancel_response(self) -> None:
        """取消当前回复。"""
        event = {
            "type": "response.cancel"
        }
        await self.send_event(event)

    async def handle_interruption(self):
        """处理用户对当前回复的打断。"""
        if not self._is_responding:
            return

        logger.info("Handling interruption")

        # 1. 取消当前回复
        if self._current_response_id:
            await self.cancel_response()

        self._is_responding = False
        self._current_response_id = None
        self._current_item_id = None
        self._current_output_text = ""

    async def handle_messages(self) -> None:
        try:
            async for message in self.ws:
                event = json.loads(message)
                event_type = event.get("type")
                
                if event_type != "response.audio.delta":
                    logger.debug(f"event: {event}")
                else:
                    logger.debug(f"event_type: {event_type}")

                if event_type == "error":
                    logger.error(f"Error: {event['error']}")
                    continue
                elif event_type == "response.created":
                    self._current_response_id = event.get("response", {}).get("id")
                    self._is_responding = True
                    if event_type in self.extra_event_handlers:
                        self.extra_event_handlers[event_type](event)
                elif event_type == "response.output_item.added":
                    self._current_item_id = event.get("item", {}).get("id")
                    # Also check extra_event_handlers for function call detection
                    if event_type in self.extra_event_handlers:
                        self.extra_event_handlers[event_type](event)
                elif event_type == "response.done":
                    self._is_responding = False
                    self._current_response_id = None
                    self._current_item_id = None
                    # Also check extra_event_handlers for tool call processing
                    if event_type in self.extra_event_handlers:
                        self.extra_event_handlers[event_type](event)
                # Handle interruptions
                elif event_type == "input_audio_buffer.speech_started":
                    logger.debug("Speech detected")
                    if self._is_responding:
                        logger.info("Handling interruption")
                        await self.handle_interruption()
                        if self.on_interrupt:
                            logger.info("Handling on_interrupt, stop playback")
                            self.on_interrupt()
                elif event_type == "input_audio_buffer.speech_stopped":
                    logger.debug("Speech ended")
                # Handle normal response events
                elif event_type == "response.text.delta":
                    delta = event.get("delta", "")
                    self._current_output_text += delta
                    if self.on_text_delta:
                        self.on_text_delta(delta)
                    if self.on_output_transcript:
                        await asyncio.to_thread(self.on_output_transcript, self._current_output_text, self._current_response_id or "")
                elif event_type == "response.audio.delta":
                    if self.on_audio_delta:
                        audio_bytes = base64.b64decode(event["delta"])
                        self.on_audio_delta(audio_bytes)
                elif event_type == "conversation.item.input_audio_transcription.delta":
                    stash = event.get("stash", "")
                    item_id = event.get("item_id")
                    if not stash or not item_id:
                        continue
                    # 新的 utterance 开始，重置缓存
                    if item_id != self._current_input_item_id:
                        self._current_input_item_id = item_id
                        self._current_input_text = ""
                    # 仅在有变化时推送，避免重复发送
                    if stash != self._current_input_text:
                        self._current_input_text = stash
                        if self.on_input_transcript:
                            await self.on_input_transcript(stash, is_final=False, item_id=item_id)
                elif event_type == "conversation.item.input_audio_transcription.completed":
                    transcript = event.get("transcript", "")
                    item_id = event.get("item_id") or self._current_input_item_id
                    self._current_input_item_id = None
                    self._current_input_text = ""
                    if transcript and self.on_input_transcript:
                        await self.on_input_transcript(transcript, is_final=True, item_id=item_id)
                        self._print_input_transcript = True
                    # 发送用户文本到对话更新回调
                    if transcript and self.on_conversation_update:
                        await self.on_conversation_update("user", transcript)
                elif event_type == "response.audio_transcript.delta":
                    delta = event.get("delta", "")
                    self._current_output_text += delta
                    if self.on_output_transcript:
                        await asyncio.to_thread(self.on_output_transcript, self._current_output_text, self._current_response_id or "")
                elif event_type == "response.audio_transcript.done" or event_type == "response.text.done":
                    # 发送完整的AI回复文本到对话更新回调
                    if self.on_conversation_update and self._current_output_text.strip():
                        await asyncio.to_thread(self.on_conversation_update, "assistant", self._current_output_text.strip())
                    if self.on_output_transcript_completed and self._current_output_text.strip():
                        await asyncio.to_thread(self.on_output_transcript_completed, self._current_output_text.strip())
                    # 清空当前输出文本缓存
                    self._current_output_text = ""
                    self._print_input_transcript = False
                elif event_type in self.extra_event_handlers:
                    self.extra_event_handlers[event_type](event)

        except websockets.exceptions.ConnectionClosed:
            logger.info("Connection closed")
        except Exception as e:
            logger.error(f"Error in message handling: {e}")

    def flush_current_input_as_final(self):
        """兜底收敛：将当前 interim stash 作为 final 取出并清空缓存，避免重复发送。"""
        if not self._current_input_text or not self._current_input_item_id:
            return None
        text, item_id = self._current_input_text, self._current_input_item_id
        self._current_input_item_id = None
        self._current_input_text = ""
        return text, item_id

    async def close(self) -> None:
        """关闭 WebSocket 连接。"""
        if self.ws:
            await self.ws.close()

