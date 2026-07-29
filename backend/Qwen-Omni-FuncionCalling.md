Qwen-Omni-Realtime 系列
Qwen3.5-Omni-Plus-Realtime、Qwen3.5-Omni-Flash-Realtime 系列支持工具调用，适用于语音对话场景。可通过 DashScope SDK或 WebSocket 原生协议调用。

工作流程：

建立 WebSocket 连接后，通过 session.update 传入工具定义，即可进入以下交互流程：

阶段一：语音输入与工具调用

用户发起语音提问，客户端采集音频并发送至服务端（对应 append_audio() 方法），服务端 VAD 检测语音结束后进行模型推理，判断需要调用工具。

服务端将工具调用信息返回给客户端（对应 response.function_call_arguments.done 事件），包含函数名（name）、函数入参（arguments）和调用标识（call_id），示例如下：

 
{
    "type": "response.function_call_arguments.done",
    "response_id": "resp_JnTOsWXlFhKcFohZbtfz6",
    "item_id": "item_Rhcms7CauTNsQprV5S4Hr",
    "output_index": 0,
    "name": "get_current_weather",
    "call_id": "call_2be200f4cafe419b9530dd",
    "arguments": "{\"location\": \"杭州\"}"
}
客户端根据函数名和入参，在本地执行对应的工具函数，获得执行结果。

阶段二：客户端回传工具结果并触发最终响应

客户端将工具执行结果发回服务端（对应 conversation.item.create 事件），包含调用标识（call_id）和执行结果（output），示例如下：

 
{
    "type": "conversation.item.create",
    "item": {
        "type": "function_call_output",
        "call_id": "call_2be200f4cafe419b9530dd",
        "output": "杭州今天天气为晴，气温25℃，微风"
    }
}
客户端继续发送 response.create 事件，触发服务端基于工具执行结果生成最终语音回答。

客户端接收服务端返回的语音和文本（对应 response.audio.delta 和 response.audio_transcript.delta 事件），播放语音回复给用户。

Qwen-Omni-Realtime 系列不支持 tool_choice 和 parallel_tool_calls 参数。
千问Omni-Realtime详情请参见： 实时（Qwen-Omni-Realtime） 、 客户端事件 、 服务端事件 。
DashScope Python SDKDashScope Java SDKWebSocket(Python)
 
# DashScope Python SDK v1.25.17
import os
import uuid
import threading
import traceback
import json
import base64
import signal
import sys
import time
from typing import Dict, Any, Optional, List
import pyaudio
import queue
import contextlib
import dashscope
from dashscope.audio.qwen_omni import *

# ==================== 常量定义 ====================
VOICE = 'Tina'
MODEL = "qwen3.5-omni-plus-realtime"
# 如果需要访问新加坡地域，请WS_URL将替换为：wss://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/api-ws/v1/realtime
WS_URL = "wss://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime"
# 配置 API Key，若没有设置环境变量，请用 API Key 将下行替换为 dashscope.api_key = "sk-xxx"
dashscope.api_key = os.getenv('DASHSCOPE_API_KEY')
AUDIO_SAMPLE_RATE = 16000
AUDIO_CHUNK_SIZE = 3200
OUTPUT_AUDIO_SAMPLE_RATE = 24000

# ==================== 工具定义 ====================
def get_train_price(src: str, dst: str) -> str:
    """查询火车票价格"""
    return f"{src}到{dst}的火车票价格为100~200元。"

def get_flight_price(src: str, dst: str) -> str:
    """查询飞机票价格"""
    return f"{src}到{dst}的机票价格为200~300美元。"

def get_current_weather(location: str) -> str:
    """查询指定城市天气"""
    return f"{location}今天天气为霾转晴，气温4/-4℃，微风"

# 统一的 OpenAI 格式工具定义
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_weather",
            "description": "当你想查询指定城市的天气时非常有用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "城市或县区，比如北京市、杭州市、余杭区等。",
                    }
                },
                "required": ["location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_flight_price",
            "description": "当你想查询飞机票价格时非常有用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "src": {
                        "type": "string",
                        "description": "飞机起飞的城市，比如北京市、杭州市等。",
                    },
                    "dst": {
                        "type": "string",
                        "description": "飞机降落的城市，比如北京市、杭州市区等。",
                    },
                },
                "required": ["src", "dst"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_train_price",
            "description": "当你想查询火车票价格时非常有用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "src": {
                        "type": "string",
                        "description": "火车出发的城市，比如北京市、杭州市等。",
                    },
                    "dst": {
                        "type": "string",
                        "description": "火车到达的城市，比如北京市、杭州市区等。",
                    },
                },
                "required": ["src", "dst"],
            },
        },
    },
]

# 工具名称到函数的映射
TOOL_FUNCTIONS = {
    "get_current_weather": get_current_weather,
    "get_flight_price": get_flight_price,
    "get_train_price": get_train_price,
}

# ==================== 工具调用处理 ====================
def handle_tool_call(tool_call_response: Dict[str, Any]) -> Dict[str, Any]:
    """
    处理工具调用请求

    Args:
        tool_call_response: 包含 name, arguments, call_id 的工具调用信息

    Returns:
        更新后的工具调用响应，包含 output 字段
    """
    try:
        function_name = tool_call_response['name']
        tool_call_arguments = json.loads(tool_call_response['arguments'])

        print(f'[Tool Call] 开始处理: name={function_name}, args={tool_call_arguments}')

        # 查找对应的函数
        if function_name not in TOOL_FUNCTIONS:
            tool_call_response['output'] = f"客户端未找到工具: {function_name}"
            print(f'[Tool Call] 错误: 未找到工具 {function_name}')
            return tool_call_response

        # 调用函数
        func = TOOL_FUNCTIONS[function_name]
        result = func(**tool_call_arguments)
        tool_call_response['output'] = result

        print(f'[Tool Call] 完成: {result}')
        return tool_call_response

    except Exception as e:
        error_msg = f"工具调用失败: {str(e)}"
        tool_call_response['output'] = error_msg
        print(f'[Tool Call] 异常: {error_msg}')
        traceback.print_exc()
        return tool_call_response

def send_tool_call_response(conversation: OmniRealtimeConversation, response: Dict[str, Any]) -> None:
    """发送工具调用结果到服务端"""
    conversation.create_item({
        "id": 'item_' + uuid.uuid4().hex,
        "type": "function_call_output",
        "call_id": response['call_id'],
        "output": response["output"],
    })

# ==================== PCM 音频播放器 ====================
class PCMPlayer:
    """
    PCM 音频播放器

    使用双线程架构实现实时音频播放：
    - 解码线程：将 base64 编码的音频数据解码为原始 PCM 数据
    - 播放线程：将 PCM 数据写入音频输出设备

    支持动态添加音频数据、取消播放、保存音频文件等功能。
    """

    def __init__(self, pya: pyaudio.PyAudio, sample_rate=24000, chunk_size_ms=100, save_file=False):
        """
        初始化 PCM 播放器

        Args:
            pya: pyaudio.PyAudio 实例
            sample_rate: 音频采样率（Hz），默认 24000
            chunk_size_ms: 音频块大小（毫秒），影响取消播放的延迟，默认 100ms
            save_file: 是否保存播放的音频到文件（result.pcm），默认 False
        """

        self.pya = pya
        self.sample_rate = sample_rate
        self.chunk_size_bytes = chunk_size_ms * sample_rate * 2 // 1000
        self.player_stream = pya.open(format=pyaudio.paInt16,
                                       channels=1,
                                       rate=sample_rate,
                                       output=True)

        self.raw_audio_buffer: queue.Queue = queue.Queue()
        self.b64_audio_buffer: queue.Queue = queue.Queue()
        self.status_lock = threading.Lock()
        self.status = 'playing'
        self.decoder_thread = threading.Thread(target=self.decoder_loop)
        self.player_thread = threading.Thread(target=self.player_loop)
        self.decoder_thread.start()
        self.player_thread.start()
        self.complete_event: threading.Event = None
        self.save_file = save_file
        if self.save_file:
            self.out_file = open('result.pcm', 'wb')

    def decoder_loop(self):
        """解码线程：将 base64 音频数据解码为 PCM 原始数据"""
        while self.status != 'stop':
            recv_audio_b64 = None
            with contextlib.suppress(queue.Empty):
                recv_audio_b64 = self.b64_audio_buffer.get(timeout=0.1)
            if recv_audio_b64 is None:
                continue
            recv_audio_raw = base64.b64decode(recv_audio_b64)
            # push raw audio data into queue by chunk
            for i in range(0, len(recv_audio_raw), self.chunk_size_bytes):
                chunk = recv_audio_raw[i:i + self.chunk_size_bytes]
                self.raw_audio_buffer.put(chunk)
                if self.save_file:
                    self.out_file.write(chunk)

    def player_loop(self):
        """播放线程：将 PCM 数据写入音频输出设备"""
        while self.status != 'stop':
            recv_audio_raw = None
            with contextlib.suppress(queue.Empty):
                recv_audio_raw = self.raw_audio_buffer.get(timeout=0.1)
            if recv_audio_raw is None:
                if self.complete_event:
                    self.complete_event.set()
                continue
            # write chunk to pyaudio audio player, wait until finish playing this chunk.
            self.player_stream.write(recv_audio_raw)

    def cancel_playing(self):
        """取消播放：清空所有缓冲队列"""
        self.b64_audio_buffer.queue.clear()
        self.raw_audio_buffer.queue.clear()

    def add_data(self, data):
        """添加 base64 编码的音频数据到播放队列"""
        self.b64_audio_buffer.put(data)

    def wait_for_complete(self):
        """等待播放完成"""
        self.complete_event = threading.Event()
        self.complete_event.wait()
        self.complete_event = None

    def shutdown(self):
        """关闭播放器并释放资源"""
        self.status = 'stop'
        self.decoder_thread.join()
        self.player_thread.join()
        self.player_stream.close()
        if self.save_file:
            self.out_file.close()

# ==================== 音频管理器 ====================
class AudioManager:
    """管理音频输入输出资源"""

    def __init__(self):
        self.pya: Optional[pyaudio.PyAudio] = None
        self.mic_stream: Optional[pyaudio.Stream] = None
        self.player: Optional[PCMPlayer] = None

    def initialize(self) -> None:
        """初始化音频设备"""
        print('初始化音频设备...')
        self.pya = pyaudio.PyAudio()
        self.mic_stream = self.pya.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=AUDIO_SAMPLE_RATE,
            input=True
        )
        self.player = PCMPlayer(self.pya, sample_rate=OUTPUT_AUDIO_SAMPLE_RATE)
        print('音频设备初始化完成')

    def read_audio_chunk(self) -> Optional[bytes]:
        """读取音频数据块"""
        if not self.mic_stream:
            return None
        try:
            return self.mic_stream.read(AUDIO_CHUNK_SIZE, exception_on_overflow=False)
        except Exception as e:
            print(f'[Error] 读取音频数据失败: {e}')
            return None

    def cleanup(self) -> None:
        """清理音频资源"""
        print('清理音频资源...')
        if self.player:
            self.player.shutdown()
        if self.mic_stream:
            self.mic_stream.close()
        if self.pya:
            self.pya.terminate()
        print('音频资源清理完成')

# ==================== 回调处理器 ====================
class OmniCallback(OmniRealtimeCallback):
    """Omni 实时对话回调处理器"""

    def __init__(self, audio_manager: AudioManager):
        self.audio_manager = audio_manager
        self.tool_calls: Dict[str, Dict[str, Any]] = {}
        self.all_response_text: str = ''
        self.last_package_time: float = 0
        self.is_first_text: bool = True
        self.is_first_audio: bool = True
        self.conversation: Optional[OmniRealtimeConversation] = None

    def set_conversation(self, conversation: OmniRealtimeConversation) -> None:
        """设置对话实例引用"""
        self.conversation = conversation

    def on_open(self) -> None:
        """连接建立时的回调"""
        print('连接已建立')
        self.audio_manager.initialize()
        self.last_package_time = time.time() * 1000
        self.is_first_text = True
        self.is_first_audio = True
        self.tool_calls = {}
        self.all_response_text = ''

    def on_close(self, close_status_code: int, close_msg: str) -> None:
        """连接关闭时的回调"""
        print(f'连接已关闭: code={close_status_code}, msg={close_msg}')
        self.audio_manager.cleanup()
        sys.exit(0)

    def on_event(self, response: Dict[str, Any]) -> None:
        """处理事件回调"""
        try:
            event_type = response.get('type', '')

            # 会话创建
            if event_type == 'session.created':
                print(f'会话已启动: {response["session"]["id"]}')

            # 语音转文本完成
            elif event_type == 'conversation.item.input_audio_transcription.completed':
                print(f'用户问题: {response.get("transcript", "")}')

            # 文本增量响应
            elif event_type in ('response.audio_transcript.delta', 'response.text.delta'):
                if self.is_first_text:
                    self.is_first_text = False
                    latency = time.time() * 1000 - self.last_package_time
                    print(f'首字延迟 (VAD结束): {latency:.0f} ms')

                text = response.get('delta', '')
                self.all_response_text += text

            # 音频增量响应
            elif event_type == 'response.audio.delta':
                if self.is_first_audio:
                    self.is_first_audio = False
                    latency = time.time() * 1000 - self.last_package_time
                    print(f'首音延迟 (VAD结束): {latency:.0f} ms')

                audio_interval = time.time() * 1000 - self.last_package_time
                print(f'音频间隔: {audio_interval:.0f} ms')
                self.last_package_time = time.time() * 1000

                recv_audio_b64 = response.get('delta', '')
                if self.audio_manager.player:
                    self.audio_manager.player.add_data(recv_audio_b64)

            # VAD 检测到语音开始
            elif event_type == 'input_audio_buffer.speech_started':
                print('====== VAD 检测到语音开始 ======')
                if self.audio_manager.player:
                    self.audio_manager.player.cancel_playing()

            # VAD 检测到语音结束
            elif event_type == 'input_audio_buffer.speech_stopped':
                print('====== VAD 检测到语音结束 ======')
                self.last_package_time = time.time() * 1000
                self.is_first_text = True
                self.is_first_audio = True
                self.tool_calls = {}

            # 函数调用参数完成
            elif event_type == 'response.function_call_arguments.done':
                print('====== 收到工具调用请求 ======')
                call_id = response.get('call_id', '')
                self.tool_calls[call_id] = response.copy()
                self.tool_calls[call_id]['processed'] = False

            # 响应完成
            elif event_type == 'response.done':
                print('====== 响应完成 ======')
                print(f'完整回复: {self.all_response_text}')

                if self.conversation:
                    response_id = self.conversation.get_last_response_id()
                    text_delay = self.conversation.get_last_first_text_delay()
                    audio_delay = self.conversation.get_last_first_audio_delay()

                    # 只有当所有指标都可用时才打印详细指标
                    if response_id is not None and text_delay is not None and audio_delay is not None:
                        print(f'[Metric] 响应ID: {response_id}, '
                              f'首字延迟: {text_delay:.0f}ms, '
                              f'首音延迟: {audio_delay:.0f}ms')
                    else:
                        print('[Metric] 指标信息暂不可用（可能是工具调用后的响应）')

                self.all_response_text = ''

        except Exception as e:
            print(f'[Error] 处理事件异常: {e}')
            traceback.print_exc()

    def process_pending_tool_calls(self) -> bool:
        """
        处理待处理的工具调用

        Returns:
            是否有新的工具调用需要响应
        """
        has_pending = False

        for call_id, tool_call in self.tool_calls.items():
            if not tool_call.get('processed', False):
                has_pending = True
                tool_call['processed'] = True

                # 处理工具调用
                result = handle_tool_call(tool_call)

                # 发送结果到服务端
                if self.conversation:
                    send_tool_call_response(self.conversation, result)

        return has_pending

# ==================== 主程序 ====================
def main():
    """主函数"""
    print('正在初始化 Omni 实时对话...')

    # 创建音频管理器
    audio_manager = AudioManager()

    # 创建回调处理器
    callback = OmniCallback(audio_manager)

    # 创建对话实例
    conversation = OmniRealtimeConversation(
        api_key=dashscope.api_key,
        url=WS_URL,
        model=MODEL,
        callback=callback,
    )

    # 设置回调中的对话引用
    callback.set_conversation(conversation)

    # 建立连接
    conversation.connect()

    # 配置会话参数
    omni_output_modalities = [MultiModality.AUDIO, MultiModality.TEXT]

    conversation.update_session(
        output_modalities=omni_output_modalities,
        voice=VOICE,
        input_audio_format=AudioFormat.PCM_16000HZ_MONO_16BIT,
        output_audio_format=AudioFormat.PCM_24000HZ_MONO_16BIT,
        enable_input_audio_transcription=True,
        enable_turn_detection=True,
        turn_detection_type='server_vad',
        tools=TOOLS,
    )

    # 设置信号处理
    def signal_handler(sig, frame):
        print('\n接收到 Ctrl+C，正在停止...')
        conversation.close()
        audio_manager.cleanup()
        print('Omni 实时对话已停止')
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    print("按 Ctrl+C 停止对话...\n")

    # 主循环：持续发送音频并检查工具调用
    try:
        while True:
            # 处理待处理的工具调用
            has_tool_calls = callback.process_pending_tool_calls()

            if has_tool_calls:
                print("*** 工具调用完成，创建新响应 ***")
                conversation.create_response(
                    instructions=None,
                    output_modalities=omni_output_modalities
                )
                print('====== 工具调用处理完成 ======\n')

            # 读取并发送音频数据
            audio_data = audio_manager.read_audio_chunk()
            if audio_data:
                audio_b64 = base64.b64encode(audio_data).decode('ascii')
                conversation.append_audio(audio_b64)
            else:
                break

    except KeyboardInterrupt:
        signal_handler(signal.SIGINT, None)
    except Exception as e:
        print(f'[Error] 主循环异常: {e}')
        traceback.print_exc()
    finally:
        conversation.close()
        audio_manager.cleanup()

if __name__ == '__main__':
    main()