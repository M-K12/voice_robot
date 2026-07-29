"""
SSE Hub — Server-Sent Events 事件广播中心

管理所有前端 SSE 客户端连接，提供统一的 broadcast() 方法
供后端各模块（KWS、Omni、Weather）推送事件到前端。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncIterator


class SSEHub:
    """
    Manages SSE client connections and broadcasts events to all connected frontends.

    Usage:
        hub = SSEHub()

        # In SSE endpoint:
        async def sse_stream():
            q = hub.connect()
            try:
                async for event in hub.stream(q):
                    yield event
            finally:
                hub.disconnect(q)

        # From anywhere in backend:
        await hub.broadcast("wake", {})
        await hub.broadcast("output_transcript", {"text": "你好", "response_id": "r1"})
    """

    def __init__(self):
        self._clients: set[asyncio.Queue] = set()

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def connect(self) -> asyncio.Queue:
        """
        Register a new SSE client. Returns an asyncio.Queue
        that will receive formatted SSE event strings.
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._clients.add(q)
        print(f"[SSEHub] Client connected. Total: {len(self._clients)}")
        return q

    def disconnect(self, q: asyncio.Queue) -> None:
        """Unregister an SSE client."""
        self._clients.discard(q)
        print(f"[SSEHub] Client disconnected. Total: {len(self._clients)}")

    async def broadcast(self, event_type: str, data: dict | str = "") -> None:
        """
        Send an event to ALL connected SSE clients.

        Args:
            event_type: SSE event name (e.g. "wake", "output_transcript")
            data: Event data, will be JSON-serialized if dict
        """
        if isinstance(data, dict):
            payload = json.dumps(data, ensure_ascii=False)
            payload_dict = data
        else:
            payload = data
            try:
                payload_dict = json.loads(data) if data else {}
            except Exception:
                payload_dict = {}

        # 旁路同步广播给大屏 WebSocket 客户端
        try:
            from backend.main import visual_broadcast_manager
            if event_type in ["control_command", "query_info"]:
                asyncio.create_task(visual_broadcast_manager.broadcast({
                    "type": event_type,
                    "data": payload_dict
                }))
        except Exception as e:
            print(f"[SSEHub] Broadcast to visual manager failed: {e}")

        # Format as SSE: event: <type>\ndata: <json>\n\n
        sse_message = f"event: {event_type}\ndata: {payload}\n\n"

        dead_clients = []
        for q in self._clients:
            try:
                q.put_nowait(sse_message)
            except asyncio.QueueFull:
                # Client is too slow, drop it
                dead_clients.append(q)
                print(f"[SSEHub] Dropping slow client (queue full)")

        for q in dead_clients:
            self._clients.discard(q)

    async def stream(self, q: asyncio.Queue) -> AsyncIterator[str]:
        """
        Async generator that yields SSE events for a specific client.
        Use this in the FastAPI SSE endpoint.
        """
        # Send initial connection confirmation
        yield f"event: connected\ndata: {{\"time\": {int(time.time())}}}\n\n"

        while True:
            try:
                # Wait for events with a timeout to send keepalive
                event = await asyncio.wait_for(q.get(), timeout=25.0)
                yield event
            except asyncio.TimeoutError:
                # Send SSE comment as keepalive to prevent proxy/browser timeout
                yield ": keepalive\n\n"
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[SSEHub] Stream error: {e}")
                break


# Global singleton instance
sse_hub = SSEHub()
