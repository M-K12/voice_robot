import os
import dashscope
from dashscope.audio.qwen_tts_realtime import QwenTtsRealtime, QwenTtsRealtimeCallback
from dotenv import load_dotenv
import wave
import time
import threading
from pathlib import Path

# 加载环境变量
load_dotenv()
api_key = os.getenv("DASHSCOPE_API_KEY")

if not api_key:
    print("Error: DASHSCOPE_API_KEY not found in .env")
    exit(1)

dashscope.api_key = api_key

class SimpleTTSCallback(QwenTtsRealtimeCallback):
    def __init__(self):
        self.audio_buffer = bytearray()
        self.done_event = threading.Event()

    def on_open(self, *args, **kwargs):
        print("TTS Connection opened.")

    def on_close(self, *args, **kwargs):
        print("TTS Connection closed.")
        self.done_event.set()

    def on_error(self, message, *args, **kwargs):
        print(f"TTS Error: {message}")
        self.done_event.set()

    def on_event(self, event):
        import base64
        etype = event.get('type')
        if etype == 'response.audio.delta':
            delta = event.get('delta')
            if delta:
                audio_bytes = base64.b64decode(delta)
                self.audio_buffer.extend(audio_bytes)
        elif etype == 'response.done':
            print("TTS Synthesis completed.")
            self.done_event.set()

def generate_audio(text, output_path):
    callback = SimpleTTSCallback()
    tts_client = QwenTtsRealtime(
        model='qwen3-tts-flash-realtime',
        callback=callback
    )
    tts_client.connect()
    tts_client.update_session(voice="Cherry")
    
    print(f"Synthesizing: '{text}'...")
    tts_client.append_text(text)
    tts_client.finish()
    
    # 等待完成
    if not callback.done_event.wait(timeout=10):
        print("Timeout waiting for TTS synthesis.")
    
    tts_client.close()
    
    if len(callback.audio_buffer) > 0:
        # 创建目录
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 保存为 WAV (16-bit PCM, 24kHz, Mono)
        with wave.open(str(output_path), 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(callback.audio_buffer)
        print(f"Saved: {output_path} ({len(callback.audio_buffer)} bytes)")
    else:
        print("No audio data received.")

if __name__ == "__main__":
    out = "../jinxiangscreen2025/public/audio/wozai.wav"
    generate_audio("我在", out)
