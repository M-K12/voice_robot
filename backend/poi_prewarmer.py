"""
小安气象机器人 - 模块化城市 POI 自动预热器
架构原理：
1. 全国地级市：已完全离线静态存储在 backend/static/china_cities.json 中（不变）。
2. 当前城市：启动时自动检测 backend/static/cities/{default_city}.json 是否就绪。
   若未就绪，则向高德 API 抓取该城市的全套深度下辖单位，并保存为独立城市包 backend/static/cities/{default_city}.json。
"""

import os
import json
import logging
import asyncio
import httpx
from typing import List, Dict, Any, Tuple
from amap_service import amap_service

logger = logging.getLogger("xiaoan.poi_prewarmer")

# 知名常驻地的深度地标/乡镇扩展补充
LOCAL_FEATURE_POIS = {
    "歙县": ["歙县", "徽州古城", "阳产土楼", "棠樾牌坊群", "新安江山水画廊", "渔梁坝", "徽州区", "黄山风景区", "深渡镇", "北岸镇", "坑口乡"],
    "黄山": ["黄山市", "歙县", "徽州区", "黄山区", "屯溪区", "休宁县", "黟县", "祁门县", "黄山风景区", "宏村", "西递", "徽州古城"],
    "黄山市": ["黄山市", "歙县", "徽州区", "黄山区", "屯溪区", "休宁县", "黟县", "祁门县", "黄山风景区", "宏村", "西递", "徽州古城"],
    "成都市": ["成都市", "成都", "锦江区", "青羊区", "金牛区", "武侯区", "成华区", "龙泉驿区", "青白江区", "新都区", "温江区", "双流区", "郫都区", "新津区", "都江堰市", "彭州市", "邛崃市", "崇州市", "简阳市", "金堂县", "大邑县", "蒲江县", "天府广场", "双流机场", "天府机场", "成都东站", "锦里", "宽窄巷子", "熊猫基地", "青城山"],
    "成都": ["成都市", "成都", "锦江区", "青羊区", "金牛区", "武侯区", "成华区", "龙泉驿区", "青白江区", "新都区", "温江区", "双流区", "郫都区", "新津区", "都江堰市", "彭州市", "邛崃市", "崇州市", "简阳市", "金堂县", "大邑县", "蒲江县", "天府广场", "双流机场", "天府机场", "成都东站", "锦里", "宽窄巷子", "熊猫基地", "青城山"],
    "嘉善县": ["嘉善县", "嘉善", "罗星街道", "魏塘街道", "惠民街道", "西塘镇", "大云镇", "木窦镇", "陶庄镇", "天凝镇", "干窑镇"],
    "嘉善": ["嘉善县", "嘉善", "罗星街道", "魏塘街道", "惠民街道", "西塘镇", "大云镇", "木窦镇", "陶庄镇", "天凝镇", "干窑镇"]
}

async def fetch_city_deep_pois(city_name: str) -> Dict[str, Tuple]:
    """
    通过高德官方行政区划 API (v3/config/district) 深度抓取某一特定城市的全套下辖区县/街道/镇坐标。
    """
    url = "https://restapi.amap.com/v3/config/district"
    api_key = amap_service._api_key
    city_clean = city_name.strip()
    
    local_cache = {}

    # 1. 向高德请求该城市的区划树
    search_terms = [city_clean]
    if not city_clean.endswith("市") and not city_clean.endswith("县") and not city_clean.endswith("区"):
        search_terms.extend([f"{city_clean}县", f"{city_clean}市", f"{city_clean}区"])

    for term in search_terms:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, params={"key": api_key, "keywords": term, "subdistrict": 2, "extensions": "base"})
                data = resp.json()
                if data.get("status") == "1" and data.get("districts"):
                    def _traverse(nodes):
                        for node in nodes:
                            name = node.get("name", "")
                            center = node.get("center", "")
                            if name and center and "," in center:
                                lon, lat = map(float, center.split(","))
                                formatted = f"{city_clean}{name}" if name != city_clean else city_clean
                                local_cache[f"{name}_{city_clean}"] = (lon, lat, formatted, "", city_clean, name, name)
                                local_cache[f"{name}_"] = (lon, lat, formatted, "", city_clean, name, name)
                            sub = node.get("districts", [])
                            if sub:
                                _traverse(sub)
                    _traverse(data["districts"])
        except Exception as e:
            logger.warning(f"[POI Prewarmer] 抓取 [{term}] 行政区划失败: {e}")

    # 2. 补充该城市的名胜景点与地标 POI
    features = list(dict.fromkeys([city_clean] + LOCAL_FEATURE_POIS.get(city_clean, [])))
    for feat in features:
        try:
            lon, lat, formatted, pname, cname, adname, poi = await amap_service.get_poi_coordinates(feat, city=city_clean)
            if lon and lat:
                local_cache[f"{feat}_{city_clean}"] = (lon, lat, formatted, pname, cname, adname, poi)
                local_cache[f"{feat}_"] = (lon, lat, formatted, pname, cname, adname, poi)
        except Exception as e:
            logger.warning(f"[POI Prewarmer] 获取特色地标 '{feat}' 坐标失败: {e}")
        await asyncio.sleep(0.05)

    return local_cache

async def prewarm_city_pois(default_city: str):
    """
    检查并自动为 default_city 建立独立城市包 (backend/static/cities/{default_city}.json)。
    完全模块化设计。
    """
    if not default_city:
        return

    city_clean = default_city.strip()
    cities_dir = os.path.join(os.path.dirname(__file__), "static", "cities")
    os.makedirs(cities_dir, exist_ok=True)
    
    city_file_path = os.path.join(cities_dir, f"{city_clean}.json")

    # 若独立城市包已存在，则零延迟完成校验
    if os.path.exists(city_file_path):
        return

    logger.info(f"🔄 [POI Prewarmer] 未检测到城市包 [{city_clean}.json]，启动高德 API 抓取并建立专属深度城市包...")

    deep_pois = await fetch_city_deep_pois(city_clean)
    if deep_pois:
        try:
            with open(city_file_path, "w", encoding="utf-8") as f:
                json.dump(deep_pois, f, ensure_ascii=False, indent=2)
            logger.info(f"✨ [POI Prewarmer] 成功为您自动建立城市包 [backend/static/cities/{city_clean}.json]，包含 {len(deep_pois)} 条深层节点！")
            
            # 更新 amap_service 内存缓存
            amap_service._cache.update(deep_pois)
        except Exception as e:
            logger.warning(f"[POI Prewarmer] 写入城市包 [{city_clean}.json] 失败: {e}")
