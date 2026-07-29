import os
import dashscope
from dashscope.audio.qwen_tts_realtime import QwenTtsRealtime, QwenTtsRealtimeCallback
from dotenv import load_dotenv
import wave
import threading
from pathlib import Path

# 加载环境变量
load_dotenv()
api_key = os.getenv("DASHSCOPE_API_KEY")
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

def generate_audio(text, output_path, voice_name):
    callback = SimpleTTSCallback()
    tts_client = QwenTtsRealtime(
        model='qwen-tts-realtime',
        callback=callback
    )
    tts_client.connect()
    tts_client.update_session(voice=voice_name)
    
    print(f"Synthesizing '{text}' with voice {voice_name}...")
    tts_client.append_text(text)
    tts_client.finish()
    
    if not callback.done_event.wait(timeout=10):
        print("Timeout waiting for TTS synthesis.")
    
    tts_client.close()
    
    if len(callback.audio_buffer) > 0:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # 保存为 24000Hz 16-bit 单声道 WAV 文件 (TTS 模型的标准输出格式)
        with wave.open(str(output_path), 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(callback.audio_buffer)
        print(f"Saved: {output_path}")
        return True
    return False

if __name__ == "__main__":
    if not api_key:
        print("Error: DASHSCOPE_API_KEY is not set.")
        exit(1)
        
    # 前端配置音色 -> 百炼 TTS 实时模型支持的预置音色
    voice_map = {
        "Tina": "Cherry",        # 对应女声
        "Theo Calm": "Ethan"     # 对应男声 (使用 Dylan 作为 TTS 映射音色)
    }
    
    for local_voice, tts_voice in voice_map.items():
        out = f"backend/assets/zai_{local_voice}.wav"
        print(f"\n--- Generating for voice {local_voice} (using TTS voice {tts_voice}) ---")
        generate_audio("在！", out, tts_voice)
    print("\nAll voices synthesized successfully.")
