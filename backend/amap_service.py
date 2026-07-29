"""
小安气象机器人 - 高德地图位置服务适配器
用于将语音识别结果或模糊地点名称（含错别字），转化为精确经纬度，给墨迹天气作为入参。
选用 v3/place/text (关键字搜索 API) 是因为它对错别字（如同音字“西细湿地”）有极强的容错能力。
"""

import os
import logging
import httpx
from typing import Tuple, Optional

logger = logging.getLogger("xiaoan.amap")

class AmapService:
    def __init__(self):
        # 兼容环境变量加载或默认硬编码
        self._api_key = os.environ.get("AMAP_API_KEY", "632818b50e4e810bde8b15902489e6cb")
        
        # httpx does not support brackets or CIDR suffixes for IPv6 in NO_PROXY. Sanitize it first.
        no_proxy = os.environ.get("NO_PROXY", "")
        if no_proxy:
            parts = []
            for part in no_proxy.split(","):
                part = part.strip()
                if not part:
                    continue
                if ":" in part:
                    part = part.replace("[", "").replace("]", "")
                    if "/" in part:
                        part = part.split("/", 1)[0]
                if part and part not in parts:
                    parts.append(part)
            os.environ["NO_PROXY"] = ",".join(parts)
            
        self._client = httpx.AsyncClient(timeout=10.0, follow_redirects=True)
        self._url = "https://restapi.amap.com/v3/place/text"
        
    async def get_poi_coordinates(self, address: str, city: Optional[str] = None) -> Tuple[Optional[float], Optional[float], Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]]:
        """
        根据地点名称查询 POI 的经纬度
        :param address: 待查询的精确或者模糊地点（可含常驻城市前缀）
        :param city: (可选) 限定请求的常驻城市，进一步收敛歧义
        :return: (lon, lat, formatted_name, pname, cityname, adname, poi_name) 如果失败或没有结果，返回 (None, None, None, None, None, None, None)
        """
        if not address:
            return None, None, None, None, None, None, None
            
        params = {
            "key": self._api_key,
            "keywords": address,
            "offset": 1,  # 只要匹配度最高的第一条
            "page": 1,
            "extensions": "base"
        }
        
        # 如果需要传入上下文城市来限定，可以释放这里
        # if city:
        #     params["city"] = city
            
        try:
            response = await self._client.get(self._url, params=params)
            response.raise_for_status()
            result = response.json()
            
            if result.get("status") == "1" and int(result.get("count", 0)) > 0:
                pois = result.get("pois", [])
                if pois:
                    best_match = pois[0]
                    location = best_match.get("location", "")
                    poi_name = best_match.get("name", address)
                    pname = best_match.get("pname", "")
                    cityname = best_match.get("cityname", "")
                    adname = best_match.get("adname", "")
                    
                    # 增强清理逻辑：高德某些 POI 名中会带有 '*' 作为内部分隔符，直接优化掉
                    if poi_name and isinstance(poi_name, str) and "*" in poi_name:
                        poi_name = poi_name.replace("*", " · ")
                    
                    pname = pname if isinstance(pname, str) else ""
                    cityname = cityname if isinstance(cityname, str) else ""
                    adname = adname if isinstance(adname, str) else ""
                    
                    # 智能拼接处理机制，过滤直接查询“行政区划”时的信息冗余
                    # 例如用户搜 "贵阳"，Amap可能返回 pname=贵州省, cityname=贵阳市, adname=观山湖区, name=贵阳市
                    # 此时如果不加判断直接拼合，会导致出现“贵州省贵阳市观山湖区贵阳市”这样反人类的播报
                    if poi_name == cityname or poi_name + "市" == cityname:
                        formatted_name = f"{pname}{cityname}"
                    elif poi_name == adname or poi_name + "区" == adname or poi_name + "县" == adname:
                        formatted_name = f"{pname}{cityname}{adname}"
                    elif poi_name == pname or poi_name + "省" == pname:
                        formatted_name = pname
                    else:
                        clean_poi_name = poi_name
                        # 如果 poi_name 已经包含了地名信息，则不再重复拼接
                        if clean_poi_name.startswith(pname) and pname:
                            clean_poi_name = clean_poi_name[len(pname):]
                        if clean_poi_name.startswith(cityname) and cityname:
                            clean_poi_name = clean_poi_name[len(cityname):]
                        if clean_poi_name.startswith(adname) and adname:
                            clean_poi_name = clean_poi_name[len(adname):]
                            
                        # 构造多级地址前缀，用于播报
                        full_name_prefix = ""
                        if pname: full_name_prefix += pname
                        if cityname and cityname != pname: full_name_prefix += cityname
                        if adname and adname != cityname: full_name_prefix += adname
                        
                        formatted_name = f"{full_name_prefix}{clean_poi_name}"
                    
                    if location and "," in location:
                        lon_str, lat_str = location.split(",")
                        logger.info(f"[高德POI] 命中: {formatted_name} => ({lon_str}, {lat_str})")
                        return float(lon_str), float(lat_str), formatted_name, pname, cityname, adname, poi_name
                        
            # 如果走到了这里说明查询不到有效信息
            error_info = result.get("info", "未查找到相关结果")
            logger.warning(f"[高德POI] 地址 '{address}' 定位失败: {error_info}")
            return None, None, None, None, None, None, None
            
        except Exception as e:
            logger.exception(f"[高德POI] 网络或解析异常: {e}")
            return None, None, None, None, None, None, None

    async def close(self):
        await self._client.aclose()

# 暴露一个单例实例供全局使用
amap_service = AmapService()
