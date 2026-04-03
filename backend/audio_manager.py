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

        # Subscribers: each gets a copy of recorded audio frames
        self._subscribers: list[asyncio.Queue] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Playback
        self._playback_queue: queue.Queue[Optional[bytes]] = queue.Queue()
        self._playback_buffer = b""  # leftover bytes from previous chunk

        # Streams
        self._input_stream: Optional[sd.InputStream] = None
        self._output_stream: Optional[sd.OutputStream] = None
        self._running = False

    def subscribe(self) -> asyncio.Queue:
        """
        Register a new audio consumer (e.g. KWS or Omni feeder).
        Returns an asyncio.Queue that will receive PCM16 bytes chunks.
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Remove a subscriber."""
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    # ────────────────────────── Recording ──────────────────────────

    def _input_callback(self, indata: np.ndarray, frames: int, time_info, status):
        """
        Called by sounddevice InputStream on each audio block.
        indata shape: (frames, channels), dtype int16.
        """
        if status:
            print(f"[AudioManager] Input status: {status}")

        # Convert to raw bytes
        pcm_bytes = indata.tobytes()

        # Broadcast to all subscribers (non-blocking)
        for q in self._subscribers:
            try:
                q.put_nowait(pcm_bytes)
            except asyncio.QueueFull:
                # Drop oldest frame to prevent memory buildup
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(pcm_bytes)
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

        while len(data) < needed_bytes:
            try:
                chunk = self._playback_queue.get_nowait()
                if chunk is None:
                    # Sentinel: stop signal, fill rest with silence
                    break
                data += chunk
            except queue.Empty:
                break

        if len(data) >= needed_bytes:
            # We have enough data
            self._playback_buffer = data[needed_bytes:]
            audio_data = data[:needed_bytes]
        else:
            # Not enough data, pad with silence
            self._playback_buffer = b""
            audio_data = data + b"\x00" * (needed_bytes - len(data))

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

        self._subscribers.clear()
        self.stop_playback()
        print("[AudioManager] Stopped.")

    @property
    def is_running(self) -> bool:
        return self._running
