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
        self._cache_file = os.path.join(os.path.dirname(__file__), "static", "poi_cache.json")
        self._cache = self._load_disk_cache()

    def _load_disk_cache(self) -> dict:
        """
        分模块极速合并 POI 缓存:
        1. 基础包：backend/static/china_cities.json (全国 800+ 地级市主节点，永恒不变)
        2. 当地专属包：backend/static/cities/{default_city}.json (当前常驻城市/县深度下辖节点)
        """
        cache = {}
        static_dir = os.path.join(os.path.dirname(__file__), "static")
        
        # 1. 加载全国所有地级市 (china_cities.json)
        china_cities_path = os.path.join(static_dir, "china_cities.json")
        if os.path.exists(china_cities_path):
            try:
                import json
                with open(china_cities_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for k, v in data.items():
                        if isinstance(v, list) and len(v) == 7:
                            cache[k] = tuple(v)
            except Exception as e:
                logger.warning(f"[高德POI] 加载全国地级市缓存 (china_cities.json) 失败: {e}")

        # 2. 读取 configs/global.json 获取 default_city 并加载对应专属城市的 cities/{default_city}.json
        try:
            import json
            config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "configs", "global.json")
            default_city = "歙县"
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    default_city = cfg.get("default_city", "歙县")
            
            city_json_path = os.path.join(static_dir, "cities", f"{default_city}.json")
            if os.path.exists(city_json_path):
                with open(city_json_path, "r", encoding="utf-8") as f:
                    local_data = json.load(f)
                    for k, v in local_data.items():
                        if isinstance(v, list) and len(v) == 7:
                            cache[k] = tuple(v)
        except Exception as e:
            logger.warning(f"加载当前城市专属POI缓存失败: {e}")

        logger.info("POI 缓存装载完毕")
        return cache

    def _save_disk_cache(self):
        """将运行时新增的 POI 动态追加写盘至当前城市的专属 JSON 包中"""
        try:
            import json
            config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "configs", "global.json")
            default_city = "歙县"
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    default_city = cfg.get("default_city", "歙县")
                    
            cities_dir = os.path.join(os.path.dirname(__file__), "static", "cities")
            os.makedirs(cities_dir, exist_ok=True)
            city_json_path = os.path.join(cities_dir, f"{default_city}.json")
            
            # 读取已有的专属包数据，合并新追加的 POI
            existing_local = {}
            if os.path.exists(city_json_path):
                try:
                    with open(city_json_path, "r", encoding="utf-8") as f:
                        existing_local = json.load(f)
                except Exception:
                    pass
            
            # 将内存中属于当地的新 POI 追加存入
            for k, v in self._cache.items():
                if default_city in k or default_city in str(v):
                    existing_local[k] = list(v)

            with open(city_json_path, "w", encoding="utf-8") as f:
                json.dump(existing_local, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[高德POI] 写入城市 [{default_city}] 专属磁盘缓存失败: {e}")
        
    async def get_poi_coordinates(self, address: str, city: Optional[str] = None) -> Tuple[Optional[float], Optional[float], Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]]:
        """
        根据地点名称查询 POI 的经纬度
        :param address: 待查询的精确或者模糊地点（可含常驻城市前缀）
        :param city: (可选) 限定请求的常驻城市，进一步收敛歧义
        :return: (lon, lat, formatted_name, pname, cityname, adname, poi_name) 如果失败或没有结果，返回 (None, None, None, None, None, None, None)
        """
        if not address:
            return None, None, None, None, None, None, None

        cache_key = f"{address.strip().lower()}_{city or ''}"
        if cache_key in self._cache:
            logger.info(f"位置校验完成➡️  {address}")
            return self._cache[cache_key]
            
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
                        res = (float(lon_str), float(lat_str), formatted_name, pname, cityname, adname, poi_name)
                        self._cache[cache_key] = res
                        self._save_disk_cache()
                        return res
                        
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
