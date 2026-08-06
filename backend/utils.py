import re
import json
import httpx
import asyncio
import sys
import logging
from pathlib import Path
from typing import Optional, Any, List
from fastapi import WebSocket
from starlette.websockets import WebSocketState

logger = logging.getLogger("xiaoan.utils")

FALLBACK_DEFAULT_CITY = "歙县"

def _get_configs_dir() -> Path:
    """Intelligently locate configs directory across standalone executable and dev environments."""
    candidates = [
        Path(sys.executable).parent / "configs",
        Path(sys.executable).parent.parent / "configs",
        Path(sys.executable).parent / "_internal" / "configs",
        Path.cwd() / "configs",
        Path.cwd() / "backend" / "configs",
        Path(__file__).parent.parent.resolve() / "configs",
        Path(__file__).parent.resolve() / "configs",
    ]
    for c in candidates:
        if c.exists() and c.is_dir():
            return c
    return Path(__file__).parent.parent.resolve() / "configs"

_CITY_TO_AREACODE = {}
_AREACODE_TO_STATION = {}
_DICT_LOADED = False

def _load_station_dicts():
    """Load city and station mapping files into memory."""
    global _CITY_TO_AREACODE, _AREACODE_TO_STATION, _DICT_LOADED
    if _DICT_LOADED:
        return
    base_dir = Path(__file__).parent.parent / "spd-weather" / "assets"
    try:
        with open(base_dir / "city_to_areacode.json", "r", encoding="utf-8") as f:
            _CITY_TO_AREACODE = json.load(f)
        with open(base_dir / "areacode_to_station.json", "r", encoding="utf-8") as f:
            _AREACODE_TO_STATION = json.load(f)
        _DICT_LOADED = True
    except Exception:
        pass

def get_city_lonlat(city: str) -> Optional[list[float]]:
    """Look up latitude and longitude of a city from local station dictionaries."""
    _load_station_dicts()
    candidates = [city, city.replace("市", ""), city + "市"]
    area_code = None
    for cand in candidates:
        area_code = _CITY_TO_AREACODE.get(cand)
        if area_code:
            break
    if not area_code:
        return None
    station = _AREACODE_TO_STATION.get(area_code)
    if not station:
        return None
    lat, lon = station.get("lat"), station.get("lon")
    if lat is not None and lon is not None:
        return [lon, lat]
    return None


async def get_city_by_ip() -> str:
    """通过 IP 自动定位当前所在城市 (保底获取)"""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            res = await client.get("http://ip-api.com/json/?lang=zh-CN")
            if res.status_code == 200:
                data = res.json()
                city = data.get("city", "")
                if city:
                    clean_city = city.strip()
                    if not clean_city.endswith("市") and not clean_city.endswith("县"):
                        clean_city += "市"
                    logger.info(f"[IP Location] 成功自动识别当前 IP 所在城市: {clean_city}")
                    return clean_city
    except Exception as e:
        logger.warning(f"[IP Location] 通过 IP 自动获取城市失败，使用保底城市: {e}")
    return "北京市"

def clean_echo_text(text: str, last_ai_summary: str) -> str:
    """Clean user input by removing overlap with the last AI summary text to avoid echo."""
    if last_ai_summary and len(text) > 5:
        if last_ai_summary in text:
            return text.replace(last_ai_summary, "").strip()
        for i in range(min(len(text), 15), 2, -1):
            if last_ai_summary.endswith(text[:i]):
                return text[i:].strip()
    return text

async def fetch_default_city() -> str:
    """Fetch default city from local configuration (configs/global.json) or external IP geolocation service."""
    # 1. 优先读取配置文件 (configs/global.json) 中的 default_city
    try:
        cfg = load_config()
        city = cfg.get("default_city")
        if city:
            return city
    except Exception:
        pass

    # 2. 回退通过 IP 自动定位当前城市
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get("http://ip-api.com/json/?lang=zh-CN", timeout=5.0)
            data = resp.json()
            if data.get("status") == "success":
                city = data.get("city", "")
                if city:
                    if city.endswith("市"):
                        city = city[:-1]
                    return city
    except Exception:
        pass

    # 3. 终极兜底保底返回
    return FALLBACK_DEFAULT_CITY

def resolve_model_path(model_dir: str) -> Path:
    """Resolve model_dir to absolute Path using multiple base directories."""
    path = Path(model_dir)
    if path.is_absolute():
        return path
    project_root = Path(__file__).parent.parent.resolve()
    test_path = project_root / model_dir
    if test_path.exists():
        return test_path
    test_path2 = Path.cwd() / model_dir
    if test_path2.exists():
        return test_path2
    return test_path

def read_wake_word_from_model(model_dir: str) -> str:
    """Read all wake words from keywords.txt inside model_dir."""
    try:
        resolved_path = resolve_model_path(model_dir)
        keywords_path = resolved_path / "keywords.txt"
        if keywords_path.exists():
            with open(keywords_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    return content
    except Exception:
        pass
    return "x iǎo ān x iǎo ān @小安小安"

def write_wake_word_to_model(model_dir: str, wake_word: str):
    """Generate pinyin and write wake_word (can be multi-line) into keywords.txt in model_dir."""
    from pypinyin import pinyin, Style
    
    # 按照换行符拆分，去除两端空白，过滤空行
    lines = [w.strip() for w in wake_word.split("\n") if w.strip()]
    if not lines:
        return
        
    output_lines = []
    for word in lines:
        if "@" in word:
            # 如果行本身已经有 @，说明是拼音/参数行，直接透传原样写入
            output_lines.append(word)
            continue
            
        parts = []
        for char in word:
            if '\u4e00' <= char <= '\u9fff':
                # 使用 strict=False 将 y/w 作为声母返回
                init = pinyin(char, style=Style.INITIALS, strict=False)[0][0]
                final = pinyin(char, style=Style.FINALS_TONE, strict=False)[0][0]
                
                # 在 j, q, x, y 后的 ü 系列韵母在 tokens.txt 中都被省略了两点，写作 u 系列韵母
                if init in ['j', 'q', 'x', 'y']:
                    ü_map = {
                        'ǖ': 'ū',
                        'ǘ': 'ú',
                        'ǚ': 'ǔ',
                        'ǜ': 'ù',
                        'ü': 'u'
                    }
                    for k, v in ü_map.items():
                        final = final.replace(k, v)
                        
                if init:
                    parts.append(f"{init} {final}")
                else:
                    parts.append(final)
            else:
                char_stripped = char.strip()
                if char_stripped:
                    parts.append(char_stripped)
        pinyin_str = " ".join(parts)
        output_lines.append(f"{pinyin_str} @{word}")
        
    resolved_path = resolve_model_path(model_dir)
    resolved_path.mkdir(parents=True, exist_ok=True)
    keywords_path = resolved_path / "keywords.txt"
    
    with open(keywords_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output_lines) + "\n")

def _get_safe_filename(name: str) -> str:
    """Convert a model name to a safe filename string for Windows compatibility."""
    if not name:
        return "default"
    return name.replace(":", "_").replace("/", "_").replace("\\", "_")

def load_config() -> dict:
    """
    Load configuration according to modular configs/ structure:
    1. Read global settings from configs/global.json
    2. Read active models from configs/model_config.json
    3. Dynamically scan configs/models/* and sherpa/models/ to build options and voice_options_map
    4. Merge fine-grained settings from active model JSON files and keywords.txt
    """
    configs_dir = _get_configs_dir()
    project_root = configs_dir.parent
    models_dir = configs_dir / "models"
    
    global_config = {}

    # 1. 基础全局属性 (configs/global.json)
    global_json = configs_dir / "global.json"
    if global_json.exists():
        try:
            with open(global_json, "r", encoding="utf-8") as f:
                global_config.update(json.load(f))
        except Exception:
            pass

    # 1.2 前端 UI 偏好配置 (configs/frontend_config.json)
    frontend_json = configs_dir / "frontend_config.json"
    if frontend_json.exists():
        try:
            with open(frontend_json, "r", encoding="utf-8") as f:
                global_config.update(json.load(f))
        except Exception:
            pass

    # 1.5 KWS 引擎专属配置 (configs/kws_config.json)
    kws_json = configs_dir / "kws_config.json"
    if kws_json.exists():
        try:
            with open(kws_json, "r", encoding="utf-8") as f:
                global_config.update(json.load(f))
        except Exception:
            pass

    # 2. 模式激活模型 (configs/model_config.json)
    model_cfg_json = configs_dir / "model_config.json"
    if model_cfg_json.exists():
        try:
            with open(model_cfg_json, "r", encoding="utf-8") as f:
                mc = json.load(f)
                if "text_chat" in mc and "model_name" in mc["text_chat"]:
                    global_config["text_model_name"] = mc["text_chat"]["model_name"]
                if "cascade_voice" in mc:
                    cv = mc["cascade_voice"]
                    if "brain_model_name" in cv:
                        global_config["voice_cascade_model_name"] = cv["brain_model_name"]
                    if "asr_mode" in cv:
                        global_config["asr_mode"] = cv["asr_mode"]
                    if "tts_engine" in cv:
                        global_config["cascade_tts_type"] = cv["tts_engine"]
                if "realtime_voice" in mc and "model_name" in mc["realtime_voice"]:
                    global_config["voice_model_name"] = mc["realtime_voice"]["model_name"]
                if "kws" in mc and "sherpa_model_dir" in mc["kws"]:
                    global_config["sherpa_model_dir"] = mc["kws"]["sherpa_model_dir"]
        except Exception:
            pass

    # 3. 动态扫描文本模型 (configs/models/text/*.json)
    text_dir = models_dir / "text"
    text_options = []
    if text_dir.exists():
        for p in sorted(text_dir.glob("*.json")):
            text_options.append({"value": p.stem, "label": p.stem})
    global_config["text_model_options"] = text_options

    # 4. 动态扫描端到端语音模型与发音人字典 (configs/models/voice_e2e/*.json)
    voice_dir = models_dir / "voice_e2e"
    voice_options = []
    voice_options_map = {}
    if voice_dir.exists():
        for p in sorted(voice_dir.glob("*.json")):
            voice_options.append({"value": p.stem, "label": p.stem})
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "voice_options" in data:
                        voice_options_map[p.stem] = data["voice_options"]
            except Exception:
                pass
    global_config["voice_model_options"] = voice_options
    global_config["voice_options_map"] = voice_options_map

    # 4.5 动态扫描 ASR 模型 (configs/models/asr/*.json)
    asr_dir = models_dir / "asr"
    asr_options = []
    if asr_dir.exists():
        for p in sorted(asr_dir.glob("*.json")):
            asr_options.append({"value": p.stem, "label": p.stem})
    global_config["asr_model_options"] = asr_options

    # 5. 动态扫描唤醒模型目录 (sherpa/models/sherpa-onnx-kws-*)
    sherpa_models_base = project_root / "sherpa" / "models"
    kws_options = []
    if sherpa_models_base.exists():
        for p in sherpa_models_base.iterdir():
            if p.is_dir() and "sherpa-onnx-kws-" in p.name:
                rel_path = f"sherpa/models/{p.name}"
                kws_options.append({"value": rel_path, "label": p.name})
    global_config["kws_model_options"] = kws_options

    # 6. 加载当前文本大模型专属参数 (configs/models/text/{text_model_name}.json)
    text_model = global_config.get("text_model_name")
    if text_model:
        safe_text = _get_safe_filename(text_model)
        p = text_dir / f"{safe_text}.json"
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "tool_mode" in data:
                        global_config["text_model_tool_mode"] = data["tool_mode"]
                    if "tool_style" in data:
                        global_config["text_model_tool_style"] = data["tool_style"]
            except Exception:
                pass

    # 7. 加载当前级联大脑专属参数 (共享 configs/models/text/{voice_cascade_model_name}.json)
    cascade_model = global_config.get("voice_cascade_model_name")
    if cascade_model:
        safe_cascade = _get_safe_filename(cascade_model)
        p = text_dir / f"{safe_cascade}.json"
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "tool_mode" in data:
                        global_config["voice_cascade_model_tool_mode"] = data["tool_mode"]
                    if "tool_style" in data:
                        global_config["voice_cascade_model_tool_style"] = data["tool_style"]
            except Exception:
                pass

    # 8. 加载当前端到端语音模型专属参数 (configs/models/voice_e2e/{voice_model_name}.json)
    voice_model = global_config.get("voice_model_name")
    if voice_model and voice_model != "sherpa-local":
        safe_voice = _get_safe_filename(voice_model)
        p = voice_dir / f"{safe_voice}.json"
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "current_voice" in data:
                        global_config["voice"] = data["current_voice"]
                    for k in ["voice_speed", "temperature", "max_tokens", "vad_silence_duration_ms", "silence_duration_ms", "qwen_audio_turn_mode", "qwen_audio_vad_threshold", "qwen_audio_voiceprint_mode", "selected_voiceprint_id", "qwen_audio_voiceprint_audio_urls", "qwen_audio_max_history_turns"]:
                        if k in data:
                            if k == "temperature":
                                global_config["e2e_temperature"] = data[k]
                            elif k == "max_tokens":
                                global_config["e2e_max_tokens"] = data[k]
                            elif k in ("vad_silence_duration_ms", "silence_duration_ms"):
                                global_config["e2e_silence_duration_ms"] = data[k]
                            else:
                                global_config[k] = data[k]

            except Exception:
                pass

    # 9. 加载当前级联 TTS 引擎专属参数 (configs/models/tts/{cascade_tts_type}.json)
    tts_type = global_config.get("cascade_tts_type")
    if tts_type:
        safe_tts = _get_safe_filename(tts_type)
        p = models_dir / "tts" / f"{safe_tts}.json"
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "current_speaker_id" in data:
                        global_config["local_tts_speaker_id"] = data["current_speaker_id"]
                    if "speed_rate" in data:
                        global_config["local_tts_speed_rate"] = data["speed_rate"]
                    if "silence_duration_ms" in data:
                        global_config["cascade_silence_duration_ms"] = data["silence_duration_ms"]
                    if "vad_energy_threshold" in data:
                        global_config["cascade_vad_energy_threshold"] = data["vad_energy_threshold"]
            except Exception:
                pass

    # 10. 加载当前 KWS 唤醒模型专属参数 (configs/models/kws/{safe_kws_dir_name}.json)
    sherpa_dir = global_config.get("sherpa_model_dir")
    if sherpa_dir:
        safe_kws = _get_safe_filename(sherpa_dir)
        p = models_dir / "kws" / f"{safe_kws}.json"
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for k in ["kws_max_active_paths", "kws_num_trailing_blanks", "kws_score", "kws_threshold"]:
                        if k in data:
                            global_config[k] = data[k]
            except Exception:
                pass
        # 从唤醒模型目录下的 keywords.txt 载入唤醒词
        global_config["wake_word"] = read_wake_word_from_model(sherpa_dir)

    return global_config

def save_config_split(new_config: dict) -> dict:
    """
    Save and split input configuration into configs/global.json, configs/model_config.json,
    configs/models/*/*.json, and model keywords.txt. Returns freshly loaded config.
    """
    configs_dir = _get_configs_dir()
    project_root = configs_dir.parent
    models_dir = configs_dir / "models"
    
    # 1. 写回基础全局属性 (configs/global.json)
    global_json = configs_dir / "global.json"
    global_fields = {}
    for k in ["default_city", "enable_visual_broadcast", "local_provider", "log_level", "log_file_level", "session_idle_timeout_sec", "voiceprint_server_url", "backend_url", "visual_terminal", "ui_type"]:
        if k in new_config:
            val = new_config[k]
            if k == "session_idle_timeout_sec":
                try:
                    val = int(val)
                except (ValueError, TypeError):
                    val = 30
            global_fields[k] = val
            
    if global_fields:
        curr_g = {}
        if global_json.exists():
            try:
                with open(global_json, "r", encoding="utf-8") as f:
                    curr_g = json.load(f)
            except Exception:
                pass
        curr_g.update(global_fields)
        try:
            with open(global_json, "w", encoding="utf-8") as f:
                json.dump(curr_g, f, indent=4, ensure_ascii=False)
        except Exception:
            pass

    # 1.2 写回前端 UI 偏好配置 (configs/frontend_config.json)
    frontend_json = configs_dir / "frontend_config.json"
    frontend_fields = {}
    for k in ["start_fullscreen", "show_weather_card"]:
        if k in new_config:
            frontend_fields[k] = new_config[k]
            
    if frontend_fields:
        curr_fe = {}
        if frontend_json.exists():
            try:
                with open(frontend_json, "r", encoding="utf-8") as f:
                    curr_fe = json.load(f)
            except Exception:
                pass
        curr_fe.update(frontend_fields)
        try:
            with open(frontend_json, "w", encoding="utf-8") as f:
                json.dump(curr_fe, f, indent=4, ensure_ascii=False)
        except Exception:
            pass

    # 1.5 写回 KWS 引擎专属配置 (configs/kws_config.json)
    kws_json = configs_dir / "kws_config.json"
    kws_fields = {}
    for k in ["wake_word", "sherpa_model_dir", "kws_max_active_paths", "kws_num_trailing_blanks", "kws_score", "kws_threshold"]:
        if k in new_config:
            kws_fields[k] = new_config[k]
            
    if kws_fields:
        curr_kws = {}
        if kws_json.exists():
            try:
                with open(kws_json, "r", encoding="utf-8") as f:
                    curr_kws = json.load(f)
            except Exception:
                pass
        curr_kws.update(kws_fields)
        try:
            with open(kws_json, "w", encoding="utf-8") as f:
                json.dump(curr_kws, f, indent=4, ensure_ascii=False)
        except Exception:
            pass

    # 2. 写回激活模型设置 (configs/model_config.json)
    model_cfg_json = configs_dir / "model_config.json"
    curr_mc = {
        "text_chat": {},
        "cascade_voice": {},
        "realtime_voice": {},
        "kws": {}
    }
    if model_cfg_json.exists():
        try:
            with open(model_cfg_json, "r", encoding="utf-8") as f:
                curr_mc.update(json.load(f))
        except Exception:
            pass

    if "text_model_name" in new_config:
        curr_mc.setdefault("text_chat", {})["model_name"] = new_config["text_model_name"]
    if "voice_cascade_model_name" in new_config:
        curr_mc.setdefault("cascade_voice", {})["brain_model_name"] = new_config["voice_cascade_model_name"]
    if "asr_mode" in new_config:
        curr_mc.setdefault("cascade_voice", {})["asr_mode"] = new_config["asr_mode"]
    if "cascade_tts_type" in new_config:
        curr_mc.setdefault("cascade_voice", {})["tts_engine"] = new_config["cascade_tts_type"]
    if "voice_model_name" in new_config:
        curr_mc.setdefault("realtime_voice", {})["model_name"] = new_config["voice_model_name"]
    if "sherpa_model_dir" in new_config:
        curr_mc.setdefault("kws", {})["sherpa_model_dir"] = new_config["sherpa_model_dir"]

    try:
        with open(model_cfg_json, "w", encoding="utf-8") as f:
            json.dump(curr_mc, f, indent=4, ensure_ascii=False)
    except Exception:
        pass

    # 3. 写回文本大模型细粒度设置 (configs/models/text/{model}.json)
    text_model = new_config.get("text_model_name")
    if text_model:
        safe_text = _get_safe_filename(text_model)
        p = models_dir / "text" / f"{safe_text}.json"
        text_data = {}
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    text_data = json.load(f)
            except Exception:
                pass
        text_data["value"] = text_model
        text_data.setdefault("label", text_model)
        if "text_model_tool_mode" in new_config:
            text_data["tool_mode"] = new_config["text_model_tool_mode"]
        if "text_model_tool_style" in new_config:
            text_data["tool_style"] = new_config["text_model_tool_style"]
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(text_data, f, indent=4, ensure_ascii=False)
        except Exception:
            pass

    # 4. 写回端到端语音模型细粒度设置 (configs/models/voice_e2e/{model}.json)
    voice_model = new_config.get("voice_model_name")
    if voice_model and voice_model != "sherpa-local":
        safe_voice = _get_safe_filename(voice_model)
        p = models_dir / "voice_e2e" / f"{safe_voice}.json"
        v_data = {}
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    v_data = json.load(f)
            except Exception:
                pass
        v_data["value"] = voice_model
        v_data.setdefault("label", voice_model)
        if "voice" in new_config:
            v_data["current_voice"] = new_config["voice"]
        if "voice_speed" in new_config:
            v_data["voice_speed"] = new_config["voice_speed"]
        if "voice_model_tool_mode" in new_config:
            v_data["tool_mode"] = new_config["voice_model_tool_mode"]
        if "e2e_temperature" in new_config:
            v_data["temperature"] = new_config["e2e_temperature"]
        if "e2e_max_tokens" in new_config:
            v_data["max_tokens"] = new_config["e2e_max_tokens"]
        if "e2e_silence_duration_ms" in new_config:
            v_data["vad_silence_duration_ms"] = new_config["e2e_silence_duration_ms"]
            v_data.pop("silence_duration_ms", None)
            v_data.pop("e2e_silence_duration_ms", None)
        if "qwen_audio_turn_mode" in new_config:
            v_data["qwen_audio_turn_mode"] = new_config["qwen_audio_turn_mode"]
        if "qwen_audio_vad_threshold" in new_config:
            v_data["qwen_audio_vad_threshold"] = new_config["qwen_audio_vad_threshold"]
        if "qwen_audio_voiceprint_mode" in new_config:
            v_data["qwen_audio_voiceprint_mode"] = new_config["qwen_audio_voiceprint_mode"]
        if "selected_voiceprint_id" in new_config:
            v_data["selected_voiceprint_id"] = new_config["selected_voiceprint_id"]
        if "qwen_audio_voiceprint_audio_urls" in new_config:
            v_data["qwen_audio_voiceprint_audio_urls"] = new_config["qwen_audio_voiceprint_audio_urls"]
        if "qwen_audio_max_history_turns" in new_config:
            v_data["qwen_audio_max_history_turns"] = new_config["qwen_audio_max_history_turns"]


        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(v_data, f, indent=4, ensure_ascii=False)
        except Exception:
            pass

    # 5. 写回 TTS 引擎细粒度设置 (configs/models/tts/{tts}.json)
    tts_type = new_config.get("cascade_tts_type")
    if tts_type:
        safe_tts = _get_safe_filename(tts_type)
        p = models_dir / "tts" / f"{safe_tts}.json"
        t_data = {}
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    t_data = json.load(f)
            except Exception:
                pass
        t_data["value"] = tts_type
        t_data.setdefault("label", tts_type)
        if "local_tts_speaker_id" in new_config:
            t_data["current_speaker_id"] = new_config["local_tts_speaker_id"]
        if "local_tts_speed_rate" in new_config:
            t_data["speed_rate"] = new_config["local_tts_speed_rate"]
        if "cascade_silence_duration_ms" in new_config:
            t_data["silence_duration_ms"] = new_config["cascade_silence_duration_ms"]
        if "cascade_vad_energy_threshold" in new_config:
            t_data["vad_energy_threshold"] = new_config["cascade_vad_energy_threshold"]

        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(t_data, f, indent=4, ensure_ascii=False)
        except Exception:
            pass

    # 6. 写回 KWS 唤醒词与专属参数
    sherpa_dir = new_config.get("sherpa_model_dir")
    wake_word = new_config.get("wake_word")
    if sherpa_dir:
        safe_kws = _get_safe_filename(sherpa_dir)
        p = models_dir / "kws" / f"{safe_kws}.json"
        k_data = {}
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    k_data = json.load(f)
            except Exception:
                pass
        for key_name in ["kws_max_active_paths", "kws_num_trailing_blanks", "kws_score", "kws_threshold"]:
            if key_name in new_config:
                k_data[key_name] = new_config[key_name]
        if k_data:
            p.parent.mkdir(parents=True, exist_ok=True)
            try:
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(k_data, f, indent=4, ensure_ascii=False)
            except Exception:
                pass

        if wake_word:
            try:
                write_wake_word_to_model(sherpa_dir, wake_word)
            except Exception as e:
                print(f"[save_config_split] Failed to write wake_word to keywords.txt: {e}")

    return load_config()

def get_tool_calling_mode(channel: str, model_name: str) -> str:
    """
    Determine the tool calling mode (serial or parallel) based on config.
    channel: 'text' or 'voice'
    model_name: Name of the LLM model (kept for signature compatibility)
    """
    config = load_config()
    key = "text_model_tool_mode" if channel == "text" else "voice_model_tool_mode"
    mode = config.get(key)
    if mode in ["serial", "parallel"]:
        return mode
    return "serial"  # Default fallback is serial

def get_tool_calling_style(model_name: str) -> str:
    """
    Determine the tool calling style (native or router) based on config.
    model_name: Name of the LLM model (kept for signature compatibility)
    """
    config = load_config()
    style = config.get("text_model_tool_style")
    if style in ["native", "router"]:
        return style
    return "native"  # Default fallback is native

def normalize_tool_name(name: str) -> str:
    """Correct and normalize common tool name variations output by LLM."""
    if not name:
        return name
    name_lower = name.lower().strip()
    if name_lower in ["get_weather_forecast", "get_weather", "query_forecast", "weather", "weather_forecast", "query_weather", "check_weather_forecast", "check_weather"]:
        return "get_weather_forecast"
    if name_lower in ["show_screen_layer", "show_layer", "show_screen", "display_layer"]:
        return "show_screen_layer"
    if name_lower in ["query_emergency_knowledge", "query_knowledge", "emergency_knowledge", "query_emergency"]:
        return "query_emergency_knowledge"
    if name_lower in ["zoom_map", "zoom", "map_zoom"]:
        return "zoom_map"
    if name_lower in ["query_history_disasters", "query_disasters", "history_disasters", "get_history_disasters"]:
        return "query_history_disasters"
    return name


# ──────────────────────────────────────────────
# 通用唤醒词与会话挂断控制
# ──────────────────────────────────────────────
WAKE_WORDS = ["小安", "小安小安", "你好小安", "小安你好"]

def is_wake_word(text: str) -> bool:
    """判断转写文本去掉标点后是否仅仅是一个单句唤醒词"""
    if not text or not isinstance(text, str):
        return False
    # 剥离所有标点符号与非中英文界符
    clean_text = re.sub(r"[^\w\u4e00-\u9fa5]", "", text.strip())
    return clean_text in WAKE_WORDS

EXIT_KEYWORDS = [
    "退下", "退一下", "退下吧", "退吧", "去休息吧", "休息吧", 
    "退出", "挂断", "再见", "拜拜", "别说了", "闭嘴", "滚蛋", "先这样", "告辞"
]

def is_exit_intent(text: str) -> bool:
    """
    严谨判断转写文本是否为退出/挂断会话意图。
    防止气象/应急业务词（如“水退了”、“灾情消退”、“怎么退出界面”）被误识别为挂断。
    """
    if not text or not isinstance(text, str):
        return False

    clean_text = re.sub(r"[^\w\u4e00-\u9fa5]", "", text.strip())
    if not clean_text:
        return False

    # 1. 业务/询问排除关键词（出现这些词极大概率为询问业务、天气、灾情或界面操作，绝对不是挂断会话指令）
    EXCLUDE_KEYWORDS = [
        "怎么", "如何", "方法", "步骤", "按钮", "界面", "功能", "系统", "操作", "页面", "屏幕", "程序",
        "水", "雨", "灾情", "消退", "退去", "撤退", "后退", "退回", "退款", "退货", "退耕", "退化",
        "退潮", "减退", "衰退", "退缩", "退避", "退费", "退单", "退还", "退一步", "退后",
        "隐患", "避难所", "物资", "救援", "大屏", "图层", "雷达", "卫星", "地图", "积水", "内涝",
        "气象", "天气", "预警", "风力", "气温", "温度", "多少", "在哪", "是不是", "查询", "介绍",
        "说明", "解决", "处理", "情况", "程度"
    ]

    # 2. 强告别/退出核心短语
    STRICT_EXACT_EXIT_PHRASES = {
        "再见", "拜拜", "挂断", "退下", "退下吧", "退一下", "退一下吧", "退出去", "小安退下", "去休息吧", "小安去休息吧",
        "休息吧", "闭嘴", "滚蛋", "告辞", "先这样吧", "先这样", "不用说了", "不要说了",
        "退出", "退出吧", "小安退出", "退出对话", "结束对话", "关闭对话", "关闭会话", "退了吧",
        "挂断会话", "挂断电话", "结束通话"
    }

    # 完全精准匹配
    if clean_text in STRICT_EXACT_EXIT_PHRASES:
        return True

    # 检查排除词：如果包含排除词，直接否决
    for exc in EXCLUDE_KEYWORDS:
        if exc in clean_text:
            return False

    # 3. 常见无害前缀剥离
    prefix_pattern = r"^(小安|好的|行了|好了|那就|没事了|你可以|那|先|就)*"
    stripped = re.sub(prefix_pattern, "", clean_text)

    if stripped in STRICT_EXACT_EXIT_PHRASES:
        return True

    # 4. 句尾告别词（当文本较短 <= 12 字，且以严格告别词结尾）
    if len(clean_text) <= 12:
        for phrase in ["再见", "拜拜", "退下", "退下吧", "去休息吧", "闭嘴", "先这样吧"]:
            if clean_text.endswith(phrase):
                return True

    return False



async def send_session_hangup(
    websocket: Optional[WebSocket] = None,
    visual_broadcast_manager: Any = None,
    client: Optional[Any] = None,
    text: str = "再见",
    reason: str = "捕获到退出关键词，直接挂断会话"
) -> None:
    """
    通用底层挂断控制：
    1. 发送 hangup 信号触发前端气泡展示“再见”与播放 exit_female.wav
    2. 推送 debug_event 调试事件
    3. 将大屏广播状态切换至 idle
    4. 立即异步关闭底层模型的 WebSocket Client
    """
    if websocket:
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.send_json({"type": "state_change", "state": "idle"})
                await websocket.send_json({"type": "hangup", "text": text})
                await websocket.send_json({
                    "type": "debug_event",
                    "step": "intent",
                    "content": reason
                })
        except Exception as e:
            logger.warning(f"[SessionHangup] 发送 WebSocket 挂断消息失败: {e}")

    if visual_broadcast_manager:
        try:
            await visual_broadcast_manager.broadcast({"type": "subtitle", "text": text})
            await visual_broadcast_manager.broadcast({"type": "interrupted"})
            await visual_broadcast_manager.broadcast({"type": "state_change", "state": "idle"})
        except Exception as e:
            logger.warning(f"[SessionHangup] 广播退出状态失败: {e}")

    if client and hasattr(client, "close"):
        try:
            if asyncio.iscoroutinefunction(client.close):
                asyncio.create_task(client.close())
            else:
                client.close()
        except Exception as e:
            logger.warning(f"[SessionHangup] 关闭底层 Client 失败: {e}")



