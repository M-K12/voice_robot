import os
import wave
import numpy as np
from pathlib import Path
from dotenv import load_dotenv
import dashscope
from dashscope.audio.tts_v2 import SpeechSynthesizer, AudioFormat

load_dotenv()
dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")

MODEL_NAME = "qwen-audio-3.0-tts-plus"

VOICES = {
    "female": {"name": "longanlingxin", "gender": "女声"},
    "male": {"name": "longanlufeng", "gender": "男声"}
}

def synthesize_and_crop(voice_code, gender_key):
    output_dir = Path(__file__).parent / "backend" / "assets"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 策略1: 输入完整流畅句“好的，小安退下了。”
    raw_text = "好的，小安退下了。"
    instruction = "助手轻声顺从地回答主人"
    
    print(f"正在为 [{gender_key}] 合成完整自然语句: '{raw_text}'...")
    synthesizer = SpeechSynthesizer(
        model=MODEL_NAME,
        voice=voice_code,
        format=AudioFormat.WAV_24000HZ_MONO_16BIT,
        volume=75,
        speech_rate=1.0,
        pitch_rate=0.98,
        instruction=instruction
    )
    audio_bytes = synthesizer.call(raw_text)
    
    if not audio_bytes:
        print("合成失败")
        return

    # 先保存原始带有“好的”的完整音频备用
    raw_file = output_dir / f"exit_full_{gender_key}.wav"
    with open(raw_file, "wb") as f:
        f.write(audio_bytes)

    # 读取 WAV 头和数据
    header = audio_bytes[:44]
    pcm_data = np.frombuffer(audio_bytes[44:], dtype=np.int16)

    # 通过寻找能量与静音间隙，把前面的“好的”以及后续的停顿自动切除
    # 24000采样率下，10ms 帧长 = 240 点
    frame_size = 240
    num_frames = len(pcm_data) // frame_size
    energies = [np.sum(np.abs(pcm_data[i*frame_size:(i+1)*frame_size], dtype=np.float64)) for i in range(num_frames)]
    
    # 前面“好的”大致在前 0.3s - 0.7s 之间，寻找第一个高峰（好的），再找中间的小波谷，截取波谷之后（小安退下了）
    # 0.4秒约为 40 帧
    search_start_frame = 25  # 从 ~0.25s 开始寻找“好的”发音结束后的低能量隙
    
    # 找到 0.25s ~ 0.8s 之间的能量极小值（字间静音 gap）
    search_end_frame = min(80, num_frames)
    min_gap_frame = search_start_frame + np.argmin(energies[search_start_frame:search_end_frame])
    
    # 从此 gap 处往后切
    crop_sample_idx = min_gap_frame * frame_size
    
    # 裁剪后的 PCM 数据
    cropped_pcm = pcm_data[crop_sample_idx:]
    
    # 重新写入 exit_female.wav / exit_male.wav
    cropped_file = output_dir / f"exit_{gender_key}.wav"
    
    with wave.open(str(cropped_file), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(cropped_pcm.tobytes())

    print(f"  └─ 成功切除前缀，提取纯正自然 '小安退下了' 保存至: {cropped_file.name}")

def main():
    for gender_key, info in VOICES.items():
        synthesize_and_crop(info["name"], gender_key)

if __name__ == "__main__":
    main()
