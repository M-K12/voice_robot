"""
audio_aec.py — SpeexDSP 回声消除处理器 (AECProcessor)

【途径 B 架构】
  播放器 24kHz → AEC 内部降采样 16kHz → 作为 Far-end 参考音轨
  麦克风 16kHz → AEC 处理 → 消除回声后的纯净 PCM

支持功能:
  - 扬声器播报中 KWS 唤醒词仍能正常触发 (Barge-in)
  - speexdsp 未安装时自动切换 Bypass 旁路模式，优雅降级
  - Far-end 环形缓冲 maxlen=50，防止无限增长
  - 空队列时旁路透传，消除初始/暂停时的帧阻塞
"""

from __future__ import annotations

from collections import deque
from typing import Optional

import numpy as np
from loguru import logger

try:
    from speexdsp import EchoCanceller
    _SPEEXDSP_AVAILABLE = True
except ImportError:
    EchoCanceller = None
    _SPEEXDSP_AVAILABLE = False
    logger.warning(
        "[AECProcessor] speexdsp 未安装 → AEC 以 Bypass 旁路模式运行（无回声消除）。\n"
        "  Linux 安装: sudo apt-get install -y libspeexdsp-dev swig && uv add speexdsp"
    )


class AECProcessor:
    """
    SpeexDSP 回声消除处理器。

    使用方式:
        # 在 main.py 创建后注入至播放器与 KWS 线程
        aec = AECProcessor(filter_length=2048)

        # 播放器回调线程调用 (Far-end)
        aec.push_far_end(out_bytes_24k)

        # 麦克风回调线程调用 (Near-end)
        clean_bytes = aec.process_near_end(mic_bytes_16k)
    """

    # ──────────────────────────────────────────────
    # 固定常量
    # ──────────────────────────────────────────────
    AEC_FRAME_SIZE = 160          # 10ms @ 16kHz (SpeexDSP 标准处理单元)
    FAR_SAMPLE_RATE = 24000       # 播放器输出采样率
    NEAR_SAMPLE_RATE = 16000      # 麦克风 / AEC 工作采样率
    FAR_QUEUE_MAXLEN = 50         # 最大缓存 50 帧 = 500ms，超出自动丢弃最老帧

    def __init__(self, filter_length: int = 2048):
        """
        Args:
            filter_length: AEC 回声尾长 (samples @ 16kHz)。
                256  =  16ms  耳麦一体式耳机 (几乎无空气传播回声)
                1024 =  64ms  笔记本内置音箱+内置麦
                2048 = 128ms  外置音箱+桌面麦克风 (推荐默认)
                4096 = 256ms  大音量外放 / 大房间混响环境
        """
        self.filter_length = filter_length
        self._aec: Optional[object] = None

        # Far-end 参考信号环形缓冲区（按 160-sample AEC 帧存储）
        # deque 的 append/popleft 在 CPython 中是原子操作，无需额外锁
        self._far_queue: deque = deque(maxlen=self.FAR_QUEUE_MAXLEN)

        self._bypass = not _SPEEXDSP_AVAILABLE
        self._empty_bypass_count = 0   # 累计旁路帧数（调试用）

        if not self._bypass:
            try:
                self._aec = EchoCanceller.create(
                    self.AEC_FRAME_SIZE,
                    self.filter_length,
                    self.NEAR_SAMPLE_RATE,
                )
                tail_ms = int(filter_length / self.NEAR_SAMPLE_RATE * 1000)
                logger.info(
                    f"[AECProcessor] ✅ SpeexDSP AEC 初始化成功 "
                    f"(frame=10ms, filter={filter_length}samp/{tail_ms}ms, "
                    f"queue_max={self.FAR_QUEUE_MAXLEN}frames/500ms)"
                )
            except Exception as e:
                logger.error(f"[AECProcessor] 初始化失败: {e}，切换至 Bypass 旁路模式")
                self._bypass = True

    # ──────────────────────────────────────────────
    # 播放器侧：Far-end 参考信号推送
    # ──────────────────────────────────────────────
    def push_far_end(self, pcm_24k_bytes: bytes) -> None:
        """
        由播放器 OutputStream audio_callback 调用。
        接收 24kHz int16 Mono PCM，内部降采样至 16kHz，
        按 160-sample 帧切分后压入环形缓冲区。

        Args:
            pcm_24k_bytes: 播放器输出的 24kHz int16 PCM 字节。
        """
        if self._bypass or not pcm_24k_bytes:
            return

        arr_24k = np.frombuffer(pcm_24k_bytes, dtype=np.int16)
        if len(arr_24k) == 0:
            return

        # ── 24kHz → 16kHz 线性插值降采样 ──────────
        # 比例: 16000/24000 = 2/3
        # 480 samples@24kHz → 320 samples@16kHz (每 20ms 回调)
        n_in = len(arr_24k)
        n_out = max(1, round(n_in * self.NEAR_SAMPLE_RATE / self.FAR_SAMPLE_RATE))
        indices = np.linspace(0, n_in - 1, n_out)
        arr_16k = np.interp(indices, np.arange(n_in), arr_24k).astype(np.int16)

        # ── 按 AEC_FRAME_SIZE 切帧并入队 ───────────
        offset = 0
        while offset + self.AEC_FRAME_SIZE <= len(arr_16k):
            frame_bytes = arr_16k[offset: offset + self.AEC_FRAME_SIZE].tobytes()
            self._far_queue.append(frame_bytes)
            offset += self.AEC_FRAME_SIZE

    # ──────────────────────────────────────────────
    # 麦克风侧：近端信号 AEC 处理
    # ──────────────────────────────────────────────
    def process_near_end(self, pcm_16k_bytes: bytes) -> bytes:
        """
        由麦克风 InputStream audio_callback 调用。
        将 16kHz int16 Mono 麦克风 PCM 经 AEC 滤波，
        返回消除回声后的纯净 PCM 字节（与输入等长）。

        如 far_queue 为空（启动初期/播放器暂停），直接旁路透传，
        确保 KWS 和 WebSocket 上传不阻塞。

        Args:
            pcm_16k_bytes: 麦克风 16kHz int16 PCM 字节。

        Returns:
            bytes: 消除回声后的 16kHz int16 PCM（与输入字节数相同）。
        """
        if self._bypass or not pcm_16k_bytes:
            return pcm_16k_bytes

        arr_near = np.frombuffer(pcm_16k_bytes, dtype=np.int16)
        output_frames: list = []
        offset = 0

        while offset + self.AEC_FRAME_SIZE <= len(arr_near):
            near_frame = arr_near[offset: offset + self.AEC_FRAME_SIZE].tobytes()

            if self._far_queue:
                far_frame = self._far_queue.popleft()
                try:
                    clean_frame = self._aec.process(near_frame, far_frame)
                    output_frames.append(clean_frame)
                except Exception as e:
                    logger.debug(f"[AECProcessor] process() 异常: {e}，旁路本帧")
                    output_frames.append(near_frame)
            else:
                # Far-end 队列为空：旁路透传，等待播放器补充参考帧
                output_frames.append(near_frame)
                self._empty_bypass_count += 1
                if self._empty_bypass_count % 500 == 1:
                    logger.debug(
                        f"[AECProcessor] far_queue 空，旁路透传 "
                        f"(累计 {self._empty_bypass_count} 帧)"
                    )

            offset += self.AEC_FRAME_SIZE

        if output_frames:
            return b"".join(output_frames)
        return pcm_16k_bytes

    @property
    def is_active(self) -> bool:
        """是否处于真实 AEC 模式（非 Bypass）"""
        return not self._bypass

    def __repr__(self) -> str:
        status = "AEC-Active" if self.is_active else "Bypass"
        return f"<AECProcessor {status} filter={self.filter_length}>"
