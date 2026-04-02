"""
天气查询路由 — 调用 spd-weather skill 并返回结构化 JSON
"""

from __future__ import annotations

import sys
import json
import asyncio
from pathlib import Path
from typing import List, Optional

# ──────────────────────────────────────────────
# 导入 spd_weather 工具类（模块化集成）
# ──────────────────────────────────────────────
_SCRIPT_DIR = (Path(__file__).parent.parent / "spd-weather" / "scripts").resolve()
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.append(str(_SCRIPT_DIR))

try:
    from spd_weather import Tools as WeatherTools
    weather_client = WeatherTools()
except ImportError:
    print(f"[WeatherRouter] Warning: Could not import spd_weather from {_SCRIPT_DIR}")
    weather_client = None

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter()

# 脚本路径仅作记录备份，不再通过 subprocess 调用
_SCRIPT = _SCRIPT_DIR / "spd_weather.py"


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []


def _parse_weather_text(raw: str, city: str) -> dict:
    """
    将 spd_weather.py 输出的文本简单解析为结构化 JSON。
    前端可直接通过 raw_text 渲染，structured 字段仅作可选增强。
    """
    lines = raw.strip().splitlines()
    daily: list[dict] = []
    hourly: list[dict] = []
    mode = None

    for line in lines:
        stripped = line.strip()
        if "未来7天" in stripped or "日预报" in stripped:
            mode = "daily"
            continue
        if "逐小时" in stripped or "小时预报" in stripped:
            mode = "hourly"
            continue
        if "── 翌日 ──" in stripped:
            continue

        if mode == "daily" and stripped.startswith(("今日", "明日", "后天", "周")):
            try:
                # 格式: 今日(MM-DD 周X)：天气  高温T/低温T  风向风力  降水Xmm
                parts = stripped.split("：", 1)
                label = parts[0].strip()
                rest = parts[1].strip() if len(parts) > 1 else ""
                daily.append({"label": label, "summary": rest})
            except Exception:
                pass

        elif mode == "hourly" and len(stripped) > 4 and stripped[2:5] in (":00", "：00"):
            try:
                hour_part, *detail = stripped.split("  ", 1)
                hourly.append({
                    "hour": hour_part.strip(),
                    "summary": detail[0].strip() if detail else "",
                })
            except Exception:
                pass

    return {
        "city": city,
        "raw_text": raw,
        "daily": daily,
        "hourly": hourly,
    }


@router.get("/weather")
async def get_weather(city: str = Query(..., description="城市名称，如：北京")):
    """
    模块化调用 spd-weather 获取天气，返回结构化 JSON。
    响应速度从秒级降低至毫秒级。
    """
    if not weather_client:
        raise HTTPException(status_code=500, detail="Weather client not initialized.")

    try:
        # 直接异步调用工具方法
        raw = await weather_client.get_city_weather(city)
        if not raw or "[错误]" in raw:
            raise HTTPException(status_code=404, detail=raw or "未找到天气数据")
            
        return _parse_weather_text(raw, city)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
