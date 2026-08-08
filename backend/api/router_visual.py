"""
Visual Screen Router — WebSocket 视觉大屏同步推送路由
"""

from __future__ import annotations

import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from visual_manager import visual_broadcast_manager

logger = logging.getLogger("xiaoan.api.visual")
router = APIRouter()


@router.websocket("/ws/visual")
async def ws_visual_endpoint(websocket: WebSocket):
    await websocket.accept()
    await visual_broadcast_manager.register(websocket)

    try:
        from utils import load_config
        from amap_service import amap_service
        config = load_config()
        ui_type = config.get("visual_terminal") or config.get("ui_type") or "demo_ui"
        await websocket.send_json({"type": "system_config", "config": {"visual_terminal": ui_type}})
        city = config.get("default_city", "")
        real_lon, real_lat = None, None
        if amap_service:
            real_lon, real_lat, area_name, _, _, _, _ = await amap_service.get_poi_coordinates(city)
            if area_name:
                city = area_name
        ctrl_data = {
            "place": city,
            "lng": real_lon,
            "lat": real_lat,
            "elements": "",
            "elements_colloquial": ""
        }
        await websocket.send_json({"type": "control_command", "data": ctrl_data, "visual_terminal": ui_type})
        if real_lon and real_lat:
            await websocket.send_json({"type": "query_info", "data": {"lonLat": [real_lon, real_lat], "address": city}, "visual_terminal": ui_type})
        logger.info(f"[WS-Visual] {ui_type}大屏连接成功，推送坐标: [{city}] ({real_lon}, {real_lat})")
    except Exception as e:
        logger.warning(f"[WS-Visual] 大屏初次连接主动下发地理坐标失败: {e}")

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"[WS-Visual] 连接异常: {e}")
    finally:
        visual_broadcast_manager.unregister(websocket)
