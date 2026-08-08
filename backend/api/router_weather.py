"""
天气查询路由 — 调用 spd-weather skill 并返回结构化 JSON
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter()


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []


@router.get("/weather")
async def get_weather(city: str = Query(..., description="城市名称，如：北京")):
    """
    模块化调用天气服务获取天气，返回结构化 JSON。
    """
    from weather_service import weather_service
    try:
        weather_data = await weather_service.get_weather(city)
        if not weather_data:
            raise HTTPException(status_code=404, detail=f"未找到 {city} 的天气数据")
        return {"status": "success", "city": city, "data": weather_data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/weather/aqi")
async def get_weather_aqi(city: str = Query(..., description="城市名称，如：北京")):
    """获取指定城市的空气质量指数 (AQI)"""
    from weather_service import weather_service
    try:
        aqi_data = await weather_service.get_aqi(city)
        if not aqi_data:
            raise HTTPException(status_code=404, detail=f"未获取到 {city} 的 AQI 数据")
        return {"status": "success", "city": city, "data": aqi_data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/weather/life_index")
async def get_weather_life_index(city: str = Query(..., description="城市名称，如：北京")):
    """获取指定城市的生活指数"""
    from weather_service import weather_service
    try:
        index_data = await weather_service.get_life_index(city)
        if not index_data:
            raise HTTPException(status_code=404, detail=f"未获取到 {city} 的生活指数数据")
        return {"status": "success", "city": city, "data": index_data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
