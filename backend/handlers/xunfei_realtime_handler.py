import os
import json
import base64
import hmac
import hashlib
import asyncio
import logging
import urllib.parse
from datetime import datetime
from wsgiref.handlers import format_date_time
from time import mktime
import websockets
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("xiaoan.xunfei_realtime")
from utils import is_exit_intent
from handlers.openai_chat_handler import OpenAIChatHandler

_chat_handler = None

def get_shared_chat_handler() -> OpenAIChatHandler:
    global _chat_handler
    if _chat_handler is None:
        _chat_handler = OpenAIChatHandler()
    return _chat_handler


class XunfeiResultParser:
    """
    解析科大讯飞语音听写的 PGS 动态修正文本结果
    """
    def __init__(self):
        self.results = {}  # {sn: text}

    def parse(self, result_dict: dict) -> str:
        sn = result_dict.get("sn")
        pgs = result_dict.get("pgs")
        rg = result_dict.get("rg")
        
        # 提取当前帧的文本
        text = ""
        ws_list = result_dict.get("ws", [])
        for ws in ws_list:
            cw_list = ws.get("cw", [])
            for cw in cw_list:
                text += cw.get("w", "")
        
        if pgs == "apd":
            self.results[sn] = text
        elif pgs == "rpl":
            if rg:
                start, end = rg
                # 删除范围内的原有 sn 记录
                for k in list(self.results.keys()):
                    if start <= k <= end:
                        self.results.pop(k, None)
            self.results[sn] = text
        else:
            if sn is not None:
                self.results[sn] = text
            
        # 按 sn 顺序拼接出完整的听写文本
        sorted_keys = sorted(self.results.keys())
        full_text = "".join(self.results[k] for k in sorted_keys)
        return full_text

    def clear(self):
        self.results.clear()


def assemble_auth_url(request_url: str, api_key: str, api_secret: str, method: str = "GET") -> str:
    """
    根据科大讯飞规范生成带签名的握手 WebSocket URL
    """
    u = urllib.parse.urlparse(request_url)
    host = u.hostname
    path = u.path

    # 获取当前 RFC1123 格式 of GMT 时间戳
    now = datetime.now()
    date = format_date_time(mktime(now.timetuple()))

    # 拼接签名原串
    signature_origin = f"host: {host}\ndate: {date}\n{method} {path} HTTP/1.1"

    # 使用 HMAC-SHA256 计算签名
    signature_sha = hmac.new(
        api_secret.encode('utf-8'),
        signature_origin.encode('utf-8'),
        digestmod=hashlib.sha256
    ).digest()
    
    signature_sha_base64 = base64.b64encode(signature_sha).decode('utf-8')

    # 组装 authorization 参数
    authorization_origin = f'api_key="{api_key}", algorithm="hmac-sha256", headers="host date request-line", signature="{signature_sha_base64}"'
    authorization = base64.b64encode(authorization_origin.encode('utf-8')).decode('utf-8')

    # 将参数放入 URL Query 中
    v = {
        "authorization": authorization,
        "date": date,
        "host": host
    }
    url = request_url + '?' + urllib.parse.urlencode(v)
    return url


class XunfeiASRClient:
    """
    封装科大讯飞流式 ASR WebSocket 客户端，实现自动握手、静音 VAD 自动结算和动态回调
    """
    def __init__(self, app_id: str, api_key: str, api_secret: str):
        self.app_id = app_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.ws = None
        self.status = 0  # 0: 准备发送首帧, 1: 发送中间帧
        self.parser = XunfeiResultParser()
        self.on_text_callback = None
        self.on_final_text_callback = None
        self.lock = asyncio.Lock()

    async def connect_and_send_first(self, pcm_data: bytes):
        try:
            url = assemble_auth_url("wss://iat-api.xfyun.cn/v2/iat", self.api_key, self.api_secret)
            self.ws = await websockets.connect(url)
            self.status = 1
            self.parser.clear()
            
            # 构造第一帧
            first_frame = {
                "common": { "app_id": self.app_id },
                "business": {
                    "language": "zh_cn",
                    "domain": "iat",
                    "accent": "mandarin",
                    "dwa": "wpgs",
                    "vad_eos": 1500  # 1.5秒静音自动结算断句
                },
                "data": {
                    "status": 0,
                    "format": "audio/L16;rate=16000",
                    "encoding": "raw",
                    "audio": base64.b64encode(pcm_data).decode("utf-8")
                }
            }
            await self.ws.send(json.dumps(first_frame))
            # 开启异步接收
            asyncio.create_task(self.receive_loop())
        except Exception as e:
            logger.error(f"[Xunfei-ASR] 初始化握手失败: {e}")
            self.ws = None
            self.status = 0

    async def send_audio(self, pcm_data: bytes):
        async with self.lock:
            if self.ws is None:
                await self.connect_and_send_first(pcm_data)
            else:
                frame = {
                    "data": {
                        "status": 1,
                        "format": "audio/L16;rate=16000",
                        "encoding": "raw",
                        "audio": base64.b64encode(pcm_data).decode("utf-8")
                    }
                }
                try:
                    await self.ws.send(json.dumps(frame))
                except Exception:
                    await self.connect_and_send_first(pcm_data)

    async def finish(self):
        async with self.lock:
            if self.ws and self.status == 1:
                frame = {
                    "data": {
                        "status": 2,
                        "format": "audio/L16;rate=16000",
                        "encoding": "raw",
                        "audio": ""
                    }
                }
                try:
                    await self.ws.send(json.dumps(frame))
                except Exception:
                    pass
                self.ws = None
                self.status = 0

    async def receive_loop(self):
        ws_to_receive = self.ws
        try:
            async for message in ws_to_receive:
                resp = json.loads(message)
                code = resp.get("code")
                if code == 0:
                    data = resp.get("data", {})
                    result = data.get("result")
                    status = data.get("status")
                    if result:
                        text = self.parser.parse(result)
                        if self.on_text_callback:
                            await self.on_text_callback(text)
                    if status == 2:
                        final_text = self.parser.parse({})
                        if self.on_final_text_callback:
                            await self.on_final_text_callback(final_text)
                        break
                else:
                    logger.error(f"[Xunfei-ASR] 云端结算异常 code={code}: {resp.get('desc')}")
                    break
        except Exception as e:
            logger.error(f"[Xunfei-ASR] 接收听写帧发生异常: {e}")
        finally:
            self.status = 0
            if self.ws == ws_to_receive:
                self.ws = None


async def synthesize_text_stream(
    text: str,
    vcn: str,
    app_id: str,
    api_key: str,
    api_secret: str,
    websocket: WebSocket,
    cancel_event: asyncio.Event,
    speed: int = 50
):
    """
    流式向科大讯飞发送文本进行语音合成。
    """
    use_spark_tts = vcn.startswith("x5_") or vcn.startswith("x6_")
    
    if use_spark_tts:
        url = assemble_auth_url("wss://cbm01.cn-huabei-1.xf-yun.com/v1/private/mcd9m97e6", api_key, api_secret)
        text_b64 = base64.b64encode(text.encode("utf-8")).decode("utf-8")
        
        request_data = {
            "header": {
                "app_id": app_id,
                "status": 2
            },
            "parameter": {
                "oral": {
                    "oral_level": "mid"
                },
                "tts": {
                    "vcn": vcn,
                    "speed": speed,
                    "volume": 60,
                    "pitch": 50,
                    "audio": {
                        "encoding": "raw",
                        "sample_rate": 16000,
                        "channels": 1,
                        "bit_depth": 16,
                        "frame_size": 0
                    }
                }
            },
            "payload": {
                "text": {
                    "encoding": "utf8",
                    "compress": "raw",
                    "format": "plain",
                    "status": 2,
                    "seq": 0,
                    "text": text_b64
                }
            }
        }
        
        try:
            async with websockets.connect(url) as ws:
                await ws.send(json.dumps(request_data))
                await websocket.send_json({"type": "output_transcript", "data": text})
                await websocket.send_json({
                    "type": "debug_event",
                    "step": "tts",
                    "content": text
                })
                
                auth_ok = True
                async for message in ws:
                    if cancel_event.is_set():
                        break
                    
                    resp = json.loads(message)
                    code = resp.get("code")
                    if code is None:
                        code = resp.get("header", {}).get("code", 0)
                    
                    if code == 11200:
                        logger.warn(f"[Xunfei-TTS] 检测到 APPID={app_id} 尚未开通高级 Spark-TTS。降级为通用音色...")
                        await websocket.send_json({
                            "type": "debug_event",
                            "step": "tts",
                            "content": "[Warning] 高级超拟人未开通(11200)，系统已降级为通用超拟人音色播放"
                        })
                        auth_ok = False
                        break
                    elif code == 0:
                        data = resp.get("data")
                        if data is None:
                            data = resp.get("payload", {}).get("audio", {})
                        
                        audio_b64 = data.get("audio")
                        status = data.get("status")
                        if audio_b64:
                            pcm_bytes = base64.b64decode(audio_b64)
                            await websocket.send_bytes(pcm_bytes)
                        if status == 2:
                            break
                    else:
                        msg = resp.get("message") or resp.get("header", {}).get("message", "")
                        logger.error(f"[Xunfei-TTS] Spark-TTS 报错 code={code}: {msg}")
                        auth_ok = False
                        break
                
                if auth_ok:
                    return
                    
        except Exception as e:
            logger.warn(f"[Xunfei-TTS] 尝试 Spark-TTS 异常: {e}，自动切换到通用 TTS 兜底")

    fallback_vcn = vcn
    if "xiaoyue" in vcn or "xiaoxuan" in vcn:
        fallback_vcn = "x4_yezi_oral"
    elif "feiyi" in vcn or "feizhe" in vcn:
        fallback_vcn = "x4_chuntian_oral"
        
    url = assemble_auth_url("wss://tts-api.xfyun.cn/v2/tts", api_key, api_secret)
    text_b64 = base64.b64encode(text.encode("utf-8")).decode("utf-8")
    
    request_data = {
        "common": {
            "app_id": app_id
        },
        "business": {
            "aue": "raw",
            "auf": "audio/L16;rate=16000",
            "vcn": fallback_vcn,
            "speed": speed,
            "volume": 60,
            "pitch": 50,
            "tte": "UTF8"
        },
        "data": {
            "status": 2,
            "text": text_b64
        }
    }
    
    try:
        async with websockets.connect(url) as ws:
            await ws.send(json.dumps(request_data))
            await websocket.send_json({"type": "output_transcript", "data": text})
            await websocket.send_json({
                "type": "debug_event",
                "step": "tts",
                "content": text
            })
            
            async for message in ws:
                if cancel_event.is_set():
                    break
                    
                resp = json.loads(message)
                code = resp.get("code", 0)
                
                if code == 0:
                    data = resp.get("data", {})
                    audio_b64 = data.get("audio")
                    status = data.get("status")
                    if audio_b64:
                        pcm_bytes = base64.b64decode(audio_b64)
                        await websocket.send_bytes(pcm_bytes)
                    if status == 2:
                        break
                else:
                    msg = resp.get("message") or resp.get("header", {}).get("message", "")
                    logger.error(f"[Xunfei-TTS] 合成报错 code={code}: {msg}")
                    try:
                        await websocket.send_json({"type": "error", "message": f"[Xunfei-TTS] 报错 code={code}: {msg}"})
                    except Exception:
                        pass
                    break
    except Exception as e:
        logger.error(f"[Xunfei-TTS] 合成通信故障: {e}")
        try:
            await websocket.send_json({"type": "error", "message": f"[Xunfei-TTS] 异常: {e}"})
        except Exception:
            pass


async def handle_xunfei_realtime_session(
    websocket: WebSocket,
    voice: str,
    config: dict,
    visual_broadcast_manager: Any
):
    """
    接管科大讯飞流式全双工中介会长连接的主循环
    """
    app_id = os.getenv("XUNFEI_APPID")
    api_key = os.getenv("XUNFEI_API_KEY")
    api_secret = os.getenv("XUNFEI_API_SECRET")
    default_city = config.get("default_city", "")
    
    if not app_id or not api_key or not api_secret:
        logger.error("[Xunfei-Voice] 缺少科大讯飞的环境变量 XUNFEI_APPID, XUNFEI_API_KEY, XUNFEI_API_SECRET")
        await websocket.close()
        return

    voice_speed = config.get("voice_speed", 50)
    print(f"\n\033[95m[Xunfei-Voice] ===== 科大讯飞流式级联会话已开启 =====\033[0m")
    print(f"\033[95m[Xunfei-Voice] 发音人: {voice}, 设定语速: {voice_speed}\033[0m")

    session_active = True
    chat_history = []
    current_cancel_event = asyncio.Event()
    tts_playing = False

    asr_client = XunfeiASRClient(app_id, api_key, api_secret)

    async def on_asr_text(text: str):
        nonlocal tts_playing
        if text.strip() and tts_playing:
            logger.info(f"[Xunfei-ASR] 检测到用户抢话(文字: '{text}')，立即打断！")
            current_cancel_event.set()
            await websocket.send_json({"type": "interrupt"})

    async def on_asr_final(final_text: str):
        nonlocal current_cancel_event, tts_playing, session_active
        if not final_text.strip():
            return
            
        logger.info(f"[Xunfei-ASR] 本轮识别最终文本: '{final_text}'")

        if is_exit_intent(final_text):
            logger.info(f"[Xunfei-ASR] 检测到退出指令 '{final_text}'，挂断")
            await websocket.send_json({"type": "hangup"})
            await visual_broadcast_manager.broadcast({"type": "interrupted"})
            await visual_broadcast_manager.broadcast({"type": "state_change", "state": "idle"})
            current_cancel_event.set()
            session_active = False
            return
            
        current_cancel_event.set()
        current_cancel_event = asyncio.Event()
        asyncio.create_task(process_brain_and_tts(final_text, current_cancel_event))

    asr_client.on_text_callback = on_asr_text
    asr_client.on_final_text_callback = on_asr_final

    async def process_brain_and_tts(final_text: str, cancel_event: asyncio.Event):
        nonlocal tts_playing
        tts_playing = True
        
        try:
            await websocket.send_json({
                "type": "debug_event",
                "step": "stt",
                "content": final_text
            })
            
            chat_history.append({"role": "user", "content": final_text})
            sentence_buffer = ""
            ai_reply_text = ""
            punctuations = {"。", "？", "！", "；", ".", "?", "!", ";", "\n"}
            chat_handler = get_shared_chat_handler()
            
            async for token in chat_handler.stream_project_text_chat(message=final_text, history=chat_history, city=default_city):
                if cancel_event.is_set():
                    logger.info("[Xunfei-Brain] 收到取消信号，中止大流式吐字")
                    break
                    
                sentence_buffer += token
                ai_reply_text += token
                await websocket.send_json({"type": "output_transcript", "data": ai_reply_text})
                
                if any(p in sentence_buffer for p in punctuations):
                    clean_sentence = sentence_buffer.strip()
                    if clean_sentence:
                        await synthesize_text_stream(
                            text=clean_sentence,
                            vcn=voice,
                            app_id=app_id,
                            api_key=api_key,
                            api_secret=api_secret,
                            websocket=websocket,
                            cancel_event=cancel_event,
                            speed=voice_speed
                        )
                    sentence_buffer = ""
            
            if not cancel_event.is_set() and sentence_buffer.strip():
                await synthesize_text_stream(
                    text=sentence_buffer.strip(),
                    vcn=voice,
                    app_id=app_id,
                    api_key=api_key,
                    api_secret=api_secret,
                    websocket=websocket,
                    cancel_event=cancel_event,
                    speed=voice_speed
                )
            if not cancel_event.is_set():
                await websocket.send_json({"type": "output_transcript_done"})
        except (WebSocketDisconnect, RuntimeError) as e:
            logger.info(f"[Xunfei-Brain] 会话应答中途连接切断: {e}")
        except Exception as e:
            logger.error(f"[Xunfei-Brain] 决策大模型执行故障: {e}")
            try:
                await websocket.send_json({"type": "error", "message": f"[Xunfei-Brain] 故障: {e}"})
            except Exception:
                pass
        finally:
            tts_playing = False

    try:
        while session_active:
            message = await websocket.receive()
            if "bytes" in message:
                data = message["bytes"]
                if len(data) > 1 and data[0] == 0x00:
                    pcm_bytes = data[1:]
                    await asr_client.send_audio(pcm_bytes)
            elif "text" in message:
                text_msg = message["text"]
                try:
                    payload = json.loads(text_msg)
                    if payload.get("type") == "interrupt":
                        logger.info("⚡ [Xunfei-Voice] 收到前端打断指令")
                        current_cancel_event.set()
                        await visual_broadcast_manager.broadcast({"type": "state_change", "state": "listening"})
                        await websocket.send_json({"type": "state_change", "state": "listening"})
                        await websocket.send_json({"type": "interrupt"})
                    elif payload.get("type") == "hangup":
                        logger.info("[Xunfei-Voice] 前端挂断请求")
                        break
                    elif payload.get("type") == "query" or payload.get("type") == "text_query":
                        text_content = payload.get("text", "")
                        if text_content:
                            logger.info(f"[Xunfei-Voice] 收到文本测试命令: {text_content}")
                            await on_asr_final(text_content)
                except Exception:
                    pass
    except WebSocketDisconnect:
        logger.info("[Xunfei-Voice] WebSocket 被前端断开")
    except Exception as e:
        logger.error(f"[Xunfei-Voice] 语音会话未知异常: {e}")
    finally:
        session_active = False
        current_cancel_event.set()
        await asr_client.finish()
        logger.info("[VoiceEngine] ===== 语音会话管道已关闭回收 =====")
