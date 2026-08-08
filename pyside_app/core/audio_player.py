import os
import sys
import wave
import queue
import threading
import numpy as np
from loguru import logger
from PySide6.QtCore import QObject, Signal, QTimer

try:
    import sounddevice as sd
except ImportError:
    sd = None


class StreamAudioPlayer:
    """
    极清高保真无缝 PCM 音频流播放引擎 (使用 int16 内存直通回调与残余 Byte 缓存，彻底清除噪音杂音与断音)
    """
    def __init__(self, sample_rate: int = 24000, aec_processor=None):
        self.sample_rate = sample_rate
        self.audio_queue = queue.Queue()
        self.pcm_buffer = bytearray()
        self.stream = None
        self.is_running = False
        self._lock = threading.Lock()
        # AEC 处理器引用（可选，延迟注入）
        self._aec_processor = aec_processor

    def start(self):
        with self._lock:
            if self.stream is not None:
                return

            if not sd:
                logger.warning("[StreamAudioPlayer] sounddevice 不可用")
                return

            self.pcm_buffer.clear()

            def audio_callback(outdata, frames, time_info, status):
                needed_bytes = frames * 2  # 16-bit Mono = 2 bytes per sample

                # 1. 尝试将队列中的全部待播放 PCM 压入本地 buffer
                while True:
                    try:
                        chunk = self.audio_queue.get_nowait()
                        if chunk:
                            self.pcm_buffer.extend(chunk)
                    except queue.Empty:
                        break

                # 2. 如果 buffer 中的字节数满足 needed_bytes
                if len(self.pcm_buffer) >= needed_bytes:
                    out_bytes = bytes(self.pcm_buffer[:needed_bytes])
                    del self.pcm_buffer[:needed_bytes]  # 保留残余字节，绝对不丢弃！
                else:
                    # 缓冲区数据不足 needed_bytes，取走全部现有数据并用 zero padding (静音) 补齐
                    out_bytes = bytes(self.pcm_buffer) + b"\x00" * (needed_bytes - len(self.pcm_buffer))
                    self.pcm_buffer.clear()

                pcm_array = np.frombuffer(out_bytes, dtype=np.int16)
                outdata[:] = pcm_array.reshape(-1, 1)

                # AEC Far-end 推送: 将输出给声卡的参考音轨同步推入 AEC 处理器
                # 只在非静音帧推送，避免全零静音帧占用 AEC far_queue
                if self._aec_processor is not None and pcm_array.any():
                    self._aec_processor.push_far_end(out_bytes)

            try:
                self.stream = sd.OutputStream(
                    samplerate=self.sample_rate,
                    channels=1,
                    dtype="int16",
                    callback=audio_callback,
                    blocksize=480
                )
                self.stream.start()
                self.is_running = True
                logger.info(f"[StreamAudioPlayer] 🚀 纯净 int16 高保真音频引擎开启 (采样率: {self.sample_rate}Hz, 硬件缓冲: 20ms)")
            except Exception as e:
                logger.error(f"[StreamAudioPlayer] 启动 OutputStream 异常: {e}")
                self.stream = None

    def write_pcm(self, pcm_bytes: bytes):
        if not pcm_bytes:
            return
        # 强制保持 16-bit int16 采样点的 2 字节偶数对齐，防止高低位错位产生嘈杂噪音
        if len(pcm_bytes) % 2 != 0:
            pcm_bytes = pcm_bytes[:-1]
        if not pcm_bytes:
            return
        if not self.is_running:
            self.start()
        self.audio_queue.put(pcm_bytes)

    def set_aec_processor(self, aec_processor) -> None:
        """延迟注入 AECProcessor，允许在 start() 后进行绑定。"""
        self._aec_processor = aec_processor

    def is_playing(self) -> bool:
        """判断当前是否有音频正处于播放或排队状态"""
        return self.is_running and (len(self.pcm_buffer) > 0 or not self.audio_queue.empty())

    def stop(self):
        with self._lock:
            if self.stream is not None:
                try:
                    self.stream.stop()
                    self.stream.close()
                except Exception:
                    pass
                self.stream = None
            self.is_running = False
            self.pcm_buffer.clear()
            while not self.audio_queue.empty():
                try:
                    self.audio_queue.get_nowait()
                except queue.Empty:
                    break
            logger.info("[StreamAudioPlayer] 🛑 停止流式音频输出引擎")


class AudioPlayer(QObject):
    """
    全功能音频播放适配器 (继承 QObject，支持状态 Signal、内存高能缓存与极速提示音播放)
    """
    signal_state_changed = Signal(str)
    signal_speaker_status = Signal(bool)  # 扬声器输出状态 (True: PLAY / False: ON)

    _stream_player = StreamAudioPlayer(sample_rate=24000)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sound_cache = {}
        # 启动时预热声卡输出设备，消灭动态建立 OutputStream 的 300ms 驱动延迟
        self._stream_player.start()
        # 预加载常驻音效资产并精准剔除头部无音 Padding
        self._preload_common_sounds()

        # 实时检测播放状态 (50ms 轮询)，精准发出 speaking / idle 转换信号
        self._is_last_playing = False
        self._playing_timer = QTimer(self)
        self._playing_timer.setInterval(50)
        self._playing_timer.timeout.connect(self._check_playing_status)
        self._playing_timer.start()

    def _check_playing_status(self):
        currently_playing = self.is_playing()
        if currently_playing != self._is_last_playing:
            self._is_last_playing = currently_playing
            status_str = "speaking" if currently_playing else "idle"
            logger.debug(f"[AudioPlayer] 播放状态改变: {status_str}")
            self.signal_state_changed.emit(status_str)
            self.signal_speaker_status.emit(currently_playing)

    def _preload_common_sounds(self):
        """预先将常用提示音直接读入 RAM，剪除头部无音 Padding 消除延迟"""
        asset_dirs = [
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backend", "assets")),
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets")),
        ]
        for ad in asset_dirs:
            if not os.path.exists(ad):
                continue
            for fn in ["zai_female.wav", "zai_male.wav", "exit_female.wav", "exit_male.wav"]:
                fp = os.path.realpath(os.path.join(ad, fn))
                if os.path.exists(fp) and fp not in self.sound_cache:
                    try:
                        with wave.open(fp, "rb") as wf:
                            if wf.getnchannels() == 1 and wf.getsampwidth() == 2:
                                raw_bytes = wf.readframes(wf.getnframes())
                                arr = np.frombuffer(raw_bytes, dtype=np.int16)
                                # 自动物理切除音频文件头部的空白/静音帧 (振幅极小样本点)，消灭 80ms~100ms 无音播放空窗
                                non_zero = np.where(np.abs(arr) > 400)[0]
                                if len(non_zero) > 0:
                                    start_idx = max(0, non_zero[0] - int(wf.getframerate() * 0.002))
                                    arr = arr[start_idx:]
                                self.sound_cache[fp] = arr.tobytes()
                    except Exception as e:
                        logger.debug(f"[AudioPlayer] 预加载提示音失败 {fp}: {e}")

    def is_playing(self) -> bool:
        return self._stream_player.is_playing()

    def play_pcm_chunk(self, pcm_bytes: bytes):
        self._stream_player.write_pcm(pcm_bytes)

    def play_wav_file(self, wav_path: str) -> bool:
        if not wav_path:
            return False

        norm_path = os.path.realpath(wav_path)

        # 1. 优先命中 RAM 零延迟内存缓存 (延迟 < 1ms)
        if norm_path in self.sound_cache:
            self.play_pcm_chunk(self.sound_cache[norm_path])
            logger.info(f"[AudioPlayer] 🚀 [内存直通 0 延迟] 播放提示音: {os.path.basename(wav_path)}")
            return True

        if not os.path.exists(wav_path):
            logger.warning(f"[AudioPlayer] 提示音文件不存在: {wav_path}")
            return False

        try:
            with wave.open(wav_path, "rb") as wf:
                sample_rate = wf.getframerate()
                n_channels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                raw_bytes = wf.readframes(wf.getnframes())

                if n_channels == 1 and sampwidth == 2:
                    arr = np.frombuffer(raw_bytes, dtype=np.int16)
                    non_zero = np.where(np.abs(arr) > 400)[0]
                    if len(non_zero) > 0:
                        start_idx = max(0, non_zero[0] - int(sample_rate * 0.002))
                        arr = arr[start_idx:]
                    pcm_clean = arr.tobytes()
                    self.sound_cache[norm_path] = pcm_clean
                    self.play_pcm_chunk(pcm_clean)
                    logger.info(f"[AudioPlayer] 🔊 无缝播放提示音: {os.path.basename(wav_path)}")
                    return True

                if not sd:
                    return False

                audio_data = np.frombuffer(frames, dtype=np.int16)
                if n_channels > 1:
                    audio_data = audio_data.reshape(-1, n_channels)

                sd.play(audio_data, samplerate=sample_rate)
                logger.info(f"[AudioPlayer] 🔊 播放提示音: {os.path.basename(wav_path)}")
                return True
        except Exception as e:
            logger.error(f"[AudioPlayer] 播放 WAV 异常: {e}")
            return False

    def stop(self):
        if sd:
            try:
                sd.stop()
            except Exception:
                pass
        self._stream_player.stop()
        self._check_playing_status()
