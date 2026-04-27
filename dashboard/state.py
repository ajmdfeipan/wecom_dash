"""
共享状态管理 — Bot 与 Web 服务器之间的桥梁
"""

import asyncio
import json
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Set


class BotState:
    """机器人运行时状态，供 Web 面板读取"""

    def __init__(self, max_messages: int = 200, max_heartbeat_log: int = 30):
        self.connected: bool = False
        self.authenticated: bool = False
        self.start_time: float = time.time()
        self.bot_id: str = ""

        # 消息日志
        self.messages: Deque[dict] = deque(maxlen=max_messages)

        # 心跳
        self.heartbeat_log: Deque[dict] = deque(maxlen=max_heartbeat_log)
        self.last_heartbeat_sent: float = 0
        self.last_heartbeat_ack: float = 0
        self.heartbeat_count: int = 0
        self.heartbeat_interval: int = 30000  # ms

        # SSE 客户端
        self.sse_queues: Set[asyncio.Queue] = set()

    def uptime(self) -> float:
        return time.time() - self.start_time

    def add_message(self, msg: dict):
        self.messages.append(msg)
        self._broadcast("message", msg)

    def add_reply(self, reply: dict):
        self.messages.append(reply)
        self._broadcast("reply", reply)

    def add_heartbeat(self, direction: str, detail: str = ""):
        entry = {
            "time": time.time(),
            "direction": direction,
            "detail": detail,
        }
        self.heartbeat_log.append(entry)
        if direction == "sent":
            self.last_heartbeat_sent = time.time()
            self.heartbeat_count += 1
        elif direction == "ack":
            self.last_heartbeat_ack = time.time()
        self._broadcast("heartbeat", entry)

    def update_status(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        self._broadcast("status", kwargs)

    def get_status(self) -> dict:
        return {
            "connected": self.connected,
            "authenticated": self.authenticated,
            "bot_id": self.bot_id,
            "uptime": round(self.uptime(), 1),
            "heartbeat_count": self.heartbeat_count,
            "last_heartbeat_sent": self.last_heartbeat_sent,
            "last_heartbeat_ack": self.last_heartbeat_ack,
            "heartbeat_interval": self.heartbeat_interval,
            "message_count": len(self.messages),
        }

    def get_messages(self) -> list:
        return list(self.messages)

    # SSE

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self.sse_queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        self.sse_queues.discard(q)

    def _broadcast(self, event_type: str, data: Any):
        payload = json.dumps({"type": event_type, "data": data}, ensure_ascii=False, default=str)
        dead = []
        for q in self.sse_queues:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self.sse_queues.discard(q)
