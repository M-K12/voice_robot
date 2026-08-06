import logging
from fastapi import WebSocket

class VisualBroadcastManager:
    def __init__(self):
        self.clients: set[WebSocket] = set()

    async def register(self, websocket: WebSocket):
        self.clients.add(websocket)
        logging.info(f"[VisualBroadcastManager] 大屏视觉端连接成功. 当前连接数: {len(self.clients)}")

    def unregister(self, websocket: WebSocket):
        self.clients.discard(websocket)
        logging.info(f"[VisualBroadcastManager] 大屏视觉端断开连接. 当前连接数: {len(self.clients)}")

    async def broadcast(self, payload: dict):
        from utils import load_config
        config = load_config()
        if not config.get("enable_visual_broadcast"):
            return
        if not self.clients:
            logging.warning(f"[VisualBroadcastManager] ⚠️ 大屏未连接(连接数:0)，无法推送事件 [{payload.get('type')}]。请检查大屏网页是否已连接 ws://127.0.0.1:10850/ws/visual")
            return

        ui_type = config.get("visual_terminal") or config.get("ui_type") or "demo_ui"
        
        # 构建适合推送的消息体
        send_payload = dict(payload)
        send_payload["visual_terminal"] = ui_type

        # app_ui 模式标准接口转换兼容
        if ui_type == "app_ui":
            evt_type = send_payload.get("type")
            if evt_type == "weather_data" and "data" not in send_payload:
                send_payload["type"] = "weather_update"
                send_payload["data"] = payload.get("weather") or payload.get("result") or payload
            elif evt_type in ("show_screen_layer", "fly_to"):
                send_payload["type"] = "control_command"
                send_payload["data"] = payload.get("data") or {
                    "place": payload.get("place", ""),
                    "lng": payload.get("lng"),
                    "lat": payload.get("lat"),
                    "elements": payload.get("elements", "temp")
                }

        logging.info(f"[VisualBroadcastManager] 📡 向大屏({len(self.clients)}个连接, 模式:{ui_type})推送事件 [{send_payload.get('type')}]")
        dead = set()
        for ws in self.clients:
            try:
                await ws.send_json(send_payload)
            except Exception as e:
                logging.error(f"[VisualBroadcastManager] 推送大屏消息失败: {e}")
                dead.add(ws)
        self.clients -= dead

visual_broadcast_manager = VisualBroadcastManager()
