import os
import sys
import time
import json
import asyncio
import threading
from PySide6.QtCore import QObject, Signal, Slot, QTimer
import websockets
import httpx
from loguru import logger

from pyside_app.core.audio_player import AudioPlayer
from pyside_app.core.config_helper import load_app_config

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class VoiceBotEngine(QObject):
    """
    小安语音机器人主核心引擎 (100% 对齐 App.vue 音频物理解包规范)
    """
    signal_chat_message = Signal(str, str)     # role ("user", "bot", "bot_stream"), content
    signal_weather_updated = Signal(dict)     # 天气结构数据
    signal_state_changed = Signal(str)         # "idle", "listening", "speaking", "thinking"
    signal_debug_event = Signal(str, object)   # step ("kws", "stt", "llm", "tts", "tool_call", "tool_result", "control"), content (str or dict)
    signal_reset_idle_timer = Signal()         # 内部跨线程信号：刷新休眠定时器
    signal_stop_idle_timer = Signal()          # 内部跨线程信号：停止休眠定时器
    signal_backend_status = Signal(bool)       # 后端在线/离线状态 (True/False)，与 App.vue 完全一致

    def __init__(self, parent=None):
        super().__init__(parent)
        self.in_call = False
        self.ws_loop = None
        self.ws_thread = None
        self.ws_connection = None
        self.pcm_queue = None
        self.chat_history = []
        self._loop_lock = threading.Lock()

        # 启动持久化的独立 asyncio 事件循环后台线程与常驻 WS 通道
        self._start_event_loop()

        # 音频流播放引擎
        self.audio_player = AudioPlayer()
        self.audio_player.signal_state_changed.connect(self._on_audio_state_changed)

        # 无语音输入自动挂断/休眠定时器 (安全绑定到主线程槽)
        self.idle_timer = QTimer(self)
        self.idle_timer.setSingleShot(True)
        self.idle_timer.timeout.connect(self._on_idle_timeout)

        self.signal_reset_idle_timer.connect(self._reset_idle_timer)
        self.signal_stop_idle_timer.connect(self._stop_idle_timer)

    def is_backend_online(self) -> bool:
        """获取最新保存的后端健康连通状态"""
        return getattr(self, "_backend_online", False)

    def _start_event_loop(self):
        def run_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self.ws_loop = loop
            asyncio.run_coroutine_threadsafe(self._start_persistent_ws(), loop)
            asyncio.run_coroutine_threadsafe(self._start_health_polling(), loop)
            loop.run_forever()

        self.ws_thread = threading.Thread(target=run_loop, daemon=True)
        self.ws_thread.start()

    async def _start_health_polling(self):
        """后端 HTTP /health 健康探针轮询 (每 3 秒检测一次，直接同步 UI)"""
        base_http = self._get_backend_url()
        health_url = f"{base_http}/health"
        last_online = None

        async with httpx.AsyncClient(trust_env=False, timeout=2.0) as client:
            while True:
                try:
                    resp = await client.get(health_url)
                    is_online = (resp.status_code == 200)
                except Exception:
                    is_online = False

                self._backend_online = is_online
                # 仅在状态变化时记录日志，避免控制台刷屏
                if is_online != last_online:
                    last_online = is_online
                    logger.info(f"[BotEngine Health] 后端 HTTP 健康探针 -> {'🟢 在线 (ON)' if is_online else '🔴 离线 (OFF)'}")

                # 每 3 秒检测完直接发射信号，确保 UI 实时最新
                self.signal_backend_status.emit(is_online)
                await asyncio.sleep(3.0)

    def handle_kws_wakeup(self, keyword: str):
        """KWS 唤醒词统一入口：根据当前通话状态，智能拆分为『休眠唤醒』与『通话中打断』两大独立场景"""
        if self.in_call:
            self.handle_incall_interrupt(source=f"kws_{keyword}")
        else:
            self.handle_idle_wakeup(keyword)

    def handle_idle_wakeup(self, keyword: str):
        """场景一：休眠唤醒 -> 播放『在呢』提示音，开启语音通话场景"""
        logger.info(f"[BotEngine] ✨ [休眠唤醒场景] 命中唤醒词: {keyword}")
        self.signal_debug_event.emit("kws", f"休眠唤醒: {keyword}")
        
        # 1. 播放响应提示音 "在"
        self.play_prompt_sound("zai")
        
        # 2. 开启语音通话 (发送 wakeup 控制命令)
        self.start_voice_call(trigger_source="kws")

    def handle_incall_interrupt(self, source: str = "barge_in"):
        """场景二：通话中打断 -> 物理秒切音频播报，发送 interrupt 信号给后端，严禁播放『在呢』提示音"""
        logger.info(f"[BotEngine] ⚡ [通话中打断场景] 触发源: {source}")
        self.signal_debug_event.emit("interrupt", f"通话打断 ({source})")

        # 1. 瞬间物理切断本地所有音频输出，清空播报队列
        self.audio_player.stop()

        # 2. 向后端 WebSocket 发送通用打断事件
        if self.ws_connection and self.ws_loop and self.ws_loop.is_running():
            async def _send_interrupt_cmd():
                try:
                    await self.ws_connection.send(json.dumps({"type": "interrupt"}))
                except Exception as e:
                    logger.error(f"[BotEngine] 发送打断指令失败: {e}")
            asyncio.run_coroutine_threadsafe(_send_interrupt_cmd(), self.ws_loop)

        # 3. 将全局状态重置为倾听 (listening)
        self.signal_state_changed.emit("listening")

    def handle_kws_hit(self, keyword: str):
        """相容别名：处理 KWS 唤醒命中"""
        self.handle_kws_wakeup(keyword)

    def play_prompt_sound(self, sound_name: str = "zai"):
        """播放应答提示音 (zai / default)"""
        candidates = [
            os.path.join(PROJECT_ROOT, "pyside_app", "assets", f"{sound_name}_female.wav"),
            os.path.join(PROJECT_ROOT, "assets", f"{sound_name}_female.wav"),
            os.path.join(PROJECT_ROOT, "backend", "assets", f"{sound_name}_female.wav"),
            os.path.join(PROJECT_ROOT, "backend", "assets", "zai_female.wav"),
        ]
        wav_path = next((p for p in candidates if os.path.exists(p)), None)

        if wav_path:
            self.audio_player.play_wav_file(wav_path)
        else:
            logger.warning("[BotEngine] 提示音文件未找到")

    def is_in_call(self) -> bool:
        """返回当前是否处于语音通话状态"""
        return self.in_call

    def close(self):
        """窗口关闭时的资源回收与安全切断"""
        self.stop_voice_call()
        if self.ws_connection and self.ws_loop and self.ws_loop.is_running():
            asyncio.run_coroutine_threadsafe(self.ws_connection.close(), self.ws_loop)

    @Slot()
    def _reset_idle_timer(self):
        """重置/刷新无语音输入自动挂断定时器 (读取 session_idle_timeout_sec)"""
        if not self.in_call:
            self.idle_timer.stop()
            return

        global_cfg = load_app_config()
        timeout_sec = int(global_cfg.get("session_idle_timeout_sec", 60))
        if timeout_sec > 0:
            self.idle_timer.start(timeout_sec * 1000)
        else:
            self.idle_timer.stop()

    @Slot()
    def _stop_idle_timer(self):
        """停止无语音输入自动挂断定时器"""
        self.idle_timer.stop()

    def _on_idle_timeout(self):
        """连续长时间未收到语音输入，触发自动挂断休眠"""
        if self.in_call:
            logger.info("[BotEngine] ⏰ 通话中连续超时未检测到语音输入，自动挂断休眠...")
            self.signal_debug_event.emit("intent", "长时间无语音输入，自动挂断休眠")
            self.stop_voice_call()

    def start_voice_call(self, trigger_source: str = "manual"):
        """开启语音通话（发 wakeup 操控云端 session，管道保持常驻）"""
        if self.in_call:
            return
        self.in_call = True
        self.signal_state_changed.emit("listening")
        logger.info(f"[BotEngine] 🎙️ 开启语音通话 (触发源: {trigger_source})")
        self.signal_reset_idle_timer.emit()

        if self.ws_connection and self.ws_loop and self.ws_loop.is_running():
            async def _send_wakeup():
                try:
                    await self.ws_connection.send(json.dumps({"type": "wakeup", "source": trigger_source}))
                except Exception as e:
                    logger.error(f"[BotEngine] 发送 wakeup 失败: {e}")
            asyncio.run_coroutine_threadsafe(_send_wakeup(), self.ws_loop)

    def stop_voice_call(self):
        """挂断语音通话（发 sleep 结束云端会话，管道保持常驻）"""
        self.signal_stop_idle_timer.emit()
        if not self.in_call:
            return
        self.in_call = False
        self.signal_state_changed.emit("idle")
        logger.info("[BotEngine] 🛑 挂断语音通话")

        if self.ws_connection and self.ws_loop and self.ws_loop.is_running():
            async def _send_sleep():
                try:
                    await self.ws_connection.send(json.dumps({"type": "sleep"}))
                except Exception as e:
                    logger.error(f"[BotEngine] 发送 sleep 失败: {e}")
            asyncio.run_coroutine_threadsafe(_send_sleep(), self.ws_loop)

    def handle_pcm_chunk(self, chunk: bytes):
        """流式接收麦克风 16kHz PCM 数据并压入队列上传至 WebSocket"""
        if self.in_call and self.ws_loop and self.ws_loop.is_running() and self.pcm_queue:
            # 当 AI 正在播报语音回复时，抑制麦克风上传，防止扬声器播报声音回灌形成回声与自激啸叫爆音
            if self.audio_player.is_playing():
                self._last_speaking_time = time.time()
                return

            # 余音尾音遮蔽过滤 (80ms)：播报停止瞬间，空气与房间残余回音可能回灌入麦，屏蔽该短时间段 PCM 帧
            if hasattr(self, "_last_speaking_time") and (time.time() - self._last_speaking_time < 0.08):
                return

            self.ws_loop.call_soon_threadsafe(self.pcm_queue.put_nowait, chunk)

    def send_audio_pcm_chunk(self, chunk: bytes):
        """兼容别名：流式接收麦克风 16kHz PCM 数据"""
        self.handle_pcm_chunk(chunk)

    def handle_user_input(self, text: str):
        """处理键盘打字发送的文本指令 (100% 参照原版 App.vue 发起 /chat POST HTTP 文本流式请求)"""
        if not text or not text.strip():
            return

        text = text.strip()
        logger.info(f"[BotEngine] 💬 收到键盘文本消息: {text}")
        self.signal_chat_message.emit("user", text)
        self.signal_state_changed.emit("thinking")

        if self.ws_loop and self.ws_loop.is_running():
            asyncio.run_coroutine_threadsafe(self._stream_text_chat(text), self.ws_loop)

    def _get_backend_url(self) -> str:
        global_cfg = load_app_config()
        return str(global_cfg.get("backend_url", "http://127.0.0.1:10850")).rstrip("/")

    async def _stream_text_chat(self, text: str):
        """HTTP POST /chat 纯文本打字机流式响应 (完全不触发语音播报，0 声音干扰)"""
        import httpx

        base_url = self._get_backend_url()
        chat_url = f"{base_url}/chat"
        payload = {
            "message": text,
            "history": self.chat_history[-10:],
            "system": "你是一个名为“小安”的智能语音助手，请用简洁友好的中文回答问题。"
        }

        self.chat_history.append({"role": "user", "content": text})
        current_bot_msg = ""
        logger.info(f"[BotEngine TextChat] 🚀 准备向后端发起 HTTP POST: {chat_url}")

        try:
            timeout_config = httpx.Timeout(60.0, connect=10.0)
            # trust_env=False: 强制忽略 Windows 系统环境变量中的代理(HTTP_PROXY)，直连本地 127.0.0.1 后端服务
            async with httpx.AsyncClient(trust_env=False, timeout=timeout_config) as client:
                logger.info(f"[BotEngine TextChat] ⏳ 发起请求中...")
                async with client.stream("POST", chat_url, json=payload) as response:
                    logger.info(f"[BotEngine TextChat] 📡 收到 HTTP 响应 Header: Status {response.status_code}")
                    if response.status_code != 200:
                        err_text = f"[Http Error {response.status_code}] 文本服务响应异常"
                        self.signal_chat_message.emit("bot", err_text)
                        self.signal_state_changed.emit("idle")
                        return

                    first_recv = True
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        if first_recv:
                            logger.info(f"[BotEngine TextChat] ⚡ 收到首流数据: {line[:50]}")
                            first_recv = False
                        raw_data = line[5:].strip()
                        if not raw_data:
                            continue
                        try:
                            obj = json.loads(raw_data)
                            obj_type = obj.get("type", "")

                            if obj_type == "delta":
                                content = obj.get("content", "")
                                if content:
                                    current_bot_msg += content
                                    self.signal_chat_message.emit("bot_stream", current_bot_msg)
                            elif obj_type == "debug_event":
                                step = obj.get("step", "llm")
                                content = obj.get("content", obj)
                                self.signal_debug_event.emit(step, content)
                            elif obj_type in ["weather_data", "tool_result"]:
                                data_obj = obj.get("data") or obj.get("result")
                                if data_obj and isinstance(data_obj, dict):
                                    self.signal_weather_updated.emit(data_obj)
                            elif obj_type == "done":
                                break
                            elif obj_type == "error":
                                err_msg = obj.get("message", "未知错误")
                                current_bot_msg += f"\n[Backend Error] {err_msg}"
                                self.signal_chat_message.emit("bot", current_bot_msg)
                                break
                        except Exception:
                            continue

            if current_bot_msg:
                self.signal_chat_message.emit("bot", current_bot_msg)
                self.chat_history.append({"role": "assistant", "content": current_bot_msg})
        except httpx.TimeoutException:
            logger.warning("[BotEngine TextChat] 文本服务请求响应超时")
            err_msg = "[请求超时] 大模型或工具调用响应超时，请重试。"
            self.signal_chat_message.emit("bot", err_msg)
        except Exception as e:
            logger.error(f"[BotEngine TextChat] 网络或系统异常: {e}", exc_info=True)
            err_msg = f"[请求失败] 无法连接到文本服务: {e}"
            self.signal_chat_message.emit("bot", err_msg)
        finally:
            self.signal_state_changed.emit("idle")

    async def _start_persistent_ws(self):
        base_http = self._get_backend_url()
        ws_url = base_http.replace("http://", "ws://").replace("https://", "wss://") + "/voice_ws"
        retry_delay = 1.0

        while True:
            try:
                self.pcm_queue = asyncio.Queue()
                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=10) as ws:
                    self.ws_connection = ws
                    retry_delay = 1.0  # 连接成功后重置退避延迟
                    logger.info(f"[WS] 🚀 成功建立长连接管道: {ws_url}")
                    self.signal_backend_status.emit(True)

                    send_task = asyncio.create_task(self._ws_send_loop())
                    recv_task = asyncio.create_task(self._ws_recv_loop())

                    await asyncio.gather(send_task, recv_task)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[WS] ⚠️ 长连接断开/连不上 ({e})，{retry_delay:.1f} 秒后重试...")
            finally:
                self.ws_connection = None
                self.signal_backend_status.emit(False)
                if self.in_call:
                    logger.info("[WS] ⚠️ WebSocket 管道异常切断，自动优雅重置语音通话状态为休眠 (idle)")
                    self.in_call = False
                    self.signal_state_changed.emit("idle")
                    self.signal_stop_idle_timer.emit()
                    self.audio_player.stop()
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 1.5, 10.0)

    async def _ws_send_loop(self):
        """麦克风 PCM 字节流打包上传循环 (仅在 in_call 为 True 时上发)"""
        try:
            while self.ws_connection:
                chunk = await self.pcm_queue.get()
                if chunk and self.ws_connection and self.in_call:
                    # 按照通信协议加上 0x00 前缀标识位
                    packet = b"\x00" + chunk
                    await self.ws_connection.send(packet)
                self.pcm_queue.task_done()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"[WS-Send] 发送循环退出: {e}")

    async def _ws_recv_loop(self):
        """下行 WebSocket 消息接收循环 (100% 对齐 App.vue enqueueAudio 的物理解包逻辑)"""
        current_user_msg = ""
        current_bot_msg = ""

        try:
            async for msg in self.ws_connection:
                if isinstance(msg, bytes):
                    # WebSocket 下行协议: 首字节 0x00 为音频流类型前缀标识
                    if len(msg) > 0 and msg[0] == 0x00:
                        pcm_payload = msg[1:]
                    else:
                        pcm_payload = msg

                    # 强制保持 16-bit int16 (2 字节/采样点) 偶数对齐，丢弃奇数零头字节
                    if len(pcm_payload) % 2 != 0:
                        pcm_payload = pcm_payload[:-1]

                    if len(pcm_payload) > 0:
                        self.audio_player.play_pcm_chunk(pcm_payload)

                elif isinstance(msg, str):
                    try:
                        data = json.loads(msg)
                    except Exception:
                        continue

                    msg_type = data.get("type", "")

                    # 1. ASR 用户说话识别字幕 (覆盖式更新流式中间态与最终态)
                    if msg_type in ["input_transcript", "user_text", "stt_delta", "asr_result", "user_transcript", "speech_started"]:
                        self.signal_reset_idle_timer.emit()
                        if msg_type == "speech_started":
                            current_user_msg = ""
                        else:
                            text = data.get("data", "") or data.get("text", "") or data.get("delta", "")
                            is_final = data.get("is_final", None)
                            if is_final is None:
                                is_final = True if msg_type in ["user_text", "user_transcript"] else False

                            if text:
                                if not is_final:
                                    # 中间态: ASR 纠错覆盖更新 (绝对不能 += 拼接，防止字符串重复翻倍)
                                    current_user_msg = text
                                    self.signal_chat_message.emit("user_stream", current_user_msg)
                                    self.signal_debug_event.emit("stt", current_user_msg)
                                else:
                                    # 最终态: 确定用户发言并定帧
                                    final_text = text if text else current_user_msg
                                    if final_text:
                                        self.signal_chat_message.emit("user", final_text)
                                        self.signal_debug_event.emit("stt", final_text)
                                    current_user_msg = ""

                    # 2. LLM / TTS 大模型回复字幕 (打字机增量 & 最终)
                    elif msg_type in ["output_transcript", "llm_text", "llm_delta", "text_delta", "weather_summary"]:
                        delta = data.get("data", "") or data.get("text", "") or data.get("delta", "")
                        is_final = data.get("is_final", False)
                        if delta:
                            if msg_type in ["output_transcript", "weather_summary"]:
                                current_bot_msg = delta
                            else:
                                current_bot_msg += delta
                            self.signal_chat_message.emit("bot_stream", current_bot_msg)
                            self.signal_debug_event.emit("tts", delta)

                        if is_final and current_bot_msg:
                            self.signal_chat_message.emit("bot", current_bot_msg)
                            current_bot_msg = ""

                    elif msg_type in ["output_transcript_done", "llm_final", "text_done", "weather_summary_complete"]:
                        text = data.get("data", "") or data.get("text", "") or current_bot_msg
                        # 仅当 current_bot_msg 尚未结算时才发送，防止 output_transcript(is_final=True) 与 output_transcript_done 重复发送
                        if text and current_bot_msg:
                            self.signal_chat_message.emit("bot", text)
                            self.signal_debug_event.emit("tts", text)
                        current_bot_msg = ""

                    # 3. 工具调用与控制事件 (纯粹转发给 Debug 控制台)
                    elif msg_type == "tool_call":
                        self.signal_debug_event.emit("tool_call", data)
                    elif msg_type == "tool_result":
                        self.signal_debug_event.emit("tool_result", data)
                        if "result" in data and isinstance(data["result"], dict):
                            self.signal_weather_updated.emit(data["result"])
                    elif msg_type == "control":
                        self.signal_debug_event.emit("control", data)
                    elif msg_type == "intent":
                        self.signal_debug_event.emit("intent", data.get("content", ""))

                    elif msg_type == "debug_event":
                        step = data.get("step", "system")
                        content = data.get("content", data)
                        logger.debug(f"[BotEngine Debug-Recv] step={step}")
                        self.signal_debug_event.emit(step, content)

                    # 4. 会话与播报状态
                    elif msg_type == "hangup":
                        text = data.get("text", "再见")
                        logger.info(f"[BotEngine] 🛑 收到后端 hangup 挂断指令: {text}")
                        self.in_call = False
                        self.signal_debug_event.emit("intent", f"会话挂断: {text}")
                        self.signal_state_changed.emit("idle")

                    elif msg_type == "state_change":
                        new_state = data.get("state", "idle")
                        if new_state == "idle":
                            self.in_call = False
                        # 核心保证：若后端推送到期/完成(listening/idle)，但本地音频正在播报中，延后切换，直到播报完毕或被打断
                        if new_state in ["listening", "idle"] and self.audio_player.is_playing():
                            logger.info(f"[BotEngine] 收到后端状态 '{new_state}'，但音频仍在播放中，保持 'speaking' 状态...")
                        else:
                            self.signal_state_changed.emit(new_state)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"[WS-Recv] 接收循环退出: {e}")
        finally:
            logger.info("[WS-Recv] 后端 WebSocket 连接正常切断")

    def _on_audio_state_changed(self, state: str):
        """音频播放器的播报状态更新 (彻底播放完毕或被打断)"""
        logger.info(f"[BotEngine] AudioPlayer 状态变化通知: {state}")
        target_state = "speaking" if state == "speaking" else ("listening" if self.in_call else "idle")
        self.signal_state_changed.emit(target_state)

        if target_state == "listening":
            self.signal_reset_idle_timer.emit()
        elif target_state == "speaking":
            self.signal_stop_idle_timer.emit()

        # 向上游后端反向同步当前真正的物理声卡播放状态，供全网大屏同步更新
        if self.ws_connection and self.ws_loop and self.ws_loop.is_running():
            async def send_state_sync():
                try:
                    await self.ws_connection.send(json.dumps({
                        "type": "playback_state",
                        "state": target_state
                    }))
                except Exception as e:
                    logger.warning(f"[BotEngine] 向后端同步播报状态失败: {e}")
            asyncio.run_coroutine_threadsafe(send_state_sync(), self.ws_loop)
