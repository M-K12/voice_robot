import os
from pathlib import Path
from dotenv import load_dotenv
import dashscope
from dashscope.audio.tts_v2 import SpeechSynthesizer, AudioFormat

load_dotenv()
dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")

VOICE_LIST = [
    # CosyVoice v1
    {"model": "cosyvoice-v1", "voice": "longxiaochun", "gender": "female", "label": "CosyVoice-v1-小春(女)"},
    {"model": "cosyvoice-v1", "voice": "longshu", "gender": "male", "label": "CosyVoice-v1-龙书(男)"},
    {"model": "cosyvoice-v1", "voice": "longfei", "gender": "male", "label": "CosyVoice-v1-龙飞(男)"},
    
    # CosyVoice v2
    {"model": "cosyvoice-v2", "voice": "longxiaochun_v2", "gender": "female", "label": "CosyVoice-v2-小春v2(女)"},
    
    # Qwen-TTS 官方通用模型 (qwen-tts-flash / qwen-audio-3.0-tts-flash)
    {"model": "qwen-audio-3.0-tts-flash", "voice": "longanhuan_v3.6", "gender": "female", "label": "QwenFlash-欢欢(女)"},
    {"model": "qwen-audio-3.0-tts-flash", "voice": "longanyang", "gender": "male", "label": "QwenFlash-昂昂(男)"},
]

def main():
    output_dir = Path(__file__).parent / "backend" / "assets" / "model_samples"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("=== 开始批量测试各种模型音色 ===")

    for item in VOICE_LIST:
        model = item["model"]
        voice = item["voice"]
        label = item["label"]
        gender = item["gender"]
        
        print(f"\n测试音色: {label} (模型: {model}, 音色: {voice})")
        
        for task, text in [("zai", "在！"), ("exit", "小安退下了")]:
            out_name = f"{task}_{gender}_{voice}.wav"
            out_file = output_dir / out_name
            try:
                synthesizer = SpeechSynthesizer(
                    model=model,
                    voice=voice,
                    format=AudioFormat.WAV_24000HZ_MONO_16BIT,
                    speech_rate=1.0,
                    volume=75
                )
                data = synthesizer.call(text)
                if data:
                    with open(out_file, "wb") as f:
                        f.write(data)
                    print(f"  └─ 已成功保存 [{task}]: {out_name}")
                else:
                    print(f"  └─ 失败 [{task}]: 空数据")
            except Exception as e:
                print(f"  └─ 失败 [{task}]: {e}")

if __name__ == "__main__":
    main()
