import os
from pathlib import Path
from dotenv import load_dotenv
import dashscope
from dashscope.audio.tts_v2 import SpeechSynthesizer, AudioFormat

load_dotenv()
dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")

MODEL_NAME = "qwen-audio-3.0-tts-plus"

# 测试几种不同的 Prompt 和文本形式，消灭呼唤感/命令感
VARIATIONS = [
    {
        "id": "v1_original_text_context_prompt",
        "text": "小安退下了。",
        "instruction": "角色是贴身助手小安，在向主人躬身汇报'小安退下了'。语气极其轻柔谦逊、平缓平顺，绝无呼唤感，'小安退下了'一口气连贯说出"
    },
    {
        "id": "v2_zhejiu_text",
        "text": "小安这就退下了。",
        "instruction": "助手小安轻柔恭顺地向主人告别，语气平缓自然，一气呵成"
    },
    {
        "id": "v3_xian_text",
        "text": "小安先退下了。",
        "instruction": "助手小安轻柔恭顺地向主人告别，语气平缓自然，一气呵成"
    },
    {
        "id": "v4_gaotui_text",
        "text": "小安告退了。",
        "instruction": "助手小安轻柔恭顺地向主人告别，语气平缓自然"
    }
]

def main():
    output_dir = Path(__file__).parent / "backend" / "assets" / "test_exits"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=== 开始合成多种退出语气对比样本 ===")

    for var in VARIATIONS:
        var_id = var["id"]
        text = var["text"]
        instruction = var["instruction"]

        for gender_key, voice_code in [("female", "longanlingxin"), ("male", "longanlufeng")]:
            filename = f"exit_{gender_key}_{var_id}.wav"
            file_path = output_dir / filename
            
            print(f"正在生成 [{gender_key}] [{var_id}] 文本: '{text}'...")
            try:
                synthesizer = SpeechSynthesizer(
                    model=MODEL_NAME,
                    voice=voice_code,
                    format=AudioFormat.WAV_24000HZ_MONO_16BIT,
                    volume=75,
                    speech_rate=1.0,
                    pitch_rate=0.97,
                    instruction=instruction
                )
                audio_data = synthesizer.call(text)
                if audio_data:
                    with open(file_path, "wb") as f:
                        f.write(audio_data)
                    print(f"  └─ 已保存: {file_path.name}")
            except Exception as e:
                print(f"  └─ 出错: {e}")

if __name__ == "__main__":
    main()
