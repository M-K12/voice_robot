import os
from pathlib import Path
from dotenv import load_dotenv
import dashscope
from dashscope.audio.tts_v2 import SpeechSynthesizer, AudioFormat

load_dotenv()
dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")

TEST_CASES = [
    {
        "name": "CosyVoice v3 (Flash)",
        "model": "cosyvoice-v3-flash",
        "female_voice": "longxiaochun",
        "male_voice": "longyeting"
    },
    {
        "name": "CosyVoice v2",
        "model": "cosyvoice-v2",
        "female_voice": "longxiaochun_v2",
        "male_voice": "longshang_v2"
    },
    {
        "name": "Qwen Audio 3.0 (Flash)",
        "model": "qwen-audio-3.0-tts-flash",
        "female_voice": "longanlingxin",
        "male_voice": "longanlufeng"
    }
]

def main():
    output_dir = Path(__file__).parent / "backend" / "assets" / "test_models"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    text = "小安退下了"
    print(f"=== 测试不同 TTS 模型合成 '{text}' ===")
    
    for case in TEST_CASES:
        model = case["model"]
        print(f"\n--- 测试模型: {case['name']} ({model}) ---")
        
        for gender, voice in [("female", case["female_voice"]), ("male", case["male_voice"])]:
            out_file = output_dir / f"{model}_{gender}_{voice}.wav"
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
                    print(f"  └─ 已成功生成 [{gender} - {voice}]: {out_file.name}")
                else:
                    print(f"  └─ 失败: 未返回数据")
            except Exception as e:
                print(f"  └─ 失败 ({model}/{voice}): {e}")

if __name__ == "__main__":
    main()
