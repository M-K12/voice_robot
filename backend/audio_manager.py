"""
AudioManager — 系统级音频录放管理

使用 sounddevice 直接操控系统声卡:
  - 录音线程: InputStream 16kHz/单声道 PCM16 → 广播给所有订阅者的 asyncio.Queue
  - 播放线程: OutputStream 24kHz/单声道 PCM16 ← 从 playback_queue 取帧
"""

from __future__ import annotations

import asyncio
import queue
import threading
import numpy as np
from typing import Optional

try:
    import sounddevice as sd
except ImportError:
    sd = None
    print("[AudioManager] WARNING: sounddevice not installed. Audio will not work.")


class AudioManager:
    """
    System-level audio I/O manager.

    Usage:
        am = AudioManager()
        kws_q = am.subscribe()       # KWS consumer
        omni_q = am.subscribe()      # Omni consumer
        await am.start()
        ...
        am.play_audio(pcm_bytes)     # enqueue for playback
        am.stop_playback()           # flush playback queue (interrupt)
        await am.stop()
    """

    def __init__(
        self,
        input_sample_rate: int = 16000,
        output_sample_rate: int = 24000,
        channels: int = 1,
        input_device: Optional[int] = None,
        output_device: Optional[int] = None,
        input_blocksize: int = 4000,   # ~250ms at 16kHz
        output_blocksize: int = 4800,  # ~200ms at 24kHz
    ):
        self.input_sample_rate = input_sample_rate
        self.output_sample_rate = output_sample_rate
        self.channels = channels
        self.input_device = input_device
        self.output_device = output_device
        self.input_blocksize = input_blocksize
        self.output_blocksize = output_blocksize

        # Subscribers split into two categories:
        #   _always_real: always get real mic data (e.g. KWS wake word detection)
        #   _half_duplex: get silence during playback (e.g. Omni conversation)
        self._always_real: list[asyncio.Queue] = []
        self._half_duplex: list[asyncio.Queue] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Playback
        self._playback_queue: queue.Queue[Optional[bytes]] = queue.Queue()
        self._playback_buffer = b""  # leftover bytes from previous chunk

        # Half-duplex echo control
        self._is_speaking = False  # True when outputting non-silence audio

        # Streams
        self._input_stream: Optional[sd.InputStream] = None
        self._output_stream: Optional[sd.OutputStream] = None
        self._running = False

    def subscribe(self, always_real: bool = False) -> asyncio.Queue:
        """
        Register a new audio consumer.

        Args:
            always_real: If True, this subscriber always receives real mic data
                        even during AI playback (for KWS wake word detection).
                        If False, receives silence during playback (half-duplex).
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        if always_real:
            self._always_real.append(q)
        else:
            self._half_duplex.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Remove a subscriber from either list."""
        try:
            self._half_duplex.remove(q)
        except ValueError:
            try:
                self._always_real.remove(q)
            except ValueError:
                pass

    # ────────────────────────── Recording ──────────────────────────

    @property
    def is_speaking(self) -> bool:
        """Whether the system is currently playing back audio (half-duplex control)."""
        return self._is_speaking

    def _input_callback(self, indata: np.ndarray, frames: int, time_info, status):
        """
        Called by sounddevice InputStream on each audio block.
        indata shape: (frames, channels), dtype int16.

        Half-duplex strategy:
          - always_real subscribers (KWS): ALWAYS get real mic data
          - half_duplex subscribers (Omni): get silence during playback
        This allows KWS to detect wake words even while AI is speaking.
        """
        if status:
            print(f"[AudioManager] Input status: {status}")

        real_pcm = indata.tobytes()
        silence_pcm = b"\x00" * (frames * self.channels * 2) if self._is_speaking else None

        # Always-real subscribers (KWS): always get real mic data
        for q in self._always_real:
            self._push_to_queue(q, real_pcm)

        # Half-duplex subscribers (Omni): silence during playback
        data = silence_pcm if silence_pcm else real_pcm
        for q in self._half_duplex:
            self._push_to_queue(q, data)

    @staticmethod
    def _push_to_queue(q: asyncio.Queue, data: bytes) -> None:
        """Non-blocking push with drop-oldest on overflow."""
        try:
            q.put_nowait(data)
        except asyncio.QueueFull:
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                pass

    # ────────────────────────── Playback ──────────────────────────

    def _output_callback(self, outdata: np.ndarray, frames: int, time_info, status):
        """
        Called by sounddevice OutputStream requesting audio data.
        We need to fill outdata with exactly `frames` samples.
        """
        if status:
            print(f"[AudioManager] Output status: {status}")

        needed_bytes = frames * self.channels * 2  # int16 = 2 bytes per sample

        # Fill from leftover buffer first
        data = self._playback_buffer
        has_real_audio = len(data) > 0  # track if we got real data

        while len(data) < needed_bytes:
            try:
                chunk = self._playback_queue.get_nowait()
                if chunk is None:
                    break
                has_real_audio = True
                data += chunk
            except queue.Empty:
                break

        if len(data) >= needed_bytes:
            self._playback_buffer = data[needed_bytes:]
            audio_data = data[:needed_bytes]
        else:
            self._playback_buffer = b""
            audio_data = data + b"\x00" * (needed_bytes - len(data))

        # Half-duplex: update speaking state based on whether we have real audio
        self._is_speaking = has_real_audio or len(self._playback_buffer) > 0

        outdata[:] = np.frombuffer(audio_data, dtype=np.int16).reshape(-1, self.channels)

    def play_audio(self, pcm_bytes: bytes) -> None:
        """
        Enqueue PCM16 audio data for playback through system speaker.
        Expected format: 24kHz mono int16.
        """
        if pcm_bytes:
            self._playback_queue.put(pcm_bytes)

    def stop_playback(self) -> None:
        """
        Flush the playback queue (used when AI is interrupted).
        """
        self._playback_buffer = b""
        while True:
            try:
                self._playback_queue.get_nowait()
            except queue.Empty:
                break

    # ────────────────────────── Lifecycle ──────────────────────────

    async def start(self) -> None:
        """Start input (recording) and output (playback) audio streams."""
        if not sd:
            print("[AudioManager] sounddevice not available, skipping audio start.")
            return

        self._loop = asyncio.get_running_loop()
        self._running = True

        # List available devices for debugging
        print("[AudioManager] Available audio devices:")
        print(sd.query_devices())
        print(f"[AudioManager] Default input: {sd.default.device[0]}, Default output: {sd.default.device[1]}")

        # Start input stream (recording)
        try:
            self._input_stream = sd.InputStream(
                samplerate=self.input_sample_rate,
                blocksize=self.input_blocksize,
                device=self.input_device,
                channels=self.channels,
                dtype="int16",
                callback=self._input_callback,
            )
            self._input_stream.start()
            print(f"[AudioManager] Input stream started: {self.input_sample_rate}Hz, blocksize={self.input_blocksize}")
        except Exception as e:
            print(f"[AudioManager] Failed to start input stream: {e}")
            raise

        # Start output stream (playback)
        try:
            self._output_stream = sd.OutputStream(
                samplerate=self.output_sample_rate,
                blocksize=self.output_blocksize,
                device=self.output_device,
                channels=self.channels,
                dtype="int16",
                callback=self._output_callback,
            )
            self._output_stream.start()
            print(f"[AudioManager] Output stream started: {self.output_sample_rate}Hz, blocksize={self.output_blocksize}")
        except Exception as e:
            print(f"[AudioManager] Failed to start output stream: {e}")
            raise

    async def stop(self) -> None:
        """Stop all audio streams and cleanup."""
        self._running = False

        if self._input_stream:
            try:
                self._input_stream.stop()
                self._input_stream.close()
            except Exception:
                pass
            self._input_stream = None

        if self._output_stream:
            try:
                self._output_stream.stop()
                self._output_stream.close()
            except Exception:
                pass
            self._output_stream = None

        self._always_real.clear()
        self._half_duplex.clear()
        self.stop_playback()
        print("[AudioManager] Stopped.")

    @property
    def is_running(self) -> bool:
        return self._running
