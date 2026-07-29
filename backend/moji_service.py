import httpx
import asyncio
import json
from typing import Dict, Any, Optional, List
import logging
import datetime

logger = logging.getLogger("xiaoan.moji")

# 防御指南对照表
DEFENSE_GUIDE = {
    "1": "增加室内活动", "2": "多做运动", "3": "准备药品", "4": "储备物资", "5": "注意防晒",
    "6": "防暑降温", "7": "防寒保暖", "8": "节约用水", "9": "小心坠物", "10": "关闭门窗",
    "11": "加固门窗", "12": "切断电源", "13": "注意防火", "14": "不用手机", "15": "不戴耳机",
    "16": "注意防护", "17": "携带雨具", "18": "小心驾驶", "19": "关注路况", "20": "公交出行",
    "21": "地铁出行", "22": "远离广告牌", "23": "远离树木", "24": "注意防滑", "25": "减少污水排放",
    "26": "不乱扔烟头", "27": "轮渡停航", "28": "船舶回港", "29": "船舶固锚", "30": "多喝热水",
    "31": "佩戴口罩", "0": "暂无建议"
}

# 预警等级颜色映射 (用于 UI 主题切换)
ALERT_LEVEL_COLORS = {
    "蓝色": "#2E5BFF",
    "黄色": "#E6B800",
    "橙色": "#FF8C00",
    "红色": "#FF3B30",
    "DEFAULT": "#8E8E93"
}

def _compact_json(data: Any, max_len: int = 200) -> str:
    """优雅折叠长 JSON 日志，保留关键开头发拉与总字符数摘要，避免刷屏"""
    raw_str = json.dumps(data, ensure_ascii=False)
    if len(raw_str) <= max_len:
        return raw_str
    return f"{raw_str[:max_len]}... [已折叠，全文共 {len(raw_str)} 字符]"


class MojiWeatherService:
    """墨迹天气 API 服务封装"""
    
    def __init__(self, appcode: str, tokens: Dict[str, str]):
        self.host = "https://aliv8.data.moji.com"
        self.appcode = appcode
        self.tokens = tokens
        self.headers = {
            "Authorization": f"APPCODE {appcode}",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
        }

    async def get_condition(self, lat: float, lon: float, days: int = 1, target_date: str = None) -> Optional[Dict[str, Any]]:
        """获取实时天气情况，自带基于查询目标的滤除机制"""
        import datetime
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        
        # 核心去重逻辑收敛在此：如果查的是未来多天，或者是未来非今日天气，彻底不发起实况请求并滤除 current
        if (days > 1) or (target_date and target_date != today_str):
            logger.info("[MojiService] 滤除：因查询多日或未来天气，主动舍弃 current 数据请求。")
            return None
            
        data = {
            "lat": str(lat),
            "lon": str(lon),
            "token": self.tokens.get("condition")
        }
        try:
            async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
                url = f"{self.host}/whapi/json/aliweather/condition"
                logger.info(f"[API Call] 墨迹天气-实况天气 -> POST {url} | 参数: {json.dumps(data, ensure_ascii=False)}")
                response = await client.post(url, data=data, headers=self.headers)
                result = response.json()
                logger.info(f"[API Response] 实况天气返回: {_compact_json(result)}")
                if result.get("code") == 0:
                    data = result.get("data", {})
                    current_condition = data.get("condition", {})
                    return current_condition
                logger.error(f"[MojiService] 获取实时天气失败: {result}")
                return None
        except Exception as e:
            logger.error(f"[MojiService] 实时天气请求异常: {e}")
            return None

    async def get_forecast(self, lat: float, lon: float, days: int = 15, target_date: str = None) -> Optional[List[Dict[str, Any]]]:
        """获取多日预报，并支持按目标日期截断"""
        data = {
            "lat": str(lat),
            "lon": str(lon),
            "token": self.tokens.get("forecast15days")
        }
        try:
            async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
                url = f"{self.host}/whapi/json/aliweather/forecast15days"
                logger.info(f"[API Call] 墨迹天气-天气预报 -> POST {url} | 参数: {json.dumps(data, ensure_ascii=False)}")
                response = await client.post(url, data=data, headers=self.headers)
                result = response.json()
                logger.info(f"[API Response] 天气预报返回: {_compact_json(result)}")
                if result.get("code") == 0:
                    forecasts = result.get("data", {}).get("forecast", [])
                    
                    # 确定起始日期：优先用传入的，否则默认为今天
                    lookup_date = target_date or datetime.datetime.now().strftime("%Y-%m-%d")
                    
                    # 从匹配日期开始截取，取 days 长度
                    filtered_forecasts = []
                    started = False
                    for f in forecasts:
                        if f.get("predictDate") == lookup_date:
                            started = True
                        
                        if started:
                            filtered_forecasts.append(f)
                            if len(filtered_forecasts) >= days:
                                break
                    
                    # 如果未找到匹配日期且没有传入 target_date，落回原始逻辑（通常不应发生）
                    if not filtered_forecasts and not target_date:
                        return forecasts[:days]
                                
                    return filtered_forecasts
                    
                logger.error(f"[MojiService] 获取预报失败: {result}")
                return None
        except Exception as e:
            logger.error(f"[MojiService] 预报请求异常: {e}")
            return None

    async def get_alerts(self, lat: float, lon: float) -> List[Dict[str, Any]]:
        """获取天气预警信息"""
        data = {
            "lat": str(lat),
            "lon": str(lon),
            "token": self.tokens.get("alert")
        }
        try:
            async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
                url = f"{self.host}/whapi/json/aliweather/alert"
                logger.info(f"[API Call] 墨迹天气-天气预警 -> POST {url} | 参数: {json.dumps(data, ensure_ascii=False)}")
                response = await client.post(url, data=data, headers=self.headers)
                result = response.json()
                logger.info(f"[API Response] 天气预警返回: {json.dumps(result, ensure_ascii=False)}")
                logger.info(f"[MojiService] 预警响应: code={result.get('code')}, alerts={result.get('data', {}).get('alert', [])}")
                
                if result.get("code") == 0:
                    alerts = result.get("data", {}).get("alert", [])
                    # 即使是空的也要返回列表
                    return alerts
                
                logger.error(f"[MojiService] 获取预警失败: {result}")
                return []
        except Exception as e:
            logger.error(f"[MojiService] 预警请求异常: {e}")
            return []

    async def get_aqi(self, lat: float, lon: float) -> Optional[Dict[str, Any]]:
        """获取详细空气质量 (AQI) 信息"""
        data = {
            "lat": str(lat),
            "lon": str(lon),
            "token": self.tokens.get("aqi")
        }
        try:
            async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
                url = f"{self.host}/whapi/json/aliweather/aqi"
                response = await client.post(url, data=data, headers=self.headers)
                result = response.json()
                logger.info(f"[MojiService] AQI 响应: code={result.get('code')}")
                
                if result.get("code") == 0:
                    return result.get("data", {}).get("aqi", {})
                
                logger.error(f"[MojiService] 获取 AQI 失败: {result}")
                return None
        except Exception as e:
            logger.error(f"[MojiService] AQI 请求异常: {e}")
            return None

    async def get_index(self, lat: float, lon: float) -> Optional[List[Dict[str, Any]]]:
        """获取生活指数 (Life Index) 信息"""
        data = {
            "lat": str(lat),
            "lon": str(lon),
            "token": self.tokens.get("index")
        }
        try:
            async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
                url = f"{self.host}/whapi/json/aliweather/index"
                response = await client.post(url, data=data, headers=self.headers)
                result = response.json()
                logger.info(f"[MojiService] 生活指数响应: code={result.get('code')}")
                
                if result.get("code") == 0:
                    # 返回 liveIndex 节点下的数据（通常是按日期组织的字典）
                    live_index = result.get("data", {}).get("liveIndex", {})
                    # 如果需要，这里可以进一步展平或筛选，但我们目前先返回原始结构
                    return live_index
                
                logger.error(f"[MojiService] 获取生活指数失败: {result}")
                return None
        except Exception as e:
            logger.error(f"[MojiService] 生活指数请求异常: {e}")
            return None

    def format_defense_guide(self, ids_str: str) -> List[str]:
        """将逗号分隔的防御指南 ID 转换为文字列表"""
        if not ids_str:
            return []
        ids = ids_str.replace(" ", "").split(",")
        guides = []
        for d_id in ids:
            if d_id in DEFENSE_GUIDE:
                guides.append(DEFENSE_GUIDE[d_id])
        # 去重并保持顺序
        return list(dict.fromkeys(guides))

    def get_alert_color(self, level: str) -> str:
        """根据预警等级获取对应颜色"""
        return ALERT_LEVEL_COLORS.get(level, ALERT_LEVEL_COLORS["DEFAULT"])

import os
from dotenv import load_dotenv

# 预加载
load_dotenv()

# 从环境变量读取
MOJI_APPCODE = os.environ.get("MOJI_APPCODE", "e9c804cad2534f2a8cd37d98ca509b29")
MOJI_TOKEN_CONDITION = os.environ.get("MOJI_TOKEN_CONDITION", "ff826c205f8f4a59701e64e9e64e01c4")
MOJI_TOKEN_FORECAST = os.environ.get("MOJI_TOKEN_FORECAST", "7538f7246218bdbf795b329ab09cc524")
MOJI_TOKEN_ALERT = os.environ.get("MOJI_TOKEN_ALERT", "d01246ac6284b5a591f875173e9e2a18")
MOJI_TOKEN_AQI = os.environ.get("MOJI_TOKEN_AQI", "6e9a127c311094245fc1b2aa6d0a54fd")
MOJI_TOKEN_INDEX = os.environ.get("MOJI_TOKEN_INDEX", "42b0c7e2e8d00d6e80d92797fe5360fd")

# 全局单例
moji_service = MojiWeatherService(
    appcode=MOJI_APPCODE,
    tokens={
        "condition": MOJI_TOKEN_CONDITION,
        "forecast15days": MOJI_TOKEN_FORECAST,
        "alert": MOJI_TOKEN_ALERT,
        "aqi": MOJI_TOKEN_AQI,
        "index": MOJI_TOKEN_INDEX
    }
)
