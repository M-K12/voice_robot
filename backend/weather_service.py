"""
小安气象机器人 - 天气服务适配器
对接您的定制气象 API，统一返回结构化天气数据。

核心逻辑：
1. 优先调用“风雨哨兵”专业接口（主选）。
2. 如果主选接口失败，调用“和风天气”补充接口（垫底）。
3. 支持切换到“模拟器”模式进行离线调试。
4. 如果均查询不到，明确告知“未查询到数据”，不进行虚假播报。
"""

import asyncio
import logging
import os
import time
import abc
from datetime import datetime, timedelta
import json
from typing import Optional, List, Dict, Any
import httpx
import re

# Setup logger before imports
logger = logging.getLogger("xiaoan.weather")

from weather_mock import generate_mock_weather
from moji_service import moji_service
from fengyu_service import fengyu_service
from amap_service import amap_service

# Dummy Geocoder since we use online AMap service primarily
class DummyGeocoder:
    @classmethod
    def get_coordinates(cls, city_name):
        return None, None, None
Geocoder = DummyGeocoder

# API 配置
WIND_RAIN_SENTINEL_URL = os.environ.get("WIND_RAIN_SENTINEL_URL", "")
WIND_RAIN_SENTINEL_KEY = os.environ.get("WIND_RAIN_SENTINEL_KEY", "")
QWEATHER_API_KEY = os.environ.get("QWEATHER_API_KEY", "")
USE_MOCK_WEATHER = os.environ.get("USE_MOCK_WEATHER", "false").lower() == "true"
# 默认天气源 (从环境变量读取，默认为 fengyu)
DEFAULT_WEATHER_SOURCE = os.environ.get("WEATHER_SOURCE", "moji").lower()

# 历史灾情数据路径
HISTORY_DISASTERS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "history_disasters.json")

# 嘉善后端代理配置
JIASHAN_PROXY_URL = os.environ.get("JIASHAN_PROXY_URL", "http://localhost:10857")

class JiashanProxyProvider:
    """嘉善后端代理服务 (专业气象要素)"""
    def __init__(self):
        self.node_mapping = {
            # --- 气温数据 ---
            "temp_obs": { "eleId": 1002, "modelId": 2, "dataSource": "2", "name": "小时气温实况" },
            "temp_max_1h": { "eleId": 6020, "modelId": 2, "dataSource": "2", "name": "近1小时最高温" },
            "temp_min_1h": { "eleId": 6021, "modelId": 2, "dataSource": "2", "name": "近1小时最低温" },
            "temp_avg_24h": { "eleId": 6022, "modelId": 2, "dataSource": "2", "name": "近24小时平均温" },
            "temp_max_24h": { "eleId": 6023, "modelId": 2, "dataSource": "2", "name": "24小时最高温" },
            "temp_min_24h": { "eleId": 6024, "modelId": 2, "dataSource": "2", "name": "24小时最低温" },
            "temp_forecast": { "eleId": 1005, "modelId": 1, "dataSource": "2", "name": "小时气温预报" },
            "temp_forecast_3h": { "eleId": 6115, "modelId": 1, "dataSource": "2", "name": "3小时气温预报" },

            # --- 降水监测 ---
            "rain_obs": { "eleId": 1008, "modelId": 2, "dataSource": "2", "name": "1小时降水实况" },
            "rain_5min": { "eleId": 1009, "modelId": 2, "dataSource": "2", "name": "5分钟降水实况" },
            "rain_3h": { "eleId": 6011, "modelId": 2, "dataSource": "2", "name": "近3小时累计降水" },
            "rain_6h": { "eleId": 6012, "modelId": 2, "dataSource": "2", "name": "近6小时累计降水" },
            "rain_12h": { "eleId": 6013, "modelId": 2, "dataSource": "2", "name": "近12小时累计降水" },
            "rain_24h": { "eleId": 6014, "modelId": 2, "dataSource": "2", "name": "24小时累计降水" },
            "rain_forecast": { "eleId": 1011, "modelId": 1, "dataSource": "2", "name": "逐小时降水预报" },
            "rain_forecast_3h": { "eleId": 1031, "modelId": 1, "dataSource": "2", "name": "3小时降水预报" },
            "rain_forecast_24h": { "eleId": 6169, "modelId": 1, "dataSource": "2", "name": "24小时降水预报" },

            # --- 风力风向 ---
            "wind_obs": { "eleId": 1014, "modelId": 2, "dataSource": "2", "name": "小时极大风" },
            "wind_2min": { "eleId": 6037, "modelId": 2, "dataSource": "2", "name": "2分钟平均风" },
            "wind_10min": { "eleId": 6038, "modelId": 2, "dataSource": "2", "name": "10分钟平均风" },
            "wind_forecast": { "eleId": 2002, "modelId": 1, "dataSource": "2", "name": "3小时风速预报" },

            # --- 湿度与能见度 ---
            "humidity_obs": { "eleId": 1024, "modelId": 2, "dataSource": "2", "name": "小时相对湿度" },
            "humidity_forecast": { "eleId": 1026, "modelId": 1, "dataSource": "2", "name": "小时相对湿度预报" },
            "visibility_obs": { "eleId": 1020, "modelId": 2, "dataSource": "2", "name": "小时能见度实况" },
            "visibility_min_1h": { "eleId": 6048, "modelId": 2, "dataSource": "2", "name": "小时最低能见度" },
            "visibility_forecast_3h": { "eleId": 1022, "modelId": 1, "dataSource": "2", "name": "3小时能见度预报" },

            # --- 雷达与探测 (DataSource 3) ---
            "radar_obs": { "eleId": 6108, "modelId": 125, "dataSource": "3", "name": "雷达实况分布图" },
            "radar_forecast": { "eleId": 6109, "modelId": 11, "dataSource": "3", "name": "雷达外推分布图" },
        }

    async def get_pro_data(self, element_key: str, area_code: str = "330421") -> Optional[Dict[str, Any]]:
        if element_key not in self.node_mapping:
            return None
        
        node = self.node_mapping[element_key]
        now_str = datetime.now().strftime("%Y-%m-%d %H:00:00")
        
        async def fetch_type(rt):
            payload = {
                "areaCode": area_code,
                "dataSource": node["dataSource"],
                "datetime": now_str,
                "eleId": node["eleId"],
                "modelId": node["modelId"],
                "retType": rt
            }
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    r = await client.post(f"{JIASHAN_PROXY_URL}/grid-data/query", json=payload)
                    if r.status_code == 200:
                        return r.json()
            except Exception as e:
                logger.error(f"[JiashanProxy] Fetch retType {rt} failed: {e}")
            return None

        # 并行抓取站点(1)和插值色斑图(3)
        stations_res, contour_res = await asyncio.gather(fetch_type(1), fetch_type(3))
        
        result = {
            "name": node["name"],
            "elements": element_key,
            "stations": [],
            "contour": None,
            "value": 0,
            "station_count": 0
        }

        if stations_res and stations_res.get("code") == 0:
            stations = stations_res.get("data", [])
            result["stations"] = stations
            result["station_count"] = len(stations)
            values = [s.get("value") for s in stations if s.get("value") is not None]
            if values:
                result["value"] = round(sum(values) / len(values), 1)

        if contour_res and contour_res.get("code") == 0:
            result["contour"] = contour_res.get("data")
            
        if result["stations"] or result["contour"]:
            return result
        return None


class BaseWeatherProvider(abc.ABC):
    @abc.abstractmethod
    async def get_weather(self, city: str, date: str, days: int, query_types: Optional[List[str]] = None, date_end: Optional[str] = None, lon: Optional[float] = None, lat: Optional[float] = None) -> Optional[Dict[str, Any]]:
        pass


class WindRainSentinelProvider(BaseWeatherProvider):
    """风雨哨兵专业气象接口 (主选)"""
    async def get_weather(self, city: str, date: str, days: int, query_types: Optional[List[str]] = None, date_end: Optional[str] = None, lon: Optional[float] = None, lat: Optional[float] = None) -> Optional[Dict[str, Any]]:
        logger.info(f"正在尝试使用 [风雨哨兵] 查询 {city} 天气...")
        
        try:
            area_name, pname, cityname, adname, poi_name = city, None, None, None, city
            if lon is None or lat is None:
                lon, lat, area_name, pname, cityname, adname, poi_name = await amap_service.get_poi_coordinates(city)
                if lon is None or lat is None:
                    logger.warning(f"[风雨哨兵] 无法识别城市/地点: {city}")
                    return None

            # Determine what to fetch based on query_types
            if query_types:
                fetch_current = "current" in query_types
                fetch_forecast = "forecast" in query_types
                fetch_alert = "alert" in query_types
            else:
                today_str = datetime.now().strftime("%Y-%m-%d")
                is_today = (date == today_str)
                fetch_current = is_today
                fetch_forecast = True
                fetch_alert = True

            # 2. 查询风雨哨兵 API
            tasks = []
            task_keys = []
            if fetch_current:
                tasks.append(fengyu_service.get_condition(lat, lon))
                task_keys.append("current")
            if fetch_forecast:
                tasks.append(fengyu_service.get_forecast(lat, lon, days=days))
                task_keys.append("forecast")
            if fetch_alert:
                tasks.append(fengyu_service.get_alerts(lat, lon, date_str=date))
                task_keys.append("alert")

            if not tasks:
                logger.warning("[风雨哨兵] 未选择任何查询类型")
                return None

            results = await asyncio.gather(*tasks)
            res_dict = dict(zip(task_keys, results))

            condition = res_dict.get("current")
            forecast = res_dict.get("forecast")
            alerts = res_dict.get("alert")

            if not condition and not forecast and not alerts:
                logger.error(f"[风雨哨兵] API 请求未返回有效数据 ({city})")
                return None

            # 3. 归一化数据
            norm_data = self._normalize(
                area_name, date, condition, forecast, alerts,
                lon, lat, days,
                poi_name=poi_name, pname=pname, cityname=cityname, adname=adname, date_end=date_end
            )
            logger.info(f"[风雨哨兵] 归一化数据: {json.dumps(norm_data, ensure_ascii=False)}")
            return norm_data

        except Exception as e:
            logger.exception(f"[风雨哨兵] 查询异常: {e}")
            return None

    def _normalize(self, city: str, date: str, now: Optional[Dict], forecast: Optional[List], alerts: Optional[List], 
                   lon: float = None, lat: float = None, days: int = 1, poi_name: str = None,
                   pname: str = None, cityname: str = None, adname: str = None) -> Dict[str, Any]:
        """将风雨哨兵数据格式归一化为小安统一结构"""
        
        # 0. 预警数据处理
        norm_alerts = []
        alert_summary_bits = []
        if alerts:
            for al in alerts:
                title = al.get("title", "天气预警")
                level = al.get("level", "未知")
                norm_alerts.append({
                    "title": title,
                    "type": al.get("type"),
                    "level": level,
                    "content": al.get("content"),
                    "pub_time": al.get("pub_time"),
                    "color": "#FF3B30" if "红" in level else "#FF8C00", # 粗略映射
                    "advice": []
                })
                alert_summary_bits.append(title)
        
        # 实况数据映射
        if now:
            now_cond_label = now.get("wpName", "未知")
            std_condition = self._get_cond_type(now_cond_label)
            current = {
                "condition": std_condition,
                "label": now_cond_label,
                "icon": std_condition,
                "temp_c": int(now.get("temMax", 0)), # ObsDay 接口返回的 temMax
                "feels_like_c": int(now.get("temMax", 0)),
                "humidity": int(now.get("prePercent", 0)), 
                "wind_direction": now.get("winDMaxCn", "无风"),
                "wind_level": f"{now.get('windDCnSLeve', '0')}级",
                "vis": "10km",
                "pressure": "1013",
                "uv_index": "1"
            }
        else:
            current = None

        # 预报数据映射（按请求的 days 数量精准截取，只返回目标天数的天气）
        norm_forecast = []
        if forecast:
            target_items = forecast[:days] if days and days > 0 else forecast
            for f in target_items:
                f_cond_label = f.get("wpName", "")
                std_f_cond = self._get_cond_type(f_cond_label)
                norm_forecast.append({
                    "date": f.get("foreDate"),
                    "label": f_cond_label,
                    "icon": std_f_cond,
                    "condition": std_f_cond,
                    "temp_high": int(f.get("temMax", 0)),
                    "temp_low": int(f.get("temMin", 0)),
                    "humidity": int(f.get("prePercent", 0)),
                    "wind_direction": f.get("winDMaxCn"),
                    "wind_level": f"{f.get('windDCnSLeve', '0')}级",
                })

        # 摘要生成
        if current:
            summary = f"正在为您播报（风雨哨兵）：目前{city}天气{current['label']}，气温{current['temp_c']}度。"
            if norm_forecast:
                today_fc = norm_forecast[0]
                summary += f"今日最高气温{today_fc['temp_high']}度，最低气温{today_fc['temp_low']}度。"
        elif norm_forecast:
            summary = f"正在为您播报（风雨哨兵）：{city}的预报。"
            first_fc = norm_forecast[0]
            summary += f"今日{first_fc['label']}，最高气温{first_fc['temp_high']}度，最低气温{first_fc['temp_low']}度。"
        else:
            summary = f"已为您查询（风雨哨兵）{city}的天气预警信息。"

        if alert_summary_bits:
            alerts_str = "、".join(alert_summary_bits)
            summary = f"注意：气象台已发布 {alerts_str}！" + summary

        result = {
            "city": city,
            "poi_name": poi_name or city,
            "province": pname,
            "cityname": cityname,
            "adname": adname,
            "date": date,
            "lng": lon,
            "lat": lat,
            "forecast": norm_forecast,
            "alerts": norm_alerts,
            "summary": summary
        }
        
        if current:
            result["current"] = current

        return result

    def _get_cond_type(self, cond_str: str) -> str:
        if not cond_str:
            return "sunny"
        if any(k in cond_str for k in ["雷", "雷阵", "强对流"]): return "thunderstorm"
        if "雨" in cond_str: return "rainy"
        if any(k in cond_str for k in ["雪", "冻"]): return "snowy"
        if any(k in cond_str for k in ["雾", "霾", "沙尘", "扬沙"]): return "foggy"
        if "阴" in cond_str: return "overcast"
        if any(k in cond_str for k in ["云", "多云", "少云", "晴间"]): return "cloudy"
        return "sunny"


class MojiProvider(BaseWeatherProvider):
    """墨迹天气专业版 (基于离线地名解析)"""
    async def get_weather(self, city: str, date: str, days: int, query_types: Optional[List[str]] = None, date_end: Optional[str] = None, lon: Optional[float] = None, lat: Optional[float] = None) -> Optional[Dict[str, Any]]:
        if not moji_service or not Geocoder:
            logger.error("[墨迹天气] 核心模块 (moji_service/Geocoder) 未正确加载")
            return None

        # 1. 地名解析 (优先复用外层解析的坐标，免发重复请求)
        area_name, pname, cityname, adname, poi_name = city, None, None, None, city
        if lon is None or lat is None:
            lon, lat, area_name, pname, cityname, adname, poi_name = await amap_service.get_poi_coordinates(city)
            if lon is None or lat is None:
                logger.warning(f"[墨迹天气] 地理编码解析失败: {city}")
                return None

        # 2. 查询墨迹 API
        try:
            # Determine what to fetch based on query_types
            if query_types:
                fetch_current = "current" in query_types
                fetch_forecast = "forecast" in query_types
                fetch_alert = "alert" in query_types
            else:
                # 优化查询：如果查询的是今天且仅 1 天，优先只查实况，不触发冗余的 15 天预报查询。
                today_str = datetime.now().strftime("%Y-%m-%d")
                is_today = (date == today_str)
                fetch_current = is_today
                fetch_forecast = not (is_today and days == 1) or (days > 1)
                fetch_alert = True

            tasks = []
            task_keys = []
            if fetch_current:
                tasks.append(moji_service.get_condition(lat, lon, days=days, target_date=date))
                task_keys.append("current")
            if fetch_forecast:
                tasks.append(moji_service.get_forecast(lat, lon, days=days, target_date=date))
                task_keys.append("forecast")
            if fetch_alert:
                tasks.append(moji_service.get_alerts(lat, lon))
                task_keys.append("alert")

            if not tasks:
                logger.warning("[墨迹天气] 未选择任何查询类型")
                return None

            results = await asyncio.gather(*tasks)
            res_dict = dict(zip(task_keys, results))

            condition = res_dict.get("current")
            forecasts = res_dict.get("forecast")
            alerts = res_dict.get("alert")

            if not condition and not forecasts and not alerts:
                logger.error(f"[墨迹天气] API 请求未返回有效数据 ({city})")
                return None

            norm_data = self._normalize(
                area_name, date, condition, forecasts, alerts, 
                lon, lat, days, 
                poi_name=poi_name, pname=pname, cityname=cityname, adname=adname, date_end=date_end
            )
            return norm_data
        except Exception as e:
            logger.exception(f"[墨迹天气] 查询异常: {e}")
            return None

    def _normalize(self, city: str, date: str, now: Optional[Dict], forecast: Optional[List], alerts: Optional[List], 
                   lon: float = None, lat: float = None, days: int = 1, poi_name: str = None,
                   pname: str = None, cityname: str = None, adname: str = None, date_end: str = None) -> Dict[str, Any]:
        """将墨迹数据格式归一化为小安统一结构"""
        
        # 0. 预警数据处理 (高优先级)
        norm_alerts = []
        alert_summary_bits = []
        if alerts:
            for al in alerts:
                level = al.get("level", "未知")
                title = al.get("title", "天气预警")
                defense_ids = al.get("land_defense_id", "") or al.get("port_defense_id", "")
                advice = moji_service.format_defense_guide(defense_ids)
                
                norm_alerts.append({
                    "title": title,
                    "type": al.get("type"),
                    "level": level,
                    "content": al.get("content"),
                    "pub_time": al.get("pub_time"),
                    "color": moji_service.get_alert_color(level),
                    "advice": advice
                })
                alert_summary_bits.append(title)
        
        # 实况数据映射
        if now:
            now_cond_label = now.get("condition", "未知")
            std_condition = self._get_cond_type(now_cond_label)
            current = {
                "condition": std_condition,
                "label": now_cond_label,
                "icon": std_condition,
                "temp_c": int(now.get("temp", 0)) if now else 0,
                "feels_like_c": int(now.get("realFeel", 0)) if now else 0,
                "humidity": int(now.get("humidity", 0)) if now else 0,
                "wind_direction": now.get("windDir", "无风") if now else "无风",
                "wind_level": now.get("windLevel", "0级") if now else "0级",
                "vis": f"{round(int(now.get('vis', 10000)) / 1000, 1)}km" if now.get('vis') else "10km",
                "pressure": now.get("pressure", "1013"),
                "uv_index": now.get("uvi", "1")
            }
        else:
            current = None

        # 构建精准的目标日期集合
        target_dates = set()
        if date:
            try:
                s_date = date.split("T")[0]
                start_dt = datetime.strptime(s_date, "%Y-%m-%d")
                if date_end:
                    e_date = date_end.split("T")[0]
                    end_dt = datetime.strptime(e_date, "%Y-%m-%d")
                    curr = start_dt
                    while curr <= end_dt:
                        target_dates.add(curr.strftime("%Y-%m-%d"))
                        curr += timedelta(days=1)
                else:
                    num_days = max(1, days or 1)
                    for i in range(num_days):
                        target_dates.add((start_dt + timedelta(days=i)).strftime("%Y-%m-%d"))
            except Exception as e:
                logger.warning(f"解析目标日期集合失败: {e}")

        # 预报数据映射（按 target_dates 精准日期匹配过滤）
        norm_forecast = []
        if forecast:
            for f in forecast:
                p_date = (f.get("predictDate") or f.get("foreDate") or "")[:10]
                if target_dates and p_date not in target_dates:
                    continue
                f_cond_label = f.get("conditionDay", "")
                std_f_cond = self._get_cond_type(f_cond_label)
                norm_forecast.append({
                    "date": p_date,
                    "label": f_cond_label,
                    "icon": std_f_cond,
                    "condition": std_f_cond,
                    "temp_high": int(f.get("tempDay", 0)),
                    "temp_low": int(f.get("tempNight", 0)),
                    "humidity": int(f.get("humidity", 0)),
                    "wind_direction": f.get("windDirDay"),
                    "wind_level": f.get("windLevelDay"),
                    "vis": f"{round(int(f.get('vis', 10000)) / 1000, 1)}km" if f.get('vis') else "10km",
                    "uv_index": f.get("uvi", "1"),
                    "pressure": f.get("pressure", "1013")
                })

        if current:
            summary = f"正在为您播报：目前{city}天气{current['label']}，气温{current['temp_c']}度。"
            if norm_forecast:
                today_fc = norm_forecast[0]
                summary += f"今日最高气温{today_fc['temp_high']}度，最低气温{today_fc['temp_low']}度。"
        elif norm_forecast:
            summary = f"正在为您播报：{city}的预报。"
            first_fc = norm_forecast[0]
            summary += f"今日{first_fc['label']}，最高气温{first_fc['temp_high']}度，最低气温{first_fc['temp_low']}度。"
            if len(norm_forecast) > 1:
                summary += f" 等未来{len(norm_forecast)}天预报。"
        else:
            summary = f"已为您查询{city}的天气预警信息。"

        # 拼接预警摘要
        if alert_summary_bits:
            alerts_str = "、".join(alert_summary_bits)
            summary = f"注意：气象台已发布 {alerts_str}！" + summary

        result = {
            "city": city,
            "poi_name": poi_name or city,
            "province": pname,
            "cityname": cityname,
            "adname": adname,
            "date": date,
            "lng": lon,   # 经度，供前端地图直接定位
            "lat": lat,   # 纬度，供前端地图直接定位
            "forecast": norm_forecast,
            "alerts": norm_alerts,
            "summary": summary
        }
        
        if current:
            result["current"] = current

        return result

    def _get_cond_type(self, cond_str: str) -> str:
        if not cond_str:
            return "sunny"
        if any(k in cond_str for k in ["雷", "雷阵", "强对流"]): return "thunderstorm"
        if "雨" in cond_str: return "rainy"
        if any(k in cond_str for k in ["雪", "冻"]): return "snowy"
        if any(k in cond_str for k in ["雾", "霾", "沙尘", "扬沙"]): return "foggy"
        if "阴" in cond_str: return "overcast"
        if any(k in cond_str for k in ["云", "多云", "少云", "晴间"]): return "cloudy"
        return "sunny"


class WeatherService:
    def __init__(self, source: Optional[str] = None):
        self._client = httpx.AsyncClient(timeout=10.0, follow_redirects=True)
        self.set_source(source or DEFAULT_WEATHER_SOURCE)
        self._history_disasters = self._load_history_disasters()
        self._jiashan_proxy = JiashanProxyProvider()
        self._cache: Dict[str, tuple] = {}  # 15 分钟内存 LRU 天气 Cache (0ms 响应)
        self._cache_ttl = 900               # 900 秒

    def set_source(self, source: str):
        source = source.lower()
        self._providers = []
        if source == "fengyu":
            self._providers = [WindRainSentinelProvider()]
        elif source == "moji":
            self._providers = [MojiProvider()]
        else:
            self._providers = [MojiProvider(), WindRainSentinelProvider()]
        self._history_disasters = self._load_history_disasters()

    def _load_history_disasters(self) -> Dict[str, List[Dict]]:
        if os.path.exists(HISTORY_DISASTERS_PATH):
            try:
                with open(HISTORY_DISASTERS_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载历史灾情数据失败: {e}")
        return {}

    async def get_weather(self, city: str, date: str, days: int = 1, query_types: Optional[List[str]] = None, date_end: Optional[str] = None, lon: Optional[float] = None, lat: Optional[float] = None) -> Optional[Dict]:
        cache_key = f"{city}_{date}_{days}_{date_end}"
        now_ts = time.time()
        if cache_key in self._cache:
            cached_data, expire_at = self._cache[cache_key]
            if now_ts < expire_at:
                logger.info(f"🎯 [Weather Cache] 命中 15 分钟内存天气缓存 '{cache_key}' -> 0ms 零延迟返回")
                return cached_data

        real_lon, real_lat, area_name, pname, cityname, poi_name = lon, lat, city, None, None, city
        if (real_lon is None or real_lat is None) and amap_service:
            try:
                real_lon, real_lat, area_name, pname, cityname, adname, poi_name = await amap_service.get_poi_coordinates(city)
                logger.info(f"[WeatherService] 高德地理编码解析: {city} -> {area_name} ({real_lon}, {real_lat}, {pname}, {cityname})")
            except Exception as e:
                logger.warning(f"[WeatherService] 高德地理编码调用或解包失败: {e}")

        is_linzhi = any(k in (area_name or "") for k in ["林芝", "西藏林芝", "林芝地区", "林芝市"])
        if USE_MOCK_WEATHER and generate_mock_weather and is_linzhi:
            logger.info(f"🎯 命中林芝 Demo 注入逻辑 (地名: {area_name})")
            return generate_mock_weather(area_name or city, date, days, lng=real_lon, lat=real_lat)

        result = None
        for provider in self._providers:
            result = await provider.get_weather(city, date, days, query_types, date_end=date_end, lon=real_lon, lat=real_lat)
            if result:
                self._cache[cache_key] = (result, now_ts + self._cache_ttl)
                break

        if result:
            lookup_city = result.get("cityname")
            area_name = result.get("city")
            
            pname = result.get("province", "")
            cityname = result.get("cityname", "")
            adname = result.get("adname", "")
            poi_name = result.get("poi_name", "")

            if adname and poi_name:
                if poi_name == cityname or (not poi_name.endswith('市') and f"{poi_name}市" == cityname):
                    result["city"] = cityname
                elif adname in poi_name:
                    result["city"] = poi_name
                else:
                    result["city"] = f"{adname}{poi_name}"
            elif poi_name:
                result["city"] = poi_name
            elif adname:
                result["city"] = adname
            elif cityname:
                result["city"] = cityname

            return result

    async def get_aqi(self, city: str) -> Optional[Dict]:
        """获取详细空气质量数据"""
        if not amap_service: return None
        try:
            lon, lat, area_name, pname, cityname, adname, poi_name = await amap_service.get_poi_coordinates(city)
            if lon is None or lat is None: return None
            
            if moji_service:
                return await moji_service.get_aqi(lat, lon)
        except Exception as e:
            logger.error(f"[WeatherService] 获取 AQI 失败: {e}")
        return None

    async def get_life_index(self, city: str) -> Optional[Dict]:
        """获取生活指数数据"""
        if not amap_service: return None
        try:
            lon, lat, area_name, pname, cityname, adname, poi_name = await amap_service.get_poi_coordinates(city)
            if lon is None or lat is None: return None
            
            if moji_service:
                return await moji_service.get_index(lat, lon)
        except Exception as e:
            logger.error(f"[WeatherService] 获取生活指数失败: {e}")
        return None

    def _find_history(self, name: str) -> Optional[List[Dict]]:
        """在历史灾情字典中进行模糊匹配"""
        if not name:
            return None
        
        if name in self._history_disasters:
            return self._history_disasters[name]
        
        clean_name = re.sub(r"^(北京市|天津市|上海市|重庆市|河北省|山西省|辽宁省|吉林省|黑龙江省|江苏省|浙江省|安徽省|福建省|江西省|山东省|河南省|湖北省|湖南省|广东省|海南省|四川省|贵州省|云南省|陕西省|甘肃省|青海省|台湾省|内蒙古自治区|广西壮族自治区|西藏自治区|宁夏回族自治区|新疆维吾尔自治区|香港特别行政区|澳门特别行政区)", "", name)
        if not clean_name:
            return None
        
        if clean_name != name and clean_name in self._history_disasters:
            return self._history_disasters[clean_name]
            
        short_name = re.sub(r"(省|市|自治区|特别行政区|回族自治区|壮族自治区|维吾尔自治区|盟|地区)$", "", clean_name)
        for k in self._history_disasters.keys():
            if short_name in k:
                return self._history_disasters[k]
        
        return None

    async def get_pro_weather(self, city: str, elements: List[str]) -> Dict[str, Any]:
        """获取专业气象要素数据（支持嘉善）"""
        results = {}
        if not any(k in city for k in ["嘉善", "JIASHAN"]):
            return {"status": "error", "msg": "目前专业气象要素查询仅支持嘉善地区。"}

        for ele in elements:
            data = await self._jiashan_proxy.get_pro_data(ele)
            if data:
                results[ele] = data
        
        if results:
            summary = f"已为您查询到嘉善的专业气象数据："
            bits = []
            for k, v in results.items():
                unit = ""
                if "temp" in k: unit = "℃"
                elif "rain" in k: unit = "mm"
                elif "wind" in k: unit = "m/s"
                elif "humidity" in k: unit = "%"
                elif "visibility" in k: unit = "m"
                bits.append(f"{v['name']}: {v['value']}{unit}")
            summary += "、".join(bits) + "。"
            return {"status": "success", "data": results, "summary": summary}
        
        return {"status": "error", "msg": "未查询到相关的专业气象数据，可能是当前时段无数据。"}

    async def get_history_disasters(self, city: str) -> List[Dict]:
        """获取指定城市的历史灾情数据（独立接口）"""
        logger.info(f"[WeatherService] 正在查询历史灾情: city='{city}'")
        real_lon, real_lat, area_name, pname, cityname, adname, poi_name = None, None, city, None, None, None, city
        if amap_service:
            try:
                real_lon, real_lat, area_name, pname, cityname, adname, poi_name = await amap_service.get_poi_coordinates(city)
                logger.info(f"[WeatherService] 灾情查询地理编码解析: {city} -> {area_name} ({real_lon}, {real_lat})")
            except Exception as e:
                logger.warning(f"[WeatherService] 灾情地理编码调用失败: {e}")

        # 使用高德返回的城市名字或原始城市名字进行模糊查找
        lookup_city = cityname or area_name or city
        history = self._find_history(lookup_city)
        if not history and area_name:
            history = self._find_history(area_name)
            
        logger.info(f"[WeatherService] 历史灾情查询结果 ({city}): 找到 {len(history or [])} 条记录")
        return history or []

    async def close(self):
        await self._client.aclose()


# 全局单例
weather_service = WeatherService()
