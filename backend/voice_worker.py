import asyncio
import os
import sys
import subprocess
import shutil
from pathlib import Path

from livekit.agents import AutoSubscribe, JobContext, JobProcess, WorkerOptions, cli, llm
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import openai

import logging
file_handler = logging.FileHandler("worker_terminal.log")
file_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
logging.getLogger().addHandler(file_handler)
logging.getLogger().setLevel(logging.DEBUG)

# Resolve the script path for spd-weather, identical to what was done in weather_router.py
_SCRIPT = (
    Path(__file__).parent.parent / "spd-weather" / "scripts" / "spd_weather.py"
).resolve()
_UV = shutil.which("uv") or "uv.exe"

def run_weather_script(city: str) -> str:
    if not _SCRIPT.exists():
        return f"spd_weather.py 未找到: {_SCRIPT}"
    try:
        proc = subprocess.run(
            [_UV, "run", str(_SCRIPT), city],
            capture_output=True,
            timeout=30.0,
            text=False,
        )
        stdout, stderr = proc.stdout, proc.stderr
    except FileNotFoundError:
        try:
            proc = subprocess.run(
                [sys.executable, str(_SCRIPT), city],
                capture_output=True,
                timeout=30.0,
                text=False,
            )
            stdout, stderr = proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            return "天气查询超时"
    except subprocess.TimeoutExpired:
        return "天气查询超时"

    raw = stdout.decode("utf-8", errors="replace").strip()
    if not raw or "[错误]" in raw:
        err_msg = raw or stderr.decode("utf-8", errors="replace").strip()
        return f"查询失败: {err_msg}"
    return raw

class AssistantFnc(llm.Toolset):
    def __init__(self, room):
        super().__init__(id="weather_tools")
        self.room = room

    @property
    def tools(self) -> list[llm.Tool]:
        return llm.find_function_tools(self)

    @llm.function_tool(description="获取指定城市的天气。请传入要查询的城市名称。")
    async def get_weather(self, city: str):
        print(f"[Tool Call] get_weather requested for city: {city}")
        # Run synchronous subprocess command in a separate thread so we don't block the async event loop
        result = await asyncio.to_thread(run_weather_script, city)
        
        # Broadcast weather data to frontend via DataChannel
        import json
        try:
            parsed_data = json.loads(result)
            payload = json.dumps({
                "type": "weather_data",
                "city": city,
                "data": parsed_data
            })
            await self.room.local_participant.publish_data(payload)
        except Exception as e:
            print(f"Failed to publish weather data: {e}")
            
        return result

async def entrypoint(ctx: JobContext):
    print("Connecting to room...")
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    fnc_ctx = AssistantFnc(room=ctx.room)

    dashscope_api_key = "sk-b74891111ed741548b74c79ac08f7216"
    
    agent = Agent(
        instructions=(
            "你是一个超级友好的智能语音助手，也是一个实时语音转录修正专家。\n"
            "角色设定：将用户不连贯的语音转换为易于阅读的内容并用自然温柔的语音对话。\n"
            "处理规则：\n"
            "1. 口语过滤：自动去除语气词（如：呃、那个、啊、就是）。\n"
            "2. 数字转换：所有温度、风力、日期、百分比一律用阿拉伯数字（例：零下五度 -> -5°C）。\n"
            "3. 专有名词校正：优先识别地理和气象术语。场景领域为“气象地理”与“日常生活对话”。\n"
            "4. 实时性：保持句子简练，不要为了修辞而改变用户原意。\n"
            "5. 中断标记：如果检测到用户话没说完被截断，务必以“...”结尾，不要强行补全。\n"
            "6. 强制热词纠错权重：全球主要城市名（特别是中国县级以上）、积雪深度、寒潮预警、体感温度、PM2.5、AQI、紫外线强度、降水概率。如果发音相近，必须修正为这些词。\n"
            "7. 动作指令：如果听到“唤醒”、“闭嘴”、“退下”、“别说了”，请领会其中断意图。\n"
            "如果遇到天气查询，请使用提供的查询工具。"
        ),
        llm=openai.realtime.RealtimeModel(
            voice="zh-cn-average",
            model="qwen-omni-turbo",
            base_url="wss://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key=dashscope_api_key,
        ),
        tools=[fnc_ctx],
    )

    session = AgentSession(agent=agent)
    await session.start(ctx.room)
    print("voice_worker is running. Assistant is ready.")

if __name__ == "__main__":
    import os
    if not os.getenv("LIVEKIT_URL"):
        os.environ["LIVEKIT_URL"] = "ws://127.0.0.1:7880"
    if not os.getenv("LIVEKIT_API_KEY"):
        os.environ["LIVEKIT_API_KEY"] = "devkey"
    if not os.getenv("LIVEKIT_API_SECRET"):
        os.environ["LIVEKIT_API_SECRET"] = "secret"
        
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, port=8082))
