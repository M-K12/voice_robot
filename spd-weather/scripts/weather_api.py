#!/usr/bin/env python3
# -*- coding: utf-8 -*-

r"""
基于 spd_weather.py 的天气查询接口服务。
运行方式：
    # 进入 scripts 目录执行：
    uvicorn weather_api:app --host 0.0.0.0 --port 8000 --reload
"""

import sys
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# 引入已有脚本的查询工具类
from spd_weather import Tools

# 使用 lifespan 事件管理器，在服务启动时初始化 Tools，在服务关闭时清理连接池资源
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.weather_tool = Tools()
    yield
    await app.state.weather_tool.close()

app = FastAPI(
    title="天气查询 API 服务",
    description="提供实时与未来天气查询功能，包括 24 小时预报和 7 天预报，完全兼容 spd_weather.py。支持自动补全地名后缀及别名转换（如：萧山 -> 杭州）。",
    version="1.3",
    lifespan=lifespan
)

# 添加 CORS 中间件，允许外部跨域调用
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 根据需要可更换为允许的域名列表
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/weather/json", summary="获取天气数据（JSON格式）")
async def get_weather_json(city: str = Query(..., description="需要查询的城市名称，例如：北京")):
    """
    接收城市名参数，返回带文本描述的结构化 JSON。
    """
    tool: Tools = app.state.weather_tool
    try:
        # 直接复用 spd_weather 的获取逻辑
        result = await tool.get_city_weather(city)
        if "[错误]" in result:
            raise HTTPException(status_code=404, detail=result)
        return {"city": city, "weather_text": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/weather/text", summary="获取天气文本（纯文本格式）", response_class=PlainTextResponse)
async def get_weather_text(city: str = Query(..., description="需要查询的城市名称，例如：北京")):
    """
    接收城市名参数，直接返回可以直接展示或语音播报的纯文本。
    """
    tool: Tools = app.state.weather_tool
    try:
        result = await tool.get_city_weather(city)
        if "[错误]" in result:
            raise HTTPException(status_code=404, detail=result)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    uvicorn.run("weather_api:app", host="0.0.0.0", port=8000, reload=True)
