import httpx
import asyncio
import json
from typing import Dict, Any, Optional, List
import logging
import datetime
import os
from dotenv import load_dotenv

# 预加载
load_dotenv()

logger = logging.getLogger("xiaoan.fengyu")

def _compact_json(data: Any, max_len: int = 200) -> str:
    """优雅折叠长 JSON 日志，保留关键开头发拉与总字符数摘要，避免刷屏"""
    raw_str = json.dumps(data, ensure_ascii=False)
    if len(raw_str) <= max_len:
        return raw_str
    return f"{raw_str[:max_len]}... [已折叠，全文共 {len(raw_str)} 字符]"


class FengyuWeatherService:
    """风雨哨兵天气 API 服务封装"""
    
    def __init__(self, token: str):
        self.host = "https://guardapi.weatherone.net"
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}"
        }

    async def get_condition(self, lat: float, lon: float) -> Optional[Dict[str, Any]]:
        """获取日天气实况数据"""
        data = {
            "longitude": str(lon),
            "latitude": str(lat)
        }
        try:
            async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
                url = f"{self.host}/api/meteo/weather/getWeatherObsDayByPoint"
                logger.info(f"[API Call] 风雨哨兵-天气实况 -> POST {url} | 参数: {json.dumps(data, ensure_ascii=False)}")
                response = await client.post(url, data=data, headers=self.headers)
                result = response.json()
                logger.info(f"[API Response] 天气实况返回: {_compact_json(result)}")
                logger.info(f"[FengyuService] 实况响应: code={result.get('code')}, msg={result.get('msg')}")
                if result.get("code") == 0:
                     return result.get("data", {})
                logger.error(f"[FengyuService] 获取实况失败: {result}")
                return None
        except Exception as e:
            logger.error(f"[FengyuService] 实况请求异常: {e}")
            return None

    async def get_forecast(self, lat: float, lon: float, days: int = 14) -> Optional[List[Dict[str, Any]]]:
        """获取日天气预报数据"""
        data = {
            "longitude": str(lon),
            "latitude": str(lat),
            "days": str(days)
        }
        try:
            async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
                url = f"{self.host}/api/meteo/weather/getWeatherForeDayByPoint"
                logger.info(f"[API Call] 风雨哨兵-天气预报 -> POST {url} | 参数: {json.dumps(data, ensure_ascii=False)}")
                response = await client.post(url, data=data, headers=self.headers)
                result = response.json()
                logger.info(f"[API Response] 天气预报返回: {_compact_json(result)}")
                logger.info(f"[FengyuService] 预报响应: code={result.get('code')}, msg={result.get('msg')}")
                if result.get("code") == 0:
                    return result.get("data", [])
                logger.error(f"[FengyuService] 获取预报失败: {result}")
                return None
        except Exception as e:
            logger.error(f"[FengyuService] 预报请求异常: {e}")
            return None

    async def get_alerts(self, lat: float, lon: float, date_str: str = None) -> List[Dict[str, Any]]:
        """获取天气预警信息"""
        if not date_str:
            date_str = datetime.datetime.now().strftime("%Y-%m-%d")
            
        params = {
            "longitude": str(lon),
            "latitude": str(lat),
            "dateTime": date_str
        }
        try:
            async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
                url = f"{self.host}/api/meteo/tearly/getEarlyWarnInfoByLonlat"
                print(f"\033[34m[API Call] 风雨哨兵-天气预警 -> GET {url}\033[0m")
                print(f"\033[34m[API Params] 参数: {json.dumps(params, ensure_ascii=False)}\033[0m")
                response = await client.get(url, params=params, headers=self.headers)
                result = response.json()
                print(f"\033[32m[API Response] 天气预警返回: {json.dumps(result, ensure_ascii=False)}\033[0m")
                logger.info(f"[FengyuService] 预警响应: code={result.get('code')}, alerts_count={len(result.get('data', []) or [])}")
                
                if result.get("code") == 0:
                    return result.get("data") or []
                
                logger.error(f"[FengyuService] 获取预警失败: {result}")
                return []
        except Exception as e:
            logger.error(f"[FengyuService] 预警请求异常: {e}")
            return []

# 从环境变量读取
FENGYU_TOKEN = os.environ.get("FENGYU_TOKEN", "")

# 全局单例
fengyu_service = FengyuWeatherService(token=FENGYU_TOKEN)
