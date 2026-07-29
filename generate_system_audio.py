import os
from pathlib import Path
from dotenv import load_dotenv
import dashscope
from dashscope.audio.tts_v2 import SpeechSynthesizer, AudioFormat

# 加载 .env 环境变量
load_dotenv()
api_key = os.getenv("DASHSCOPE_API_KEY")
if not api_key:
    print("错误: 未找到 DASHSCOPE_API_KEY 环境变量，请检查 .env 文件。")
    exit(1)

dashscope.api_key = api_key

# 设定模型为 Qwen-Audio-TTS (qwen-audio-3.0-tts-plus)
MODEL_NAME = "qwen-audio-3.0-tts-plus"

VOICES = {
    "female": {
        "name": "longanlingxin",
        "gender": "女声 (longanlingxin)",
        "wake_rate": 1.0,       # 恢复正常语速，吐字欢快
        "wake_pitch": 1.05,     # 微调音高，表现出积极饱满的精神状态
        "close_rate": 1.0,
        "close_pitch": 1.0
    },
    "male": {
        "name": "longanlufeng",
        "gender": "男声 (longanlufeng)",
        "wake_rate": 1.0,       # 恢复正常语速
        "wake_pitch": 1.05,     # 阳光饱满
        "close_rate": 1.0,
        "close_pitch": 1.0
    }
}

TASKS = [
    {
        "type": "wake",
        "text": "在！",               # 带感叹号，富有朝气
        "key": "zai",
        "volume": 75,             # 适中适度的音量
        "instruction": "声音积极主动、热情响应、充满精气神" # 积极有朝气的提示词
    },
    {
        "type": "close",
        "text": "再见",              # 退出“再见”
        "key": "exit",
        "volume": 70,
        "instruction": None
    }
]

def main():
    output_dir = Path(__file__).parent / "backend" / "assets"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"=== 使用 Qwen-Audio-TTS ({MODEL_NAME}) 积极情感生成系统语音 ===")
    
    generated_files = []

    for gender_key, voice_info in VOICES.items():
        voice_code = voice_info["name"]
        gender_desc = voice_info["gender"]
        
        for task in TASKS:
            text = task["text"]
            task_key = task["key"]
            volume = task["volume"]
            speech_rate = voice_info[f"{task['type']}_rate"]
            pitch_rate = voice_info[f"{task['type']}_pitch"]
            instruction = task.get("instruction")
            
            filename = f"{task_key}_{gender_key}.wav"
            file_path = output_dir / filename
            
            print(f"\n正在生成 [{gender_desc}] 文件: {filename}")
            print(f"  ├─ 文本: '{text}'")
            print(f"  ├─ Prompt: '{instruction}'")
            print(f"  └─ 参数: Volume={volume}, Rate={speech_rate}, Pitch={pitch_rate}")
            
            try:
                kwargs = {
                    "model": MODEL_NAME,
                    "voice": voice_code,
                    "format": AudioFormat.WAV_24000HZ_MONO_16BIT,
                    "volume": volume,
                    "speech_rate": speech_rate,
                    "pitch_rate": pitch_rate
                }
                if instruction:
                    kwargs["instruction"] = instruction

                synthesizer = SpeechSynthesizer(**kwargs)
                audio_data = synthesizer.call(text)
                
                if audio_data:
                    with open(file_path, "wb") as f:
                        f.write(audio_data)
                    print(f"  └─ 成功保存: {file_path.name}")
                    generated_files.append(file_path)
                else:
                    print(f"  └─ 失败: 未收到音频数据")
            except Exception as e:
                print(f"  └─ 合成出错: {e}")

    print("\n=== 目标语音生成完毕 ===")
    print("保存的文件如下：")
    for gf in generated_files:
        print(f" - {gf.name}")

if __name__ == "__main__":
    main()
