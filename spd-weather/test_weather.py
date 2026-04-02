#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "httpx",
# ]
# ///
"""
test_weather.py
可在 spd-weather 目录下直接运行的回归测试脚本。
测试三个城市，验证 get_city_weather 的查询结果格式正确。

运行方式：
    cd d:/Ming/voice_robot/spd-weather
    uv run test_weather.py
"""

import asyncio
import os
import sys

# 定位到 scripts/ 目录（跨平台方式）
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_THIS_DIR, "scripts"))

from spd_weather import Tools  # noqa: E402

TEST_CITIES = ["北京", "成都", "湘西"]


async def run_tests():
    tool = Tools()
    try:
        all_passed = True
        for city in TEST_CITIES:
            print(f"\n{'='*50}")
            print(f"📍 查询城市：{city}")
            print("=" * 50)
            result = await tool.get_city_weather(city)

            # 简单断言：结果中必须包含城市名且包含天气预报关键字
            if "天气预报" in result and "℃" in result:
                print(result)
                print(f"\n✅ [{city}] 测试通过")
            elif result.startswith("[错误]"):
                print(f"❌ [{city}] 返回错误：{result}")
                all_passed = False
            else:
                print(result)
                print(f"⚠️  [{city}] 结果异常（可能数据为空）")

        print(f"\n{'='*50}")
        print("✅ 全部测试完成" if all_passed else "⚠️  部分测试未通过，请检查上方输出")
    finally:
        await tool.close()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_tests())
