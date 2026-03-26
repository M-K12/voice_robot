"""
天气查询路由 — 调用 spd-weather skill 并返回结构化 JSON
"""

from __future__ import annotations

import sys
import json
import asyncio
import subprocess
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter()

# spd-weather 脚本路径（相对于 backend/ 的父目录）
_SCRIPT = (
    Path(__file__).parent.parent / "spd-weather" / "scripts" / "spd_weather.py"
).resolve()

import shutil
_UV = shutil.which("uv") or "uv.exe"  # 规避 Windows 下缺省扩展名引发子进程 OSError


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
def get_weather(city: str = Query(..., description="城市名称，如：北京")):
    """
    调用 spd-weather skill 获取天气，返回结构化 JSON。
    使用同步 def，FastAPI 会自动分配到线程池执行，避免 Windows 环境下 Uvicorn 无法在 SelectorEventLoop 启动 subprocess 的 500 异常。
    """
    if not _SCRIPT.exists():
        raise HTTPException(status_code=500, detail=f"spd_weather.py 未找到: {_SCRIPT}")

    try:
        proc = subprocess.run(
            [_UV, "run", "--no-sync", str(_SCRIPT), city],
            capture_output=True,
            timeout=30.0,
            text=False,
        )
        stdout, stderr = proc.stdout, proc.stderr
    except FileNotFoundError:
        # fallback：直接用系统 Python
        try:
            proc = subprocess.run(
                [sys.executable, str(_SCRIPT), city],
                capture_output=True,
                timeout=30.0,
                text=False,
            )
            stdout, stderr = proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail="天气查询超时（30s）")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="天气查询超时（30s）")

    raw = stdout.decode("utf-8", errors="replace").strip()
    if not raw or "[错误]" in raw:
        err_msg = raw or stderr.decode("utf-8", errors="replace").strip()
        raise HTTPException(status_code=404, detail=err_msg)

    return _parse_weather_text(raw, city)
