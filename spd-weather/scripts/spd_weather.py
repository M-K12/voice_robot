#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "httpx",
# ]
# ///

"""
title: 天气查询函数工具
description: 提供公司内部的实时与未来天气查询功能，包括 24 小时预报和 7 天预报。
author: admin
version: 1.3
"""

import os
import sys
import json
import re
import httpx
import asyncio
import argparse
from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone, date as _date

# ──────────────────────────────────────────────────────────────────────────────
# Token：优先从环境变量读取，否则使用内置默认值
# ──────────────────────────────────────────────────────────────────────────────
API_BEARER_TOKEN = os.getenv(
    "SPD_WEATHER_TOKEN",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX2lkIjoiN2FkOTE3MzMzODNjNGFjOGFlMTZhMThhNDBiZjU2Y2UiLCJwaG9uZSI6IjE1MTYxMTgzMDA3IiwidXNlcl9uYW1lIjoi5p2O6ZizIiwic2NvcGUiOlsiYWxsIl0sImV4cCI6MjUyODk1MTkxMywianRpIjoiZWI4ODRjYWMtYWY2OC00ZTNjLTk3YzctYTJmNWE0YzUyMGE4IiwiY2xpZW50X2lkIjoibndlY2hhdCJ9.Td1EC5QhKNF9Meo_8v8RgJQFanZeyDHoIdfi3WGEY0g"
)

# ──────────────────────────────────────────────────────────────────────────────
# #2 城市名规范化：行政后缀正则 + 省会映射 + 别名字典
# ──────────────────────────────────────────────────────────────────────────────

# 行政后缀正则（顺序：长优先）
_ADMIN_SUFFIXES = re.compile(
    r"(回族自治区|维吾尔自治区|壮族自治区|藏族自治区"
    r"|土家族苗族自治州|布依族苗族自治州|哈尼族彝族自治州"
    r"|蒙古族藏族自治州|柯尔克孜自治州|彝族自治州"
    r"|苗族侗族自治州|傣族景颇族自治州|傣族自治州"
    r"|藏族羌族自治州|藏族自治州|哈萨克自治州|朝鲜族自治州"
    r"|蒙古族自治州|回族自治州|土家族自治州|壮族自治州"
    r"|土家族自治县|苗族自治县|彝族自治县|回族自治县"
    r"|满族自治县|蒙古族自治县|壮族自治县|瑶族自治县"
    r"|傣族自治县|布依族自治县|侗族自治县|畲族自治县"
    r"|土族自治县|撒拉族自治县|羌族自治县|藏族自治县"
    r"|自治区|特别行政区|自治州|自治县|自治旗"
    r"|地区|盟市|盟|省|市|县|区|旗)"
)

# 省名 → 省会城市（用于处理"用户说四川想查成都"的情形）
PROVINCE_CAPITALS: Dict[str, str] = {
    "北京": "北京", "天津": "天津", "上海": "上海", "重庆": "重庆",
    "河北": "石家庄", "山西": "太原", "辽宁": "沈阳", "吉林": "长春",
    "黑龙江": "哈尔滨", "江苏": "南京", "浙江": "杭州", "安徽": "合肥",
    "福建": "福州", "江西": "南昌", "山东": "济南", "河南": "郑州",
    "湖北": "武汉", "湖南": "长沙", "广东": "广州", "海南": "海口",
    "四川": "成都", "贵州": "贵阳", "云南": "昆明", "陕西": "西安",
    "甘肃": "兰州", "青海": "西宁", "内蒙古": "呼和浩特",
    "广西": "南宁", "西藏": "拉萨", "宁夏": "银川", "新疆": "乌鲁木齐",
}

# 网络别名 / 口语映射（只保留脚本内无法自动推断的部分）
CITY_ALIAS: Dict[str, str] = {
    "魔都": "上海", "帝都": "北京", "蓉城": "成都", "羊城": "广州",
    "鹏城": "深圳", "江城": "武汉", "榕城": "福州", "泉城": "济南",
    "星城": "长沙", "春城": "昆明", "冰城": "哈尔滨", "山城": "重庆",
}


def _normalize_city(raw: str) -> str:
    """
    #2 城市名标准化（脚本侧）：
      1. 剥离行政后缀（循环直到稳定）
      2. 省名 → 省会
      3. 网络别名映射
    """
    city = raw.strip()
    # 1. 循环剥离后缀（最多 5 次）
    for _ in range(5):
        stripped = _ADMIN_SUFFIXES.sub("", city, count=1)
        if stripped == city:
            break
        city = stripped
    # 2. 网络别名
    city = CITY_ALIAS.get(city, city)
    # 3. 省名 → 省会
    city = PROVINCE_CAPITALS.get(city, city)
    return city


# ──────────────────────────────────────────────────────────────────────────────
# 加载预构建的两个 O(1) 查询索引（由 build_station_dicts.py 生成）
# ──────────────────────────────────────────────────────────────────────────────

def _load_station_dicts():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assets = os.path.join(base_dir, "assets")
    try:
        with open(os.path.join(assets, "city_to_areacode.json"), "r", encoding="utf-8") as f:
            c2a = json.load(f)
        with open(os.path.join(assets, "areacode_to_station.json"), "r", encoding="utf-8") as f:
            a2s = json.load(f)
        return c2a, a2s
    except Exception as exc:
        print(f"[spd-weather] 警告：加载索引文件失败：{exc}", file=sys.stderr)
        return {}, {}


CITY_TO_AREACODE, AREACODE_TO_STATION = _load_station_dicts()

# ──────────────────────────────────────────────────────────────────────────────
# #11 文件缓存（缓存原始数据 dict，时间戳用 UTC）
# ──────────────────────────────────────────────────────────────────────────────

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CACHE_DIR = os.path.join(_BASE_DIR, "assets", "cache")
CACHE_EXPIRE_MINUTES = 30

os.makedirs(_CACHE_DIR, exist_ok=True)


def _cache_path(city: str) -> str:
    safe = city.replace("/", "_").replace("\\", "_")
    return os.path.join(_CACHE_DIR, f"{safe}.json")


def _load_cache(city: str) -> Optional[Dict[str, Any]]:
    """读取缓存，返回原始数据 dict；过期或不存在则返回 None。"""
    path = _cache_path(city)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        # #11 aware datetime 比较
        saved_at = datetime.fromisoformat(obj["saved_at"])
        now_utc = datetime.now(timezone.utc)
        if now_utc - saved_at < timedelta(minutes=CACHE_EXPIRE_MINUTES):
            return obj.get("data")  # dict {"hourly": ..., "daily": ...}
    except Exception:
        pass
    return None


def _save_cache(city: str, hourly: Dict, daily: Dict):
    """将原始 API 数据写入缓存文件（UTC 时间戳）。"""
    try:
        with open(_cache_path(city), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "saved_at": datetime.now(timezone.utc).isoformat(),
                    "data": {"hourly": hourly, "daily": daily},
                },
                f,
                ensure_ascii=False,
            )
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# 输出格式化：将原始数据 dict 转换为 LLM 友好的精简文本
# ──────────────────────────────────────────────────────────────────────────────

_WEEKDAY_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _parse_date(date_str: str) -> Optional[_date]:
    """#7 安全解析日期字符串（'20260319' 格式）。"""
    try:
        return datetime.strptime(date_str.strip(), "%Y%m%d").date()
    except (ValueError, AttributeError):
        return None


def _parse_datetime_str(dt_str: str) -> Optional[datetime]:
    """#7 安全解析 API 返回的 datetime 字符串（'2026-03-19 15:00:00' 格式）。"""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(dt_str.strip(), fmt)
        except (ValueError, AttributeError):
            continue
    return None


def _format_output(city: str, hourly_data: Dict, daily_data: Dict) -> str:
    """
    将上游 API 的原始数据 dict 格式化为精简文本，减少 LLM 输入 Token。
    """
    lines = [f"【{city} 天气预报】"]

    # ── 7 天日预报 ──────────────────────────────────────────────────────────
    try:
        dd = daily_data.get("data") or {}
        if dd and daily_data.get("errcode") in ("200", 200):
            time_list = dd.get("time_list", [])
            tmax_list = dd.get("TMAX", [])
            tmin_list = dd.get("TMIN", [])
            weather_list = dd.get("WPHE24", [])
            dir_list = dd.get("DIR_STR", [])
            spd_list = dd.get("SPEED_STR", [])
            rain_list = dd.get("ER24", [])

            lines.append("\n📅 未来7天日预报")
            for i, date_str in enumerate(time_list):
                if i >= 7:
                    break
                d = _parse_date(date_str)
                if d is None:
                    continue
                mm_dd = f"{d.month:02d}-{d.day:02d}"
                wday = _WEEKDAY_ZH[d.weekday()]

                # #13 统一格式：前三天保留今/明/后，其余全用"周X(mm-dd)"
                if i == 0:
                    label_str = f"今日({mm_dd} {wday})"
                elif i == 1:
                    label_str = f"明日({mm_dd} {wday})"
                elif i == 2:
                    label_str = f"后天({mm_dd} {wday})"
                else:
                    label_str = f"{wday}({mm_dd})"

                tmax = f"{tmax_list[i]}℃" if i < len(tmax_list) else "?"
                tmin = f"{tmin_list[i]}℃" if i < len(tmin_list) else "?"
                weath = weather_list[i] if i < len(weather_list) else "?"
                wdir = dir_list[i] if i < len(dir_list) else "?"
                wspd = f"{spd_list[i]}级" if i < len(spd_list) else "?"
                rain = f"{rain_list[i]}mm" if i < len(rain_list) else "?"
                lines.append(
                    f"  {label_str}：{weath}  高温{tmax}/低温{tmin}  {wdir}风{wspd}  降水{rain}"
                )
        else:
            lines.append("\n📅 日预报：暂无数据")
    except Exception as e:
        lines.append(f"\n📅 日预报解析失败：{e}")

    # ── 逐小时预报（仅取未来 8 小时）────────────────────────────────────────
    try:
        hd = hourly_data.get("data") or {}
        if hd and hourly_data.get("errcode") in ("200", 200):
            s_time_list = hd.get("s_time") or ["????-??-?? 00:00:00"]
            s_dt = _parse_datetime_str(s_time_list[0])
            start_hour = s_dt.hour if s_dt else 0
            mm_dd = f"{s_dt.month:02d}-{s_dt.day:02d}" if s_dt else "??-??"

            tmp_list = hd.get("TMP", [])
            wth_list = hd.get("WPHE01") or []
            dir_list_h = hd.get("DIR_STR", [])
            spd_list_h = hd.get("SPEED_STR", [])
            rain_list_h = hd.get("ER01", [])

            lines.append(f"\n🕐 逐小时预报（起始 {mm_dd} {start_hour:02d}:00，共展示8小时）")
            crossed_day = False  # #14 跨天标记
            for i in range(min(8, len(tmp_list))):
                absolute_hour = start_hour + i
                h = absolute_hour % 24

                # #14 当跨过午夜时插入"翌日"分隔线（仅一次）
                if absolute_hour >= 24 and not crossed_day:
                    lines.append("  ── 翌日 ──")
                    crossed_day = True

                tmp = f"{tmp_list[i]}℃" if i < len(tmp_list) else "?"
                wph = wth_list[i] if i < len(wth_list) else ""
                wdir = dir_list_h[i] if i < len(dir_list_h) else ""
                wspd = f"{spd_list_h[i]}级" if i < len(spd_list_h) else ""
                rain = (
                    f"降水{rain_list_h[i]}mm"
                    if i < len(rain_list_h) and rain_list_h[i] > 0
                    else ""
                )
                weather_str = wph if wph else (f"{wdir}风{wspd}" if wdir else "")
                parts = [p for p in [weather_str, rain] if p]
                suffix = "  " + "  ".join(parts) if parts else ""
                lines.append(f"  {h:02d}:00  {tmp}{suffix}")
        else:
            msg = hourly_data.get("message", "暂无数据")
            lines.append(f"\n🕐 逐小时预报：{msg}")
    except Exception as e:
        lines.append(f"\n🕐 逐小时预报解析失败：{e}")

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# #4 异步重试工具
# ──────────────────────────────────────────────────────────────────────────────

async def _request_with_retry(client: httpx.AsyncClient, method: str, url: str,
                               retries: int = 2, delay: float = 1.5, **kwargs) -> httpx.Response:
    """对 httpx 请求加指数退避重试，处理 ConnectError / TimeoutException。"""
    last_exc: Exception = RuntimeError("未知错误")
    for attempt in range(retries + 1):
        try:
            resp = await client.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
            last_exc = e
            if attempt < retries:
                await asyncio.sleep(delay * (attempt + 1))
    raise last_exc


# ──────────────────────────────────────────────────────────────────────────────
# API 客户端
# ──────────────────────────────────────────────────────────────────────────────

# 运行时城市站点信息缓存（进程内）
CITY_CACHE: Dict[str, Dict[str, Any]] = {}


class Tools:
    def __init__(self):
        self.headers = {"Authorization": f"Bearer {API_BEARER_TOKEN}"}
        self.timeout = 30.0
        self._client = httpx.AsyncClient(timeout=self.timeout, trust_env=False)

    async def close(self):
        await self._client.aclose()

    async def get_point_hour_forecast(self, lat: float, lon: float) -> Dict:
        """#1 直接返回 dict，不做 JSON 序列化往返。"""
        url = "https://jxtq.sxjzqx.com:7070/pyapi/api/get_point_hour"
        para_json = json.dumps({"lat": lat, "lon": lon}, ensure_ascii=False)
        try:
            response = await _request_with_retry(
                self._client, "POST", url,
                data={"para": para_json}, headers=self.headers
            )
            return response.json()
        except Exception as e:
            return {"data": None, "errcode": -1, "message": str(e)}

    async def get_point_day_forecast(self, lat: float, lon: float, station_id: str) -> Dict:
        """#1 直接返回 dict，不做 JSON 序列化往返。"""
        url = "https://jxtq.sxjzqx.com:7070/pyapi/api/get_point_day"
        para_json = json.dumps({"lat": lat, "lon": lon, "station": station_id}, ensure_ascii=False)
        try:
            response = await _request_with_retry(
                self._client, "POST", url,
                data={"para": para_json}, headers=self.headers
            )
            return response.json()
        except Exception as e:
            return {"data": None, "errcode": -1, "message": str(e)}

    async def get_city_weather(self, city_name: str) -> str:
        # #2 脚本侧城市名标准化（剥后缀 → 别名 → 省会）
        city = _normalize_city(city_name)

        # ── 1. 文件缓存命中 ──────────────────────────────────────────────────
        cached = _load_cache(city)
        if cached:
            # #3 重新渲染，确保格式变更立即生效
            result = _format_output(city, cached["hourly"], cached["daily"])
            return result # + "\n\n（来自缓存，刷新间隔30分钟）"

        # ── 2. 查本地站点索引 ────────────────────────────────────────────────
        if city not in CITY_CACHE:
            area_code = CITY_TO_AREACODE.get(city)
            if not area_code:
                return f"[错误] 未在本地索引中找到城市：{city}（原始输入：{city_name}）"
            station_info = AREACODE_TO_STATION.get(area_code)
            if not station_info:
                return f"[错误] 未找到 {city}（areaCode={area_code}）对应的气象站点"
            CITY_CACHE[city] = station_info

        station_info = CITY_CACHE[city]
        lat = station_info["lat"]
        lon = station_info["lon"]
        station_id = station_info["station_id"]

        # ── 3. 并发请求两个接口 ──────────────────────────────────────────────
        hour_result, day_result = await asyncio.gather(
            self.get_point_hour_forecast(lat, lon),
            self.get_point_day_forecast(lat, lon, station_id),
        )

        # ── 4. 写文件缓存（原始数据）────────────────────────────────────────
        _save_cache(city, hour_result, day_result)

        # ── 5. 格式化为文本 ──────────────────────────────────────────────────
        return _format_output(city, hour_result, day_result)


# ==========================================
# CLI 入口，供大模型通过终端调用
# ==========================================
async def main():
    # 修复 Windows 控制台默认编码（防止 emoji 输出乱码）
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="SPD Weather 天气查询技能脚本")
    parser.add_argument("city", type=str, help="需要查询的城市名称，例如：北京")
    args = parser.parse_args()

    tool = Tools()
    try:
        result = await tool.get_city_weather(args.city)
        print(result)
        sys.stdout.flush()
    finally:
        await tool.close()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())