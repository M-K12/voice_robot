import os
import sys
import json
import asyncio
import logging
import traceback
import numpy as np
from pathlib import Path
from fastapi import WebSocket, WebSocketDisconnect

# 修复 Windows 下 "The requested API version [23] is not available" 错误
if sys.platform == "win32":
    import importlib.util
    spec = importlib.util.find_spec("sherpa_onnx")
    if spec and spec.origin:
        sherpa_onnx_dir = Path(spec.origin).parent
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(str(sherpa_onnx_dir))
            except Exception:
                pass
        os.environ["PATH"] = str(sherpa_onnx_dir) + os.pathsep + os.environ.get("PATH", "")

try:
    import sherpa_onnx
except ImportError:
    sherpa_onnx = None

logger = logging.getLogger("xiaoan.local_voice")

from utils import is_exit_intent
from handlers.openai_chat_handler import OpenAIChatHandler


# 全局模型实例缓存 (单例)
_streaming_asr = None
_offline_asr = None
_tts_engine = None
_chat_handler = None

import re

def get_shared_chat_handler() -> OpenAIChatHandler:
    global _chat_handler
    if _chat_handler is None:
        _chat_handler = OpenAIChatHandler()
    return _chat_handler

def clean_text_for_vits(text: str) -> str:
    """将大模型文本中的 Emoji、Markdown 标志剥离，并将英文词汇/英文字母转换为中文谐音，便于纯中文 VITS 朗读"""
    # 1. 过滤 Emoji 及所有表情字符
    text = re.sub(r"[\U00010000-\U0010ffff]", "", text)
    # 2. 过滤 Markdown 符号（如 *, #, `, -, >, _, ~ 等）
    text = re.sub(r"[\*\#\`\-\>\_\~]", "", text)
    
    # 3. 常用多字符英文词汇与缩写转换 (全词匹配且忽略大小写)
    replacements = {
        r"\b[aA][iI]\b": "人工智能",
        r"\b[aA][pP][iI]\b": "接口",
        r"\b[oO][kK]\b": "欧克",
        r"\b[gG][pP][uU]\b": "显卡",
        r"\b[cC][pP][uU]\b": "处理器",
        r"\b[uU][vV]\b": "优威",
        r"\b[pP][yY][tT][hH][oO][nN]\b": "派森",
        r"\b[wW][eE][bB][sS][oO][cC][kK][eE][tT]\b": "套接字",
        r"\b[oO][lL][lL][aA][mM][aA]\b": "奥拉马",
        r"\b[qQ][wW][eE][nN]\b": "千问",
        r"\b[tT][tT][sS]\b": "语音合成",
        r"\b[aA][sS][rR]\b": "语音识别",
        r"\b[vV][aA][dD]\b": "端点检测",
        r"\b[cC][uU][dD][nN][nN]\b": "库丹",
        r"\b[cC][uU][dD][aA]\b": "库达",
    }
    for pattern, repl in replacements.items():
        text = re.sub(pattern, repl, text)
        
    # 4. 未被匹配到的独立英文字母/单词，按字符逐一转换为发音谐音
    alphabet_map = {
        'a': '诶', 'b': '必', 'c': '西', 'd': '地', 'e': '伊', 'f': '艾弗', 'g': '基',
        'h': '艾驰', 'i': '哎', 'j': '杰', 'k': '开', 'l': '艾尔', 'm': '艾姆', 'n': '恩',
        'o': '欧', 'p': '批', 'q': '扣', 'r': '阿尔', 's': '艾斯', 't': '踢', 'u': '尤',
        'v': '微', 'w': '达布刘', 'x': '埃克斯', 'y': '歪', 'z': '贼'
    }
    
    def repl_word(match):
        word = match.group(0).lower()
        return "".join(alphabet_map.get(char, char) for char in word)
        
    text = re.sub(r"[a-zA-Z]+", repl_word, text)
    return text

def _get_local_provider() -> str:
    """从 config.json 动态获取本地硬件加速 provider"""
    try:
        from utils import load_config
        return load_config().get("local_provider", "cpu")
    except Exception:
        return "cpu"

def get_streaming_asr():
    """获取本地流式 ASR 识别器"""
    global _streaming_asr
    if sherpa_onnx is None:
        raise ImportError("sherpa-onnx 未安装，无法启动本地 ASR 引擎。")
    if _streaming_asr is None:
        logger.info(f"正在初始化流式 ASR 识别器 (Zipformer 80M), provider: {_get_local_provider()}...")
        project_root = Path(__file__).parent.parent.parent.resolve()
        model_dir = project_root / "sherpa" / "models" / "sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20"
        
        _streaming_asr = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(model_dir / "tokens.txt"),
            encoder=str(model_dir / "encoder-epoch-99-avg-1.onnx"),
            decoder=str(model_dir / "decoder-epoch-99-avg-1.onnx"),
            joiner=str(model_dir / "joiner-epoch-99-avg-1.onnx"),
            sample_rate=16000,
            feature_dim=80,
            decoding_method="greedy_search",
            num_threads=2,
            provider=_get_local_provider()
        )
        logger.info("流式 ASR 识别器初始化完成！")
    return _streaming_asr

def get_offline_asr():
    """获取本地非流式 ASR 识别器"""
    global _offline_asr
    if sherpa_onnx is None:
        raise ImportError("sherpa-onnx 未安装，无法启动本地 ASR 引擎。")
    if _offline_asr is None:
        logger.info(f"正在初始化离线 ASR 识别器 (SenseVoice-Small), provider: {_get_local_provider()}...")
        project_root = Path(__file__).parent.parent.parent.resolve()
        model_dir = project_root / "sherpa" / "models" / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
        
        # 优先使用 int8 模型
        model_file = model_dir / "model.int8.onnx"
        if not model_file.exists():
            model_file = model_dir / "model.onnx"
            
        _offline_asr = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(model_file),
            tokens=str(model_dir / "tokens.txt"),
            num_threads=2,
            use_itn=True,
            provider=_get_local_provider()
        )
        logger.info("离线 ASR 识别器 (SenseVoice-Small) 初始化完成！")
    return _offline_asr

def get_tts_engine():
    """获取本地 TTS 语音合成器"""
    global _tts_engine
    if sherpa_onnx is None:
        raise ImportError("sherpa-onnx 未安装，无法启动本地 TTS 引擎。")
    if _tts_engine is None:
        logger.info(f"正在初始化离线 TTS 合成器 (VITS), provider: {_get_local_provider()}...")
        project_root = Path(__file__).parent.parent.parent.resolve()
        model_dir = project_root / "sherpa" / "models" / "vits-icefall-zh-aishell3"
        
        tts_config = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=str(model_dir / "model.onnx"),
                    lexicon=str(model_dir / "lexicon.txt"),
                    tokens=str(model_dir / "tokens.txt"),
                    data_dir="",
                ),
                num_threads=2,
                provider=_get_local_provider()
            ),
            rule_fsts=",".join([str(model_dir / f) for f in ["phone.fst", "date.fst", "number.fst"]])
        )
        _tts_engine = sherpa_onnx.OfflineTts(tts_config)
        logger.info("离线 TTS 合成器 (VITS) 初始化完成！")
    return _tts_engine


async def synthesize_and_play(text: str, tts, speaker_id: int, websocket: WebSocket, speed_rate: float = 1.0):
    """将文本合成为语音并下发"""
    clean_text = clean_text_for_vits(text).strip()
    if not clean_text:
        return
    try:
        audio = await asyncio.to_thread(tts.generate, clean_text, sid=speaker_id, speed=speed_rate)
        samples_arr = np.array(audio.samples, dtype=np.float32)
        pcm_bytes = (samples_arr * 32768.0).astype(dtype=np.int16).tobytes()
        
        await websocket.send_bytes(b"\x00" + pcm_bytes)
        await websocket.send_json({"type": "output_transcript", "data": text})
    except Exception as e:
        logger.error(f"[Local-TTS] Synthesis failed for text '{text}': {e}")


async def handle_local_voice_session(
    websocket: WebSocket, 
    voice: str, 
    config: dict, 
    visual_broadcast_manager: Any
):
    """接管本地 ASR + TTS 的 WebSocket 通话会话主循环"""
    asr_mode = config.get("asr_mode", "offline")
    default_city = config.get("default_city", "")
    speaker_id = int(config.get("local_tts_speaker_id", 0))
    try:
        if voice and voice.isdigit():
            speaker_id = int(voice)
    except Exception:
        pass
    speed_rate = float(config.get("local_tts_speed_rate", 1.05))
    
    silence_timeout = float(config.get("cascade_silence_duration_ms", 1200)) / 1000.0
    energy_threshold = float(config.get("cascade_vad_energy_threshold", 0.025))
    
    print(f"\n\033[95m[Local-Voice] ===== 本地语音会话已开启 =====\033[0m")
    print(f"\033[95m[Local-Voice] ASR 模式: {asr_mode}, TTS 发音人 ID: {speaker_id}, 语速: {speed_rate}, VAD 静音判定: {silence_timeout}s, 能量阈值: {energy_threshold}\033[0m")
    
    try:
        tts_engine = get_tts_engine()
        if asr_mode == "streaming":
            asr_recognizer = get_streaming_asr()
            asr_stream = asr_recognizer.create_stream()
        else:
            asr_recognizer = get_offline_asr()
            audio_buffer = []
    except Exception as e:
        print(f"\033[91m[Local-Voice] 初始化引擎失败: {e}\033[0m")
        traceback.print_exc()
        await websocket.send_json({"type": "error", "message": f"引擎加载失败: {str(e)}"})
        return

    session_active = True
    silence_duration = 0.0
    chunk_duration = 0.1
    last_asr_result = ""
    chat_history = []
    has_spoken = False
    
    await visual_broadcast_manager.broadcast({"type": "state_change", "state": "listening"})
    await websocket.send_json({"type": "debug_event", "step": "asr_ready", "content": f"本地语音引擎就绪，识别模式：{asr_mode}"})
    print(f"\033[92m[Local-Voice] 本地语音接收循环就绪，等待音频输入...\033[0m")

    try:
        while session_active:
            msg = await websocket.receive()
            if "bytes" in msg:
                data = msg["bytes"]
                if len(data) > 1 and data[0] == 0x00:
                    pcm_bytes = data[1:]
                    samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
                    
                    energy = np.sqrt(np.mean(samples ** 2)) if len(samples) > 0 else 0.0
                    is_silence = energy < energy_threshold
                    
                    if is_silence:
                        silence_duration += chunk_duration
                    else:
                        silence_duration = 0.0
                        if not has_spoken:
                            has_spoken = True
                            print(f"\n\033[93m[Local-VAD] 检测到声学信号 (能量: {energy:.4f})，开始采集用户语音...\033[0m")

                    if asr_mode == "streaming":
                        asr_stream.accept_waveform(16000, samples)
                        while asr_recognizer.is_ready(asr_stream):
                            asr_recognizer.decode_stream(asr_stream)
                        
                        current_text = asr_recognizer.get_result(asr_stream)
                        if current_text and current_text != last_asr_result:
                            last_asr_result = current_text
                            await websocket.send_json({"type": "input_transcript", "data": current_text})
                            await visual_broadcast_manager.broadcast({"type": "asr_result", "text": current_text})
                            print(f"\033[90m[Local-ASR] 流式中间文字: '{current_text}'\033[0m", end="\r")

                        if silence_duration >= silence_timeout and has_spoken:
                            final_text = current_text.strip()
                            print(f"\n\033[92m[Local-VAD] 说话结束。最终识别文本: '{final_text}'\033[0m")
                            
                            if final_text:
                                await run_voice_chat_pipeline(
                                    final_text, chat_history, tts_engine, speaker_id, 
                                    websocket, visual_broadcast_manager, default_city,
                                    speed_rate=speed_rate
                                )
                            
                            asr_stream = asr_recognizer.create_stream()
                            last_asr_result = ""
                            silence_duration = 0.0
                            has_spoken = False
                    else:
                        if has_spoken:
                            audio_buffer.append(samples)
                        
                        if silence_duration >= silence_timeout and has_spoken and len(audio_buffer) > 5:
                            print(f"\033[92m[Local-VAD] 说话结束。正在使用 SenseVoice-Small 识别音频...\033[0m")
                            full_audio = np.concatenate(audio_buffer)
                            audio_buffer = []
                            silence_duration = 0.0
                            has_spoken = False
                            
                            offline_stream = asr_recognizer.create_stream()
                            offline_stream.accept_waveform(16000, full_audio)
                            asr_recognizer.decode_streams([offline_stream])
                            result_text = offline_stream.result.text
                            
                            if result_text.strip():
                                final_text = result_text.strip()
                                print(f"\033[96m[Local-ASR] SenseVoice 识别文本: '{final_text}'\033[0m")
                                
                                await websocket.send_json({"type": "input_transcript", "data": final_text})
                                await visual_broadcast_manager.broadcast({"type": "asr_result", "text": final_text})
                                
                                await run_voice_chat_pipeline(
                                    final_text, chat_history, tts_engine, speaker_id, 
                                    websocket, visual_broadcast_manager, default_city,
                                    speed_rate=speed_rate
                                )
                            else:
                                print(f"\033[90m[Local-ASR] 未识别出有效字符 (SenseVoice 返回空串)\033[0m")
                                
            elif "text" in msg:
                try:
                    payload = json.loads(msg["text"])
                    if payload.get("type") == "interrupt":
                        print(f"\033[93m[Local-Voice] 收到打断指令，重置为倾听状态\033[0m")
                        await visual_broadcast_manager.broadcast({"type": "state_change", "state": "listening"})
                        await websocket.send_json({"type": "state_change", "state": "listening"})
                        await websocket.send_json({"type": "interrupt"})
                    elif payload.get("type") == "query":
                        text = payload.get("text", "").strip()
                        if is_exit_intent(text):
                            print(f"\033[91m[Local-Voice] 收到前端挂断指令: {text}\033[0m")
                            await websocket.send_json({"type": "hangup"})
                            session_active = False
                except Exception as e:
                    print(f"\033[91m[Local-Voice] 解析文本消息出错: {e}\033[0m")
    except WebSocketDisconnect:
        print(f"\033[91m[Local-Voice] WebSocket 通话连接已断开。\033[0m")
    except RuntimeError as e:
        if "receive" in str(e) or "disconnect" in str(e):
            print(f"\033[91m[Local-Voice] WebSocket 通话正常结束。\033[0m")
        else:
            print(f"\033[91m[Local-Voice] 运行时异常: {e}\033[0m")
            traceback.print_exc()
    except Exception as e:
        print(f"\033[91m[Local-Voice] 会话循环异常退出: {e}\033[0m")
        traceback.print_exc()
    finally:
        session_active = False
        print(f"\033[95m[Local-Voice] ===== 本地语音会话已关闭 =====\033[0m\n")


async def run_voice_chat_pipeline(
    final_text: str,
    chat_history: list,
    tts_engine,
    speaker_id: int,
    websocket: WebSocket,
    visual_broadcast_manager,
    default_city: str,
    speed_rate: float = 1.0
):
    """将 ASR 结果喂给核心大模型应答流，并流式断句通过 TTS 播放"""
    if is_exit_intent(final_text):
        print(f"\033[91m[Local-Voice] 识别到退出指令，执行挂断并退回复位...\033[0m")
        await websocket.send_json({"type": "hangup"})
        await visual_broadcast_manager.broadcast({"type": "interrupted"})
        await visual_broadcast_manager.broadcast({"type": "state_change", "state": "idle"})
        return
        
    print(f"\033[94m[Local-LLM] 发起大模型会话. 用户文本: '{final_text}'\033[0m")
    await visual_broadcast_manager.broadcast({"type": "state_change", "state": "thinking"})
    
    ai_reply_text = ""
    sentence_buffer = ""
    punctuations = ["。", "？", "！", "；", ".", "?", "!", ";", "\n"]
    chat_handler = get_shared_chat_handler()
    
    try:
        async for token in chat_handler.stream_project_text_chat(message=final_text, history=chat_history, city=default_city):
            ai_reply_text += token
            sentence_buffer += token
            
            await websocket.send_json({"type": "output_transcript", "data": ai_reply_text})
            await visual_broadcast_manager.broadcast({"type": "subtitle", "text": ai_reply_text})
            
            has_punc = any(p in sentence_buffer for p in punctuations)
            if has_punc:
                last_punc_idx = -1
                for idx, char in enumerate(sentence_buffer):
                    if char in punctuations:
                        last_punc_idx = idx
                
                if last_punc_idx != -1:
                    sub_sentence = sentence_buffer[:last_punc_idx+1].strip()
                    sentence_buffer = sentence_buffer[last_punc_idx+1:]
                    
                    if sub_sentence:
                        print(f"\033[90m[Local-LLM] 吐句分词: '{sub_sentence}'\033[0m")
                        await visual_broadcast_manager.broadcast({"type": "state_change", "state": "speaking"})
                        await synthesize_and_play(sub_sentence, tts_engine, speaker_id, websocket, speed_rate=speed_rate)
                
        if sentence_buffer.strip():
            final_sub = sentence_buffer.strip()
            print(f"\033[90m[Local-LLM] 吐句分词(完结): '{final_sub}'\033[0m")
            await visual_broadcast_manager.broadcast({"type": "state_change", "state": "speaking"})
            await synthesize_and_play(final_sub, tts_engine, speaker_id, websocket, speed_rate=speed_rate)
            
        if ai_reply_text.strip():
            print(f"\033[92m[Local-LLM] AI 完整答复: '{ai_reply_text.strip()}'\033[0m")
            chat_history.append({"role": "user", "content": final_text})
            chat_history.append({"role": "assistant", "content": ai_reply_text.strip()})
            await websocket.send_json({"type": "output_transcript", "data": ai_reply_text.strip()})
            await websocket.send_json({"type": "output_transcript_done"})
            
    except Exception as e:
        print(f"\033[91m[Local-LLM] 大模型会话管道抛出异常: {e}\033[0m")
        traceback.print_exc()
    finally:
        await visual_broadcast_manager.broadcast({"type": "state_change", "state": "idle"})
        print(f"\033[95m[Local-Voice] ===== 对话管道流执行完毕 =====\033[0m")
