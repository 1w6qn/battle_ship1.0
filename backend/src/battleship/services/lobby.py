"""Lobby use cases: subscription, public chat, create/close room, state fan-out.

The socket handlers are pure protocol translation; every rule lives here. The
state is assembled fresh on every broadcast (rooms/queue/presence are in memory;
only the avatar projection touches the database, and it is cached per account).

lobby_state is a BROADCAST to the lobby room. It cannot carry a per-recipient
"is_me" flag, so the client compares its own connection key against
lobby_hello.key. That is the frozen legacy contract.

Known projection gap (owned by later tickets, do not re-implement the curves
here): level/rank/title/name_style come from the progression/profile modules
which are still placeholders, so this service projects the legacy defaults
(level 1, rank None, empty title/name_style). Avatars are real.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from ..domain.lobby.rules import (
    LOBBY_CHAT_BACKLOG,
    LOBBY_CHAT_MIN_INTERVAL,
    LOBBY_MAX_PLAYERS,
    LOBBY_ROOM,
    LOBBY_STATE_TICK_SECONDS,
    chat_text,
    clean_name,
    player_status,
    rooms_by_socket,
    visible_rooms,
)
from ..infra.logging import get_logger
from .presence import PresenceService
from .rooms import Connection, EventPublisher, NullPublisher, RoomService

logger = get_logger("lobby")

#: Avatar / title cache lifetime (the legacy stack used 60s to avoid a query per
#: broadcast; the lobby ticker re-broadcasts every 4 seconds).
PROFILE_CACHE_TTL_SECONDS = 60.0

MATCH_MODE_RANKED = "ranked"


@dataclass
class _Member:
    name: str
    joined_at: float = field(default_factory=time.time)


class LobbyService:
    """Online presence is owned by PresenceService; this service owns members/chat."""

    def __init__(
        self,
        rooms: RoomService,
        presence: PresenceService,
        database: Any | None = None,
        *,
        tick_seconds: float | None = LOBBY_STATE_TICK_SECONDS,
    ) -> None:
        self._rooms = rooms
        self._presence = presence
        self._database = database
        self.tick_seconds = tick_seconds
        self._members: dict[str, _Member] = {}
        self._chat: list[dict[str, Any]] = []
        self._chat_seq = 0
        self._last_chat_at: dict[str, float] = {}
        self._profile_cache: dict[str, tuple[float, dict[str, str]]] = {}
        self._publisher: EventPublisher = NullPublisher()
        self._ticker_task: asyncio.Task | None = None

    # ------------------------------------------------------------------ wiring

    def bind(self, publisher: EventPublisher) -> None:
        self._publisher = publisher

    def ensure_ticker(self) -> None:
        """Start the legacy 4s fallback broadcast (idempotent)."""
        if not self.tick_seconds or self._ticker_task is not None:
            return
        try:
            self._ticker_task = asyncio.create_task(self._ticker_loop())
        except RuntimeError:
            self._ticker_task = None

    async def _ticker_loop(self) -> None:
        while True:
            await asyncio.sleep(float(self.tick_seconds or LOBBY_STATE_TICK_SECONDS))
            try:
                await self.broadcast()
            except Exception:  # noqa: BLE001 - the fallback must never die
                logger.exception("lobby ticker broadcast failed")

    # --------------------------------------------------------------- membership

    def is_member(self, sid: str) -> bool:
        return sid in self._members

    def member_count(self) -> int:
        return len(self._members)

    def members(self) -> list[str]:
        return list(self._members)

    def recent_chat(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._chat]

    def subscriber_name(self, connection: Connection, data: dict[str, Any] | None = None) -> str:
        """Show name: session first, then the payload, then the presence record."""
        if connection.username:
            return clean_name(connection.username)
        if isinstance(data, dict) and str(data.get("player_name") or "").strip():
            return clean_name(data.get("player_name"))
        record = self._presence.get(connection.sid)
        return clean_name(record.name if record else "")

    # ------------------------------------------------------------ socket events

    async def subscribe(self, connection: Connection,
                        data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        name = self.subscriber_name(connection, data)
        # The name/user id are facts of this connection; store them once.
        self._presence.update_identity(connection.sid, name=name, user_id=connection.user_id)
        member = self._members.get(connection.sid)
        if member is None:
            self._members[connection.sid] = _Member(name=name)
        else:
            member.name = name

        await self._publisher.enter_room(connection.sid, LOBBY_ROOM)
        await self._publisher.emit(
            "lobby_hello",
            {"key": connection.sid, "name": name, "guest": not bool(connection.user_id)},
            to=connection.sid,
        )
        await self._publisher.emit(
            "lobby_chat_history",
            {"messages": self.recent_chat()},
            to=connection.sid,
        )
        await self._publisher.emit("lobby_state", self.build_state(), to=connection.sid)
        # Tell the other members that the player list / lobby count changed.
        await self.broadcast()
        return {"status": "success", "key": connection.sid}

    async def unsubscribe(self, connection: Connection,
                          data: dict[str, Any] | None = None) -> dict:
        self._members.pop(connection.sid, None)
        await self._publisher.leave_room(connection.sid, LOBBY_ROOM)
        await self.broadcast()
        return {"status": "success"}

    async def refresh(self, connection: Connection,
                      data: dict[str, Any] | None = None) -> dict:
        if not self.is_member(connection.sid):
            # The refresh button must not kick the player out of the lobby.
            return await self.subscribe(connection, data)
        await self._publisher.emit("lobby_state", self.build_state(), to=connection.sid)
        return {"status": "success"}

    async def create_room(self, connection: Connection,
                          data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        payload = {
            "player_name": self.subscriber_name(connection, data),
            "name": data.get("name"),
            "public": data.get("public", True),
        }
        result = await self._rooms.create_room(connection, payload)
        if not isinstance(result, dict) or result.get("status") != "success":
            return result if isinstance(result, dict) else {
                "status": "error", "message": "建房失败"
            }
        await self.broadcast()
        room = self._rooms.get_room(result.get("room_id"))
        return {
            "status": "success",
            "room_id": result.get("room_id"),
            "name": str(getattr(room, "name", "") or ""),
            "public": bool(getattr(room, "public", True)),
        }

    async def chat_send(self, connection: Connection,
                        data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        sid = connection.sid
        if not self.is_member(sid):
            return {"status": "error", "message": "请先进入大厅"}
        if not self._chat_allowed(sid):
            await self._publisher.emit(
                "error",
                {"message": f"发言太快了，请等 {LOBBY_CHAT_MIN_INTERVAL:.0f} 秒"},
                to=sid,
            )
            return {"status": "error", "message": "发言太快了"}
        record = self._presence.get(sid)
        name = clean_name(
            connection.username or (record.name if record else "") or "游客"
        )
        item = self._add_chat(sid, name, data.get("message"))
        if item is None:
            return {"status": "error", "message": "消息不能为空"}
        await self._publisher.emit("lobby_chat", item, room=LOBBY_ROOM)
        return {"status": "success", "ts": item["ts"]}

    async def close_room(self, connection: Connection,
                         data: dict[str, Any] | None = None) -> dict:
        result = await self._rooms.close_room(connection, data)
        if result.get("status") == "success":
            await self.broadcast()
        return result

    async def handle_disconnect(self, sid: str) -> None:
        """Drop lobby membership for a closed connection (presence follows)."""
        self._members.pop(sid, None)
        self._last_chat_at.pop(sid, None)

    # ------------------------------------------------------------------- state

    async def broadcast(self) -> int:
        if not self._members:
            return 0
        await self._publisher.emit("lobby_state", self.build_state(), room=LOBBY_ROOM)
        return len(self._members)

    def build_state(self) -> dict[str, Any]:
        now = time.time()
        presence = self._presence.snapshot()
        members = set(self._members)
        in_game, in_room = rooms_by_socket(self._rooms.get_all_rooms().values())
        queued = {
            str(entry.get("sid"))
            for entry in self._rooms.match_queue
            if entry.get("sid")
        }
        ordered = sorted(
            presence.items(), key=lambda item: item[1].get("connected_at") or 0
        )[:LOBBY_MAX_PLAYERS]
        profiles = self._profiles_for([
            str(row.get("user_id")) for _sid, row in ordered if row.get("user_id")
        ])

        players: list[dict[str, Any]] = []
        for sid, row in ordered:
            uid = str(row.get("user_id") or "")
            profile = profiles.get(uid, {}) if uid else {}
            players.append(
                {
                    "key": sid,
                    "name": row.get("name") or "游客",
                    "guest": not bool(uid),
                    "in_lobby": sid in members,
                    "status": player_status(
                        sid, in_game=in_game, in_room=in_room, queued=queued
                    ),
                    "avatar": profile.get("avatar", ""),
                    "level": 1,
                    "name_style": profile.get("name_style", ""),
                    "title": profile.get("title", ""),
                    "rank": None,
                }
            )

        queue = list(self._rooms.match_queue)
        ranked_n = sum(1 for entry in queue if entry.get("mode") == MATCH_MODE_RANKED)
        return {
            "ts": int(now),
            "online_count": len(presence),
            "lobby_count": len(members),
            "queue": {"casual": len(queue) - ranked_n, "ranked": ranked_n},
            "players": players,
            "rooms": visible_rooms(self._rooms.get_all_rooms().values(), set(presence)),
            # Live matches are the spectate entry; spectating is a later ticket,
            # and listing a match that cannot be entered is worse than listing
            # none. The key stays because the client renders it unconditionally.
            "matches": [],
        }

    # ------------------------------------------------------------------- chat

    def _chat_allowed(self, sid: str, now: float | None = None) -> bool:
        current = time.time() if now is None else now
        last = self._last_chat_at.get(sid)
        if last is not None and current - last < LOBBY_CHAT_MIN_INTERVAL:
            return False
        self._last_chat_at[sid] = current
        return True

    def _add_chat(self, sid: str, name: str, message: Any) -> dict[str, Any] | None:
        text = chat_text(message)
        if text is None:
            return None
        self._chat_seq += 1
        item = {
            "key": sid,
            "name": clean_name(name),
            "message": text,
            "ts": time.time(),
            "seq": self._chat_seq,
        }
        self._chat.append(item)
        if len(self._chat) > LOBBY_CHAT_BACKLOG:
            del self._chat[: len(self._chat) - LOBBY_CHAT_BACKLOG]
        return item

    # ---------------------------------------------------------------- profiles

    def _profiles_for(self, user_ids: list[str]) -> dict[str, dict[str, str]]:
        """Cached avatar projection, one batched query per broadcast."""
        if not user_ids or self._database is None:
            return {}
        now = time.time()
        result: dict[str, dict[str, str]] = {}
        missing: list[str] = []
        for uid in {uid for uid in user_ids if uid}:
            cached = self._profile_cache.get(uid)
            if cached is not None and now - cached[0] < PROFILE_CACHE_TTL_SECONDS:
                result[uid] = dict(cached[1])
            else:
                missing.append(uid)
        if missing:
            try:
                with self._database.unit_of_work() as uow:
                    users = uow.users.list_by_ids(missing)
            except Exception:  # noqa: BLE001 - a lobby frame must not 500
                logger.exception("lobby profile projection failed")
                users = {}
            for uid in missing:
                user = users.get(uid)
                projection = {
                    "avatar": str(getattr(user, "avatar", "") or "") if user else "",
                    "title": "",
                    "name_style": "",
                }
                self._profile_cache[uid] = (now, projection)
                result[uid] = dict(projection)
        return result
