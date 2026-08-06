import json
import re
import time
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import WebSocket

from sse_hub import sse_hub
from weather_service import weather_service
from knowledge_service import KnowledgeService
from address_corrector import AddressCorrector
from amap_service import amap_service

logger = logging.getLogger("xiaoan.handlers")

# Initialize service singletons for tool handlers
knowledge_service = KnowledgeService()
address_corrector = AddressCorrector()

def _load_screen_layers_config() -> dict:
    """Dynamically load screen layer configurations from static/screen_layers.json."""
    config_path = Path(__file__).parent.parent / "static" / "screen_layers.json"
    if not config_path.exists():
        config_path = Path(__file__).parent.parent.parent / "backend" / "static" / "screen_layers.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {k: v for k, v in data.items() if not k.startswith("_")}
        except Exception as e:
            logger.error(f"[Handlers] Failed to load screen_layers.json: {e}")
    return {}

@dataclass
class ToolContext:
    websocket: WebSocket
    default_city: str
    expecting_weather_summary: bool = False
    session_active: bool = True

def _calculate_end_time(start_str: str, dur_str: str) -> Optional[str]:
    """Calculate date_end based on start_time and relative duration string (e.g. +1h, -24h)."""
    if not start_str or not dur_str:
        return None
    match = re.match(r'([+-])?(\d+)([hdm])', dur_str)
    if not match:
        return None
    sign = -1 if match.group(1) == '-' else 1
    val = int(match.group(2))
    unit = match.group(3)
    try:
        fmt = "%Y-%m-%d" if len(start_str) == 10 else "%Y-%m-%dT%H:%M"
        from datetime import datetime, timedelta
        start_dt = datetime.strptime(start_str, fmt)
        if unit == 'h':
            delta = timedelta(hours=sign * val)
        elif unit == 'd':
            delta = timedelta(days=sign * val)
        elif unit == 'm':
            delta = timedelta(minutes=sign * val)
        else:
            return None
        end_dt = start_dt + delta
        return end_dt.strftime(fmt)
    except Exception:
        return None

async def execute_tool(name: str, arguments_str: str, ctx: ToolContext) -> str:
    """Execute the requested tool by name with arguments in the provided context, returning the result JSON."""
    try:
        try:
            args = json.loads(arguments_str) if isinstance(arguments_str, str) else (arguments_str or {})
        except Exception:
            args = {}

        logger.info(f"[Tool Call] 🔨 {name} -> 参数: {json.dumps(args, ensure_ascii=False)}")
        if ctx.websocket: await ctx.websocket.send_json({
            "type": "debug_event",
            "step": "tool_call",
            "name": name,
            "arguments": args
        })

        if name == "get_weather_forecast":
            raw_location = args.get("location_name") or ctx.default_city
            location = address_corrector.correct(raw_location)
            if location != raw_location:
                logger.info(f"[Operation] 地址纠错: '{raw_location}' -> '{location}'")

            real_lon, real_lat = None, None
            try:
                if amap_service:
                    real_lon, real_lat, area_name, pname, cityname, adname, poi_name = await amap_service.get_poi_coordinates(location)
                    if area_name and area_name != location:
                        location = area_name
            except Exception as e:
                logger.error(f"[Error] 高德地图 POI 解析异常: {e}")

            # ⚡ 高德接口确认地理信息后，立刻无延迟推送大屏定位与经纬度悬浮！
            instant_ctrl_data = {
                "place": location,
                "lng": real_lon,
                "lat": real_lat,
                "elements": args.get("elements", ""),
                "elements_colloquial": args.get("elements_colloquial", "")
            }
            try:
                from visual_manager import visual_broadcast_manager
                await visual_broadcast_manager.broadcast({"type": "control_command", "data": instant_ctrl_data})
                if real_lon and real_lat:
                    await visual_broadcast_manager.broadcast({"type": "query_info", "data": {"lonLat": [real_lon, real_lat], "address": location}})
            except Exception as e:
                logger.error(f"[Handlers] Immediate POI broadcast failed: {e}")

            original_date = args.get("date", "")
            raw_date = address_corrector.correct_general(original_date)
            if raw_date != original_date:
                logger.info(f"[Operation] 日期关键字纠错: '{original_date}' -> '{raw_date}'")
            from datetime import datetime, timedelta
            
            def parse_colloquial_date(d_str: str) -> str:
                d_str = d_str.strip()
                if not d_str:
                    return ""
                import re
                if re.match(r"^\d{4}-\d{2}-\d{2}", d_str):
                    return d_str[:10]
                now_dt = datetime.now()
                if "今" in d_str:
                    return now_dt.strftime("%Y-%m-%d")
                elif "明" in d_str:
                    return (now_dt + timedelta(days=1)).strftime("%Y-%m-%d")
                elif "后" in d_str:
                    return (now_dt + timedelta(days=2)).strftime("%Y-%m-%d")
                elif "昨" in d_str:
                    return (now_dt - timedelta(days=1)).strftime("%Y-%m-%d")
                elif "前" in d_str:
                    return (now_dt - timedelta(days=2)).strftime("%Y-%m-%d")
                return d_str

            start_time_str = parse_colloquial_date(raw_date)
            end_time_str = args.get("date_end", "")
            duration_str = args.get("duration", "")
            req_elem = args.get("elements", "")
            days_val = args.get("days", 1)
            query_types = args.get("query_types", None)

            if duration_str and not end_time_str:
                end_time_str = _calculate_end_time(start_time_str, duration_str)

            ctrl_data = {
                "place": location,
                "lng": real_lon,
                "lat": real_lat,
                "time_colloquial": args.get("time_colloquial", ""),
                "time_standard": start_time_str,
                "time_standard_end": end_time_str,
                "duration": duration_str,
                "elements": req_elem,
                "elements_colloquial": args.get("elements_colloquial", "")
            }
            await sse_hub.broadcast("control_command", ctrl_data)
            if ctx.websocket:
                await ctx.websocket.send_json({
                    "type": "debug_event",
                    "step": "control",
                    "content": f"推送大屏控制指令: 展示 {location} 天气信息",
                    "arguments": ctrl_data
                })
            if real_lon and real_lat:
                await sse_hub.broadcast("query_info", {"lonLat": [real_lon, real_lat], "address": location})

            date_str = start_time_str.split("T")[0] if start_time_str else ""
            weather_data = await weather_service.get_weather(
                city=location,
                date=date_str,
                days=days_val,
                query_types=query_types,
                date_end=end_time_str,
                lon=real_lon,
                lat=real_lat
            )
            if weather_data:
                if ctx.websocket: await ctx.websocket.send_json({"type": "weather_data", "city": location, "data": weather_data})
                ctx.expecting_weather_summary = True
                try:
                    from visual_manager import visual_broadcast_manager
                    import asyncio
                    asyncio.create_task(visual_broadcast_manager.broadcast({
                        "type": "weather_data",
                        "data": weather_data
                    }))
                except Exception as e:
                    logger.error(f"[Handlers] Broadcast weather_data failed: {e}")
                tool_result_content = weather_data
            else:
                tool_result_content = {
                    "status": "error",
                    "message": f"未查询到 {location} 在 {date_str} 的有效天气数据。可能因为日期超出预报范围或接口暂时不可用。"
                }

            res_json_str = json.dumps(tool_result_content, ensure_ascii=False)
            logger.info(f"[Tool Result] get_weather_forecast -> Result: {res_json_str[:220]}... [已折叠，全文共 {len(res_json_str)} 字符]" if len(res_json_str) > 220 else f"[Tool Result] get_weather_forecast -> Result: {res_json_str}")
            if ctx.websocket: await ctx.websocket.send_json({
                "type": "debug_event",
                "step": "tool_result",
                "name": name,
                "result": tool_result_content
            })

            return json.dumps(tool_result_content, ensure_ascii=False)

        elif name == "show_screen_layer":
            raw_location = args.get("location_name") or ctx.default_city
            location = address_corrector.correct(raw_location)
            if location != raw_location:
                logger.info(f"[Operation] 地图大屏地址纠错: '{raw_location}' -> '{location}'")

            raw_layer = args.get("layer_name", "")
            layer = address_corrector.correct_layer(raw_layer).strip().lower()
            if layer != raw_layer.strip().lower():
                logger.info(f"[Operation] 大屏图层纠错: '{raw_layer}' -> '{layer}'")

            screen_layers = _load_screen_layers_config()
            matched_key = None
            if layer in screen_layers:
                matched_key = layer
            else:
                for key, info in screen_layers.items():
                    keywords = info.get("keywords", [])
                    if any(isinstance(kw, str) and (kw.lower() in layer or layer in kw.lower()) for kw in keywords):
                        matched_key = key
                        break
            if matched_key:
                layer = matched_key

            real_lon, real_lat = None, None
            try:
                if amap_service:
                    real_lon, real_lat, area_name, pname, cityname, adname, poi_name = await amap_service.get_poi_coordinates(location)
                    if area_name and area_name != location:
                        location = area_name
            except Exception:
                pass

            # ⚡ 高德接口确认地理信息后，立刻无延迟推送大屏图层控制指令！
            instant_ctrl_data = {
                "place": location,
                "lng": real_lon,
                "lat": real_lat,
                "elements": layer,
                "elements_colloquial": args.get("elements_colloquial") or raw_layer,
                "type": "show_layer"
            }
            try:
                from visual_manager import visual_broadcast_manager
                await visual_broadcast_manager.broadcast({"type": "control_command", "data": instant_ctrl_data})
                if real_lon and real_lat:
                    await visual_broadcast_manager.broadcast({"type": "query_info", "data": {"lonLat": [real_lon, real_lat], "address": location}})
            except Exception as e:
                logger.error(f"[Handlers] Immediate POI broadcast failed: {e}")

            ctrl_data = {
                "place": location,
                "lng": real_lon,
                "lat": real_lat,
                "elements": layer,
                "elements_colloquial": args.get("elements_colloquial") or raw_layer,
                "type": "show_layer"
            }
            await sse_hub.broadcast("control_command", ctrl_data)
            if ctx.websocket:
                await ctx.websocket.send_json({
                    "type": "debug_event",
                    "step": "control",
                    "content": f"推送大屏控制指令: 切换到 {location} {layer} 图层",
                    "arguments": ctrl_data
                })
            if real_lon and real_lat:
                await sse_hub.broadcast("query_info", {"lonLat": [real_lon, real_lat], "address": location})

            jiashan_pro_bases = {
                "temp", "temp_max", "temp_min", "temp_avg",
                "rain", "wind", "wind_obs", "wind_2min", "wind_10min", "wind_forecast",
                "humidity", "visibility", "visibility_min", "radar"
            }
            is_jiashan = "嘉善" in location or "JIASHAN" in location.upper()
            if layer in jiashan_pro_bases and is_jiashan:
                try:
                    await weather_service.get_pro_weather(location, [layer])
                except Exception:
                    pass

            layer_info = screen_layers.get(layer, {})
            layer_zh = layer_info.get("name", layer)
            result_content = {"status": "success", "message": f"{layer_zh}已在大屏展示，请查看。"}

            logger.info(f"[Tool Result] show_screen_layer -> Result: {json.dumps(result_content, ensure_ascii=False)}")
            if ctx.websocket: await ctx.websocket.send_json({
                "type": "debug_event",
                "step": "tool_result",
                "name": name,
                "result": result_content
            })

            return json.dumps(result_content, ensure_ascii=False)

        elif name == "query_emergency_knowledge":
            raw_location = args.get("location_name") or ctx.default_city
            location = address_corrector.correct(raw_location)
            if location != raw_location:
                logger.info(f"[Operation] 应急知识地址纠错: '{raw_location}' -> '{location}'")

            raw_category = args.get("category", "")
            category = address_corrector.correct_knowledge_category(raw_category).strip()
            if category != raw_category.strip():
                logger.info(f"[Operation] 应急类型纠错: '{raw_category}' -> '{category}'")

            query_keyword = args.get("query_keyword", "").strip()
            corrected_query_cat = address_corrector.correct_knowledge_category(query_keyword).strip()

            all_text_to_check = (category + " " + query_keyword + " " + corrected_query_cat).lower()
            matched_cat = None
            if "shelters" in all_text_to_check or "避难" in all_text_to_check or "避灾" in all_text_to_check or "场所" in all_text_to_check or "shelter" in all_text_to_check:
                matched_cat = "shelters"
            elif "rescue_team" in all_text_to_check or "队伍" in all_text_to_check or "救援" in all_text_to_check or "抢险" in all_text_to_check or "team" in all_text_to_check:
                matched_cat = "rescue_team"
            elif "supplies" in all_text_to_check or "物资" in all_text_to_check or "储备" in all_text_to_check or "装备" in all_text_to_check or "suppl" in all_text_to_check:
                matched_cat = "supplies"
            elif "risk_point" in all_text_to_check or "隐患" in all_text_to_check or "风险" in all_text_to_check or "地灾" in all_text_to_check or "hazard" in all_text_to_check or "risk" in all_text_to_check:
                matched_cat = "risk_point"

            if matched_cat:
                category = matched_cat
            elif category not in ["risk_point", "shelters", "rescue_team", "supplies"]:
                category = "shelters"

            if query_keyword:
                q_clean = query_keyword.strip()
                if q_clean in ["避难所", "避灾场所", "避难场所", "避灾点", "避难点", "避灾安置点", "收容所",
                               "救援队", "救援队伍", "抢险队", "抢险队伍", "突击队", "突击队伍",
                               "物资库", "储备库", "物资储备库", "物资储备", "应急物资",
                               "隐患点", "风险点", "地灾隐患点", "隐患", "风险", "灾害点"]:
                    query_keyword = ""
                elif q_clean.lower() in ["避难", "避灾", "场所", "收容", "shelter", "救援", "队伍", "抢险", "team", "物资", "储备", "装备", "supplies", "supply", "隐患", "风险", "地灾", "hazard", "risk"]:
                    query_keyword = ""

            real_lon, real_lat = None, None
            try:
                if amap_service:
                    real_lon, real_lat, area_name, pname, cityname, adname, poi_name = await amap_service.get_poi_coordinates(location)
                    if area_name and area_name != location:
                        location = area_name
            except Exception:
                pass

            ctrl_data = {
                "place": location,
                "lng": real_lon,
                "lat": real_lat,
                "elements": category,
                "query_keyword": query_keyword
            }
            await sse_hub.broadcast("control_command", ctrl_data)
            if ctx.websocket:
                await ctx.websocket.send_json({
                    "type": "debug_event",
                    "step": "control",
                    "content": f"推送大屏控制指令: 展示 {location} 的 {category} 应急物资/场所",
                    "arguments": ctrl_data
                })
            if real_lon and real_lat:
                await sse_hub.broadcast("query_info", {"lonLat": [real_lon, real_lat], "address": location})

            search_query = query_keyword if query_keyword else (location if location and location != "嘉善" else "")
            kb_data = knowledge_service.search_knowledge(category, search_query)

            tool_result_content = kb_data
            logger.info(f"[Tool Result] query_emergency_knowledge -> Result: {json.dumps(tool_result_content, ensure_ascii=False)}")
            if ctx.websocket: await ctx.websocket.send_json({
                "type": "debug_event",
                "step": "tool_result",
                "name": name,
                "result": tool_result_content
            })

            return json.dumps(tool_result_content, ensure_ascii=False)

        elif name == "zoom_map":
            action = args.get("action", "zoom_in")
            ctrl_data = {
                "action": action,
                "type": "map_zoom",
                "timestamp": time.time()
            }
            await sse_hub.broadcast("control_command", ctrl_data)
            if ctx.websocket:
                await ctx.websocket.send_json({
                    "type": "debug_event",
                    "step": "control",
                    "content": f"推送大屏控制指令: 地图{'放大' if action == 'zoom_in' else '缩小'}",
                    "arguments": ctrl_data
                })
            result_content = {"status": "success", "message": f"地图已成功{'放大' if action == 'zoom_in' else '缩小'}。"}
            
            logger.info(f"[Tool Result] zoom_map -> Result: {json.dumps(result_content, ensure_ascii=False)}")
            if ctx.websocket: await ctx.websocket.send_json({
                "type": "debug_event",
                "step": "tool_result",
                "name": name,
                "result": result_content
            })

            return json.dumps(result_content, ensure_ascii=False)

        elif name == "query_history_disasters":
            raw_location = args.get("location_name") or ctx.default_city
            location = address_corrector.correct(raw_location)
            if location != raw_location:
                logger.info(f"[Operation] 灾情查询地址纠错: '{raw_location}' -> '{location}'")

            ctrl_data = {
                "place": location,
                "type": "query_history_disasters"
            }
            await sse_hub.broadcast("control_command", ctrl_data)
            if ctx.websocket:
                await ctx.websocket.send_json({
                    "type": "debug_event",
                    "step": "control",
                    "content": f"推送大屏控制指令: 查询 {location} 历史灾情",
                    "arguments": ctrl_data
                })

            history_data = await weather_service.get_history_disasters(location)
            if ctx.websocket:
                ctx.expecting_weather_summary = True

            result_content = history_data
            logger.info(f"[Tool Result] query_history_disasters -> Result: {json.dumps(result_content, ensure_ascii=False)}")
            if ctx.websocket: await ctx.websocket.send_json({
                "type": "debug_event",
                "step": "tool_result",
                "name": name,
                "result": result_content
            })

            return json.dumps(result_content, ensure_ascii=False)

        elif name == "hangup":
            try:
                from visual_manager import visual_broadcast_manager
            except Exception:
                visual_broadcast_manager = None

            from utils import send_session_hangup
            await send_session_hangup(
                websocket=ctx.websocket,
                visual_broadcast_manager=visual_broadcast_manager,
                reason="模型触发 hangup 工具挂断会话"
            )
            ctx.session_active = False
                
            result_content = {"status": "success"}
            logger.info(f"[Tool Result] hangup -> Result: {json.dumps(result_content, ensure_ascii=False)}")
            if ctx.websocket: await ctx.websocket.send_json({
                "type": "debug_event",
                "step": "tool_result",
                "name": name,
                "result": result_content
            })

            return json.dumps(result_content, ensure_ascii=False)

        else:
            error_msg = f"Unknown tool name: {name}"
            logger.error(f"[Tool Call Error] {error_msg}")
            return json.dumps({"error": error_msg})
    except Exception as e:
        import traceback
        logger.error(f"[execute_tool Exception] {e}\n{traceback.format_exc()}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)
