import os
from pathlib import Path
from dotenv import load_dotenv
import dashscope
from dashscope.audio.tts_v2 import SpeechSynthesizer, AudioFormat

load_dotenv()
dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")

COSY_CASES = [
    {
        "model": "cosyvoice-v1",
        "voice": "longxiaochun",
        "gender": "female",
        "desc": "CosyVoice v1 女声 (小春)"
    },
    {
        "model": "cosyvoice-v1",
        "voice": "longxiaochuan",
        "gender": "male",
        "desc": "CosyVoice v1 男声 (小川)"
    },
    {
        "model": "cosyvoice-v2",
        "voice": "longxiaochun_v2",
        "gender": "female",
        "desc": "CosyVoice v2 女声 (小春v2)"
    },
    {
        "model": "cosyvoice-v2",
        "voice": "longxiaochuan_v2",
        "gender": "male",
        "desc": "CosyVoice v2 男声 (小川v2)"
    }
]

def main():
    output_dir = Path(__file__).parent / "backend" / "assets" / "cosy_test"
    output_dir.mkdir(parents=True, exist_ok=True)

    text = "小安退下了"
    print(f"=== 测试 CosyVoice 引擎生成 '{text}' ===")

    for case in COSY_CASES:
        model = case["model"]
        voice = case["voice"]
        gender = case["gender"]
        desc = case["desc"]
        
        out_file = output_dir / f"{gender}_{model}_{voice}.wav"
        print(f"正在生成 [{desc}]...")
        
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
                print(f"  └─ 成功: {out_file.name}")
            else:
                print(f"  └─ 失败: 空数据")
        except Exception as e:
            print(f"  └─ 失败: {e}")

if __name__ == "__main__":
    main()
