"""In-game quick chat (ticket #14).

Port of the legacy quick_chat handler: room lookup, seat identity, whitelist,
per-room rate rule, one broadcast and one game_log line. Sending a phrase is a
conversation action, so it never touches state / phase / attacks / chain.

The replay recorder hook from the legacy add_game_log is NOT ported here: replay
is a separate ticket. The log entry itself is the legacy shape because the
client renders it today.
"""

from __future__ import annotations

import time
from typing import Any

from ..domain.social import quick_chat
from ..infra.logging import get_logger
from .rooms import Connection, EventPublisher, NullPublisher, RoomService

logger = get_logger("chat")


class ChatService:
    def __init__(self, rooms: RoomService, publisher: EventPublisher | None = None) -> None:
        self._rooms = rooms
        self._publisher: EventPublisher = publisher or NullPublisher()

    def bind(self, publisher: EventPublisher) -> None:
        self._publisher = publisher

    async def _fail(self, connection: Connection, message: str) -> dict[str, Any]:
        """Explain the refusal to the sender only, then return the error ack."""
        try:
            await self._publisher.emit("error", {"message": message}, to=connection.sid)
        except Exception:  # noqa: BLE001 - the ack is the authoritative result
            logger.exception("quick_chat error frame failed")
        return {"status": "error", "message": message}

    async def quick_chat(self, connection: Connection,
                         data: dict[str, Any] | None = None) -> dict[str, Any]:
        data = data if isinstance(data, dict) else {}
        room_id = data.get("room_id")
        player_id = data.get("player_id")
        msg_id = data.get("msg_id")

        room = self._rooms.get_room(room_id)
        if room is None:
            return await self._fail(connection, "房间不存在")
        if player_id not in room.players or not self._rooms.identity_ok(
            room, player_id, connection
        ):
            return await self._fail(connection, "无效的房间或玩家")

        item = quick_chat.by_id(msg_id)
        if item is None:
            return await self._fail(connection, "无效的快捷语")

        now = time.time()
        recent = [t for t in (room.quick_chat_recent.get(player_id) or [])
                  if now - t < quick_chat.WINDOW_SECONDS]
        allowed, reason = quick_chat.check_rate(
            recent, now, room.quick_chat_last.get(player_id), msg_id
        )
        # Drop expired timestamps even on a refusal (the room list must not grow
        # forever), but a refused phrase is never recorded.
        room.quick_chat_recent[player_id] = recent
        if not allowed:
            return await self._fail(connection, reason)

        recent.append(now)
        room.quick_chat_recent[player_id] = recent
        room.quick_chat_last[player_id] = {"id": msg_id, "ts": now}

        player = room.players[player_id]
        name = str(getattr(player, "name", "") or player_id)
        await self._publisher.emit(
            "quick_chat",
            {
                "player_id": player_id,
                "name": name,
                "msg_id": msg_id,
                "text": item["text"],
                "ts": int(now),
            },
            room=room.id,
        )
        entry = {
            "ts": int(now),
            "type": "quick_chat",
            "text": f"{name}：{item['text']}",
            "detail": {"player_id": player_id, "msg_id": msg_id},
        }
        room.game_logs.append(entry)
        await self._publisher.emit("game_log", entry, room=room.id)
        return {"status": "success", "msg_id": msg_id, "text": item["text"]}
