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
                    # 发生异常通常代表上一轮连接在云端已经被自动结算断开了，这里尝试重新连接首帧发送
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
    优先采用天花板级“超拟人合成大模型 Spark-TTS”（使用聆小玥/聆飞逸），
    若鉴权失败或无权限（11200）则自动无缝降级回退到“通用流式 TTS”（使用叶子/春天明星拟真音色）以保证交互可用性。
    """
    # 步骤 1：判定当前是否尝试使用高级超拟人 Spark-TTS 接口 (x5_ 或 x6_ 系列发音人)
    use_spark_tts = vcn.startswith("x5_") or vcn.startswith("x6_")
    
    if use_spark_tts:
        # 高级超拟人 Spark-TTS（在线合成超拟人版）WebSocket 接口地址与请求构造
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
                    "vcn": vcn, # 直接传入如 x6_lingxiaoyue_pro 这样在控制台已授权的发音人代码
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
                
                # 发送当前播放的字幕信息给前端
                await websocket.send_json({"type": "output_transcript", "data": text})
                
                # 同时通知前端大屏进入 TTS 状态
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
                        logger.warn(f"[Xunfei-TTS] 检测到 APPID={app_id} 尚未在科大讯飞控制台开通高级“超拟人语音合成 (Spark-TTS)”服务。将自动为您降级为通用 TTS 口语化明星音色...")
                        # 广播通知前端当前音色处于降级模式，建议开通高级权限
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
                    return # 成功通过高级超拟人合成播放，直接退出
                    
        except Exception as e:
            logger.warn(f"[Xunfei-TTS] 尝试使用高级 Spark-TTS 异常: {e}，将自动切换到通用 TTS 兜底")

    # 步骤 2：降级回退到通用流式 TTS 接口
    fallback_vcn = vcn
    # 将无法授权的 x6_ 或 x5_ 顶级超拟人音色映射为有权限的普通超拟人明星音色
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
            
            # 发送当前播放的字幕与状态（如果刚才第一步没有发送成功的话）
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
                    logger.error(f"[Xunfei-TTS] 伪装超拟人合成报错 code={code}: {msg}")
                    try:
                        await websocket.send_json({"type": "error", "message": f"[Xunfei-TTS] 报错 code={code}: {msg}"})
                    except Exception:
                        pass
                    break
    except Exception as e:
        logger.error(f"[Xunfei-TTS] 伪装级联合成通信发生异常: {e}")
        try:
            await websocket.send_json({"type": "error", "message": f"[Xunfei-TTS] 异常: {e}"})
        except Exception:
            pass


async def handle_xunfei_realtime_session(
    websocket: WebSocket,
    voice: str,
    config: dict,
    run_chat_workflow_fn,
    visual_broadcast_manager
):
    """
    接管科大讯飞流式全双工中介会长连接的主循环
    """
    app_id = os.getenv("XUNFEI_APPID")
    api_key = os.getenv("XUNFEI_API_KEY")
    api_secret = os.getenv("XUNFEI_API_SECRET")
    
    if not app_id or not api_key or not api_secret:
        logger.error("[Xunfei-Voice] 缺少科大讯飞的环境变量 XUNFEI_APPID, XUNFEI_API_KEY, XUNFEI_API_SECRET")
        await websocket.close()
        return

    voice_speed = config.get("voice_speed", 50)
    print(f"\n\033[95m[Xunfei-Voice] ===== 科大讯飞流式级联会话已开启 =====\033[0m")
    print(f"\033[95m[Xunfei-Voice] 发音人: {voice}, 设定语速: {voice_speed}\033[0m")

    # 会话核心变量
    session_active = True
    chat_history = []
    
    # 打断与控制
    current_cancel_event = asyncio.Event()
    tts_playing = False

    # 初始化 ASR 客户端
    asr_client = XunfeiASRClient(app_id, api_key, api_secret)

    # 1. 当 ASR 识别到临时文字时，如果 AI 正在说话，判定用户进行“抢话打断”
    async def on_asr_text(text: str):
        nonlocal tts_playing
        if text.strip() and tts_playing:
            logger.info(f"[Xunfei-ASR] 检测到用户抢话(文字: '{text}')，立即打断并静音上一次播放！")
            current_cancel_event.set()
            # 广播打断消息通知前端清空缓冲区
            await websocket.send_json({"type": "interrupt"})

    async def on_asr_final(final_text: str):
        nonlocal current_cancel_event, tts_playing, session_active
        if not final_text.strip():
            return
            
        logger.info(f"[Xunfei-ASR] 本轮识别最终文本: '{final_text}'")

        # 优化退出指令识别，支持语音说：退下、去休息吧、退出等词汇
        exit_keywords = ["退下", "去休息吧", "退出", "挂断", "再见", "拜拜", "别说了", "闭嘴", "滚蛋"]
        if any(kw in final_text for kw in exit_keywords):
            logger.info(f"[Xunfei-ASR] 检测到退出指令 '{final_text}'，执行快速挂断")
            await websocket.send_json({"type": "hangup"})
            await visual_broadcast_manager.broadcast({"type": "interrupted"})
            await visual_broadcast_manager.broadcast({"type": "state_change", "state": "idle"})
            current_cancel_event.set()
            session_active = False
            return
            
        # 强制将上一轮取消（以防万一）
        current_cancel_event.set()
        
        # 重建取消信号
        current_cancel_event = asyncio.Event()
        
        # 启动异步处理大模型和 TTS 语音合成
        asyncio.create_task(process_brain_and_tts(final_text, current_cancel_event))

    asr_client.on_text_callback = on_asr_text
    asr_client.on_final_text_callback = on_asr_final

    # 大大脑和 TTS 合成循环
    async def process_brain_and_tts(final_text: str, cancel_event: asyncio.Event):
        nonlocal tts_playing
        tts_playing = True
        
        try:
            # 2.1 模拟将 ASR 结果发送给前端展现 STT
            await websocket.send_json({
                "type": "debug_event",
                "step": "stt",
                "content": final_text
            })
            
            # 记录历史
            chat_history.append({"role": "user", "content": final_text})
            
            # 分句合成的文本缓存
            sentence_buffer = ""
            ai_reply_text = ""
            punctuations = {"。", "？", "！", "；", ".", "?", "!", ";", "\n"}
            
            # 流式启动大模型决策生成
            async for line in run_chat_workflow_fn(final_text, chat_history):
                if cancel_event.is_set():
                    logger.info("[Xunfei-Brain] 收到取消信号，中止大语言脑流式吐字")
                    break
                    
                if not line.startswith("data: "):
                    continue
                try:
                    payload = json.loads(line.replace("data: ", "").strip())
                    
                    # 2.2 转发大模型脑的所有调试事件（包括 "intent" 语义意图分析事件！）
                    # 这能令大屏幕完美自动弹出“语义分析决定调用工具：...”调试框及对应的图层看板
                    if payload.get("type") == "debug_event":
                        await websocket.send_json(payload)
                        continue
                    elif payload.get("type") == "error":
                        logger.error(f"[Xunfei-Brain] 收到大模型脑子抛出错误: {payload.get('message')}")
                        await websocket.send_json(payload)
                        continue
                        
                    # 2.3 累积输出回答内容用于 TTS 分句流式合成
                    if payload.get("type") == "delta":
                        delta = payload.get("content", "")
                        sentence_buffer += delta
                        ai_reply_text += delta
                        await websocket.send_json({"type": "output_transcript", "data": ai_reply_text})
                        
                        # 检查句段分割
                        if delta in punctuations or any(sentence_buffer.endswith(p) for p in punctuations):
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
                except Exception as e:
                    logger.warn(f"[Xunfei-Brain] 解析流式响应帧失败: {e}")
            
            # 处理最后残留文本
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
            # 捕获断开连接和 ASGI send 异常并安全退避，不在控制台抛出 Traceback
            logger.info(f"[Xunfei-Brain] 会话应答中途连接已断开，大脑及 TTS 任务安全终止: {e}")
        except Exception as e:
            logger.error(f"[Xunfei-Brain] 决策大模型脑流程执行故障: {e}")
            try:
                await websocket.send_json({"type": "error", "message": f"[Xunfei-Brain] 故障: {e}"})
            except Exception:
                pass
        finally:
            tts_playing = False

    # 3. 实时从前端读取二进制麦克风流并喂送给 ASR 流进行识别
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
                    if payload.get("type") == "hangup":
                        logger.info("[Xunfei-Voice] 前端收到挂断请求")
                        break
                    elif payload.get("type") == "query" or payload.get("type") == "text_query":
                        text_content = payload.get("text", "")
                        if text_content:
                            logger.info(f"[Xunfei-Voice] 收到文本命令测试: {text_content}")
                            await on_asr_final(text_content)
                except Exception:
                    pass
    except WebSocketDisconnect:
        logger.info("[Xunfei-Voice] WebSocket 被前端断开")
    except Exception as e:
        logger.error(f"[Xunfei-Voice] 语音会话发生未知异常: {e}")
    finally:
        session_active = False
        current_cancel_event.set()
        await asr_client.finish()
        logger.info("[Xunfei-Voice] ===== 科大讯飞语音会话管道已关闭回收 =====")
