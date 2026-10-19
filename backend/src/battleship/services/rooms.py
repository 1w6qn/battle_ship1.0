"""Room / seating / reconnect use cases.

The socket layer only translates protocol frames; every rule about who may sit
where, what a seat key is, and how the 30-second disconnect grace behaves lives
here. Rooms are in-memory exactly like the legacy `RoomManager` (there is no room
table in the 21-table schema), so this service needs no unit of work. Anything
that later touches the database (match settlement, ticket #12) enters through
`repositories.UnitOfWork`, never raw SQL here.

Identity rules (frozen, see contracts.identity):

* custom / AI rooms: logged-in seat key = session user_id, guest key = socket sid;
* matchmaking rooms: seat key = the sid captured when the player joined the queue;
* the server always sends `player_id`; clients must never substitute their own
  `sio.sid` (it differs in matchmaking rooms and after reconnects).
"""

from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass
from typing import Any, Protocol

from ..contracts.identity import (
    IdentityClaim,
    SeatIdentity,
    ai_player_id,
    verify_identity,
)
from ..infra.logging import get_logger
from ..domain.room import (
    AI_DIFFICULTIES,
    LOBBY_ROOM_NAME_MAX_LEN,
    Player,
    Room,
    RoomState,
    build_room_sync,
    card_payload,
    new_room_id,
    opponent_of,
    rank_payload,
    room_kind,
    seat_label,
)
from .presence import PresenceService

logger = get_logger("rooms")

DISCONNECT_GRACE_SECONDS = 30
DISCONNECT_GRACE_INITIAL_DELAY_SECONDS = 0.2
ENDED_ROOM_RETENTION_SECONDS = 120
WAITING_ROOM_TTL_SECONDS = 3600


@dataclass(frozen=True)
class Connection:
    """The trusted facts of one live socket connection."""

    sid: str
    user_id: str | None = None
    username: str | None = None


class EventPublisher(Protocol):
    """The only outbound surface the service is allowed to use."""

    async def emit(
        self,
        event: str,
        data: dict[str, Any],
        *,
        to: str | None = None,
        room: str | None = None,
    ) -> None: ...

    async def enter_room(self, sid: str, room: str) -> None: ...

    async def leave_room(self, sid: str, room: str) -> None: ...


class NullPublisher:
    """Used by unit-style callers that only assert state, never wire frames."""

    async def emit(self, event: str, data: dict[str, Any], *,
                   to: str | None = None, room: str | None = None) -> None:
        return None

    async def enter_room(self, sid: str, room: str) -> None:
        return None

    async def leave_room(self, sid: str, room: str) -> None:
        return None


def _normalize_difficulty(value: Any) -> str:
    return value if value in AI_DIFFICULTIES else "normal"


class RoomService:
    """Owns rooms, seats, reconnect tokens and the disconnect grace window."""

    def __init__(
        self,
        *,
        grace_seconds: float = DISCONNECT_GRACE_SECONDS,
        grace_initial_delay_seconds: float = DISCONNECT_GRACE_INITIAL_DELAY_SECONDS,
        ended_room_retention_seconds: float = ENDED_ROOM_RETENTION_SECONDS,
        waiting_room_ttl_seconds: float = WAITING_ROOM_TTL_SECONDS,
        presence: PresenceService | None = None,
    ) -> None:
        self.rooms: dict[str, Room] = {}
        self.match_queue: list[dict[str, Any]] = []
        # One online table for the whole backend (CLAUDE #17). The room service
        # only writes the "seated in a room" flag and the name/uid of a seat;
        # the lobby and the friends service read the same instance.
        self.presence = presence or PresenceService()
        self.grace_seconds = grace_seconds
        self.grace_initial_delay_seconds = grace_initial_delay_seconds
        self.ended_room_retention_seconds = ended_room_retention_seconds
        self.waiting_room_ttl_seconds = waiting_room_ttl_seconds
        self._publisher: EventPublisher = NullPublisher()
        self._tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ wiring

    def bind(self, publisher: EventPublisher) -> None:
        self._publisher = publisher

    def _spawn(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)

        def _finished(done: asyncio.Task) -> None:
            self._tasks.discard(done)
            if done.cancelled():
                return
            error = done.exception()
            if error is not None:
                logger.error(
                    "room background task failed",
                    extra={"error_type": type(error).__name__},
                    exc_info=error,
                )

        task.add_done_callback(_finished)

    def get_room(self, room_id: str | None) -> Room | None:
        return self.rooms.get(room_id) if room_id else None

    def get_all_rooms(self) -> dict[str, Room]:
        return self.rooms

    # --------------------------------------------------------------- identity

    @staticmethod
    def _player_name(connection: Connection, data: dict[str, Any]) -> str:
        # Legacy: the logged-in account name wins; guests may send a display name.
        name = connection.username or data.get("player_name") or "匿名玩家"
        return str(name)

    @staticmethod
    def seat_identity(room: Room, player_id: str) -> SeatIdentity | None:
        player = room.players.get(player_id)
        if player is None:
            return None
        order = list(room.players)
        return SeatIdentity(
            room_id=room.id,
            room_kind=room_kind(room),
            player_id=player_id,
            user_id=player.user_id,
            socket_id=player.socket_id,
            seat=order.index(player_id) if player_id in order else None,
        )

    def identity_ok(self, room: Room | None, player_id: str | None,
                    connection: Connection | None) -> bool:
        """True only when the request really comes from that seat's owner.

        Mirrors `contracts.identity.verify_identity`: the claimed player_id must
        equal the seat key, the session user must own the seat, and the current
        socket must be the one registered on the seat. The last check is what
        stops replaying another player's action from a different connection.
        """

        if room is None or not player_id or connection is None:
            return False
        seat = self.seat_identity(room, str(player_id))
        if seat is None:
            return False
        decision = verify_identity(
            IdentityClaim(player_id=str(player_id)),
            seat,
            session_user_id=connection.user_id,
            current_socket_id=connection.sid,
        )
        return decision.ok

    # ------------------------------------------------------------- lifecycle

    async def handle_connect(self, connection: Connection) -> None:
        """Register the connection in the single online table (legacy connect)."""
        self.presence.add_connection(
            connection.sid, name=connection.username, user_id=connection.user_id
        )

    def _bind_presence_game(self, room: Room) -> None:
        """Mark every real account in the room as "in a game" (idempotent)."""
        for player in room.players.values():
            user_id = getattr(player, "user_id", None)
            if user_id:
                self.presence.set_in_game(user_id, True)

    def _release_presence_game(self, room: Room) -> None:
        """Clear the "in a game" flag for every real account in the room."""
        for player in room.players.values():
            user_id = getattr(player, "user_id", None)
            if user_id:
                self.presence.set_in_game(user_id, False)

    async def create_room(self, connection: Connection, data: dict[str, Any] | None) -> dict:
        data = data if isinstance(data, dict) else {}
        player_id = connection.user_id or connection.sid
        # One player may host at most one waiting room; otherwise every click
        # leaks another "same name" room into the lobby (legacy fix retained).
        self._recycle_host_waiting_rooms(player_id)

        room = Room(id=new_room_id())
        room.name = str(data.get("name") or "").strip()[:LOBBY_ROOM_NAME_MAX_LEN]
        room.public = bool(data.get("public", True))
        room.players[player_id] = Player(
            name=self._player_name(connection, data),
            user_id=player_id,
            socket_id=connection.sid,
        )
        self.rooms[room.id] = room
        await self._publisher.enter_room(connection.sid, room.id)
        self.presence.update_identity(
            connection.sid, name=room.players[player_id].name, user_id=connection.user_id
        )
        self._bind_presence_game(room)
        return {"status": "success", "room_id": room.id}

    async def create_ai_room(self, connection: Connection, data: dict[str, Any] | None) -> dict:
        data = data if isinstance(data, dict) else {}
        room = Room(id=new_room_id())
        room.is_ai_room = True
        room.ai_difficulty = _normalize_difficulty(data.get("difficulty") or "normal")
        room.ai_difficulty_by_player = {}
        room.ranked = False
        ai_id = ai_player_id(room.id)
        room.players[ai_id] = Player(
            name="AI",
            user_id=None,
            socket_id=ai_id,
            remaining_ships=0,
        )
        room.init_player_magic(ai_id)
        self.rooms[room.id] = room
        await self._publisher.enter_room(connection.sid, room.id)
        self._bind_presence_game(room)
        return {
            "status": "success",
            "room_id": room.id,
            "message": "人机对战房间创建成功",
        }

    def create_invite_room(self) -> str:
        """Empty custom room for friend invitations (friend invite HTTP route).

        The inviter and the invitee seat themselves through join_room, exactly
        like a room shared by id. No player is written here (the legacy
        create_custom_room_for_invite only allocated the room).
        """
        room = Room(id=new_room_id())
        room.public = True
        self.rooms[room.id] = room
        return room.id

    async def join_room(self, connection: Connection, data: dict[str, Any] | None) -> dict:
        data = data if isinstance(data, dict) else {}
        room_id = data.get("room_id")
        player_id = connection.user_id or connection.sid
        player_name = self._player_name(connection, data)

        room = self.get_room(room_id)
        if room is None:
            await self._publisher.emit("error", {"message": "房间不存在"}, to=connection.sid)
            return {"status": "error", "message": "房间不存在"}

        self._drop_my_other_waiting_rooms(player_id, room.id)

        seated = room.players.get(player_id)
        if seated is not None and room.state == RoomState.WAITING:
            # Same identity re-entering a waiting room (new tab / refresh):
            # reuse the seat and move its connection. Adding a second seat with
            # the same key would keep len(players) at 1 forever (legacy bug).
            seated.socket_id = connection.sid
            if player_name:
                seated.name = player_name
            await self._publisher.enter_room(connection.sid, room.id)
            self.presence.update_identity(
                connection.sid, name=seated.name, user_id=connection.user_id
            )
            self._bind_presence_game(room)
            return {
                "status": "success",
                "player_id": player_id,
                "seat": "reused",
                "player_seat": seat_label(room, player_id),
            }

        if len(room.players) >= 2:
            await self._publisher.emit("error", {"message": "房间已满"}, to=connection.sid)
            return {"status": "error", "message": "房间已满"}

        room.players[player_id] = Player(
            name=player_name,
            user_id=player_id,
            socket_id=connection.sid,
        )
        await self._publisher.enter_room(connection.sid, room.id)

        if len(room.players) == 2:
            # Skeleton: a full room enters placement. Placement legality / RPS /
            # attack rules belong to ticket #8.
            room.transition(RoomState.PLACING_SHIPS)
            for seat_id in room.players:
                room.init_player_magic(seat_id)
            for seat_id, seat in room.players.items():
                opponent_id = opponent_of(room, seat_id)
                opponent = room.players.get(opponent_id) if opponent_id else None
                if not seat.socket_id:
                    continue
                await self._publisher.emit(
                    "game_state",
                    {
                        "state": room.state.value,
                        "room_id": room.id,
                        **rank_payload(room),
                        "player_id": seat_id,
                        "player_seat": seat_label(room, seat_id),
                        "player_name": seat.name,
                        "opponent_name": opponent.name if opponent else None,
                    },
                    to=seat.socket_id,
                )

        self.presence.update_identity(
            connection.sid, name=player_name, user_id=connection.user_id
        )
        self._bind_presence_game(room)
        return {
            "status": "success",
            "player_id": player_id,
            "player_seat": seat_label(room, player_id),
        }

    async def close_room(self, connection: Connection,
                        data: dict[str, Any] | None = None) -> dict:
        """Let the host dissolve their own waiting room (the lobby escape hatch).

        Three checks, each of which is a hole if removed: the room still exists
        and is waiting (a started game must not be dissolved under the
        opponent), exactly one player is seated (nobody is waiting), and that
        player is the caller (same key rule as create_room).
        """
        data = data if isinstance(data, dict) else {}
        room_id = str(data.get("room_id") or "")
        player_id = connection.user_id or connection.sid
        room = self.get_room(room_id) if room_id else None
        if room is None:
            return {"status": "error", "message": "房间不存在"}
        if room.state != RoomState.WAITING:
            return {"status": "error", "message": "对局已开始，不能解散"}
        entries = list(room.players.items())
        if len(entries) != 1 or entries[0][0] != player_id:
            return {"status": "error", "message": "只能解散自己创建的房间"}
        # _drop_room releases the "in a game" flag: the player is still
        # connected, so without it the friend guard would block invites forever.
        self._drop_room(room_id)
        return {"status": "success", "room_id": room_id}

    # --------------------------------------------------------------- reconn.

    async def get_reconnect_token(self, connection: Connection,
                                  data: dict[str, Any] | None) -> dict:
        data = data if isinstance(data, dict) else {}
        room = self.get_room(data.get("room_id"))
        player_id = data.get("player_id")
        if room is None or not player_id or player_id not in room.players:
            return {"status": "error", "message": "无效的房间或玩家"}
        if not self.identity_ok(room, player_id, connection):
            return {"status": "error", "message": "无效的房间或玩家"}
        token = room.issue_reconnect_token(str(player_id))
        return {"status": "success", "token": token}

    async def rejoin_room(self, connection: Connection, data: dict[str, Any] | None) -> dict:
        data = data if isinstance(data, dict) else {}
        room = self.get_room(data.get("room_id"))
        player_id = data.get("player_id")
        token = data.get("token")
        if room is None or not player_id or player_id not in room.players:
            return {"status": "error", "message": "房间不存在"}

        stored_token = room.reconnect_tokens.get(player_id)
        ok = (
            bool(stored_token)
            and bool(token)
            and secrets.compare_digest(str(stored_token), str(token))
        )
        if not ok:
            # Legacy fallback: the signed session itself is proof for a logged-in
            # owner (guest keys are sids, which a session can never equal).
            ok = bool(connection.user_id) and str(connection.user_id) == str(player_id)
        if not ok:
            return {"status": "error", "message": "身份校验失败"}

        if room.state == RoomState.GAME_OVER:
            if room.game_over_reason == "opponent_disconnected" and room.winner != player_id:
                await self._publisher.emit(
                    "reconnect_warning",
                    {"message": "对局已因你掉线超时结束，请勿中途掉线"},
                    to=connection.sid,
                )
                self._spawn(self._cleanup_room_after(room.id, 3))
            else:
                await self._publisher.emit("error", {"message": "对局已结束"}, to=connection.sid)
            return {"status": "success"}

        seat = room.players[str(player_id)]
        seat.socket_id = connection.sid
        await self._publisher.enter_room(connection.sid, room.id)

        was_reconnect = str(player_id) in room.disconnected
        room.disconnected.pop(str(player_id), None)
        for other_id, other in room.players.items():
            if other_id != player_id and other.socket_id:
                await self._publisher.emit(
                    "opponent_reconnected", {"player_id": player_id}, to=other.socket_id
                )

        # Deliberate small deviation from the legacy "only when was_reconnect":
        # the grace entry is registered 0.2s after disconnect, so an instant
        # reconnect used to succeed without any snapshot (16-traps §6.3), leaving
        # the client on a stale/blank screen. The snapshot is idempotent, so it
        # is always sent on a successful rejoin.
        await self._publisher.emit(
            "room_sync", build_room_sync(room, str(player_id)), to=connection.sid
        )
        return {"status": "success", "reconnected": was_reconnect}

    async def request_hand_sync(self, connection: Connection,
                                data: dict[str, Any] | None) -> dict:
        data = data if isinstance(data, dict) else {}
        room = self.get_room(data.get("room_id"))
        player_id = data.get("player_id")
        if room is None or not player_id or player_id not in room.players:
            return {"status": "error", "message": "无效的房间或玩家"}
        if not self.identity_ok(room, player_id, connection):
            return {"status": "error", "message": "无效的房间或玩家"}
        player = room.players[str(player_id)]
        # Ticket #10 owns the real hand; this is the authoritative empty hand
        # (the event itself and its resync flag are frozen now so the client can
        # self-heal as soon as cards exist).
        await self._publisher.emit(
            "hand_updated",
            {"hand": [card_payload(card) for card in player.magic_hand], "resync": True},
            to=player.socket_id or connection.sid,
        )
        return {"status": "success", "count": len(player.magic_hand)}

    async def notify_resume(self, connection: Connection) -> None:
        """Server-pushed resume hint on a new connection (legacy connect handler)."""

        if not connection.user_id:
            return
        candidates: list[tuple[str, str]] = []
        for room_id, room in self.rooms.items():
            if room.state == RoomState.GAME_OVER:
                continue
            for player_id, player in room.players.items():
                if player.user_id and str(player.user_id) == str(connection.user_id):
                    if player.socket_id != connection.sid:
                        candidates.append((room_id, player_id))
        if len(candidates) != 1:
            return
        room_id, player_id = candidates[0]
        await self._publisher.emit(
            "resume_game",
            {
                "room_id": room_id,
                "player_id": player_id,
                "message": "检测到未结束的对局，正在恢复…",
            },
            to=connection.sid,
        )
        room = self.rooms.get(room_id)
        if room is not None:
            token = room.issue_reconnect_token(player_id)
            await self._publisher.emit("reconnect_token", {"token": token}, to=connection.sid)

    # -------------------------------------------------------------- disconnect

    async def handle_disconnect(self, sid: str) -> None:
        """Remove transport-only state, then start the grace window.

        No event is emitted synchronously here: the legacy hub deadlock is gone
        with asyncio, but the notification + timer still belong to a background
        task so a disconnect can never slow down another room's handler.
        """

        # Presence is the single online table: drop the connection first so a
        # lobby_state built by the disconnect broadcast no longer lists it.
        self.presence.remove_connection(sid)
        self._remove_from_match_queue(sid)
        for room_id, room in list(self.rooms.items()):
            for player_id, player in list(room.players.items()):
                if player.socket_id != sid:
                    continue
                self.presence.set_in_game(player.user_id, False)
                if room.state != RoomState.GAME_OVER:
                    self._spawn(self._start_disconnect_grace(room_id, player_id))
                return

    async def _start_disconnect_grace(self, room_id: str, player_id: str) -> None:
        await asyncio.sleep(self.grace_initial_delay_seconds)
        room = self.rooms.get(room_id)
        if room is None or room.state == RoomState.GAME_OVER:
            return
        if player_id in room.disconnected:
            return
        room.disconnect_seq += 1
        token = room.disconnect_seq
        deadline = time.time() + self.grace_seconds
        room.disconnected[player_id] = {"deadline": deadline, "token": token}
        for other_id, other in room.players.items():
            if other_id != player_id and other.socket_id:
                await self._publisher.emit(
                    "opponent_disconnected",
                    {
                        "player_id": player_id,
                        "seconds": self.grace_seconds,
                        "deadline": deadline,
                    },
                    to=other.socket_id,
                )
        await asyncio.sleep(self.grace_seconds)
        await self._disconnect_timeout(room_id, player_id, token)

    async def _disconnect_timeout(self, room_id: str, player_id: str, token: int) -> None:
        room = self.rooms.get(room_id)
        if room is None:
            return
        entry = room.disconnected.get(player_id)
        if not entry or entry.get("token") != token:
            return
        room.disconnected.pop(player_id, None)

        other_id = opponent_of(room, player_id)
        pre_battle = room.state in (RoomState.PLACING_SHIPS, RoomState.ROCK_PAPER_SCISSORS)
        if (
            room.is_ai_room
            or pre_battle
            or other_id is None
            or other_id in room.disconnected
            or room.state == RoomState.GAME_OVER
        ):
            await self._publisher.emit(
                "game_canceled",
                {
                    "reason": "opponent_disconnected",
                    "message": "对局已取消（对手掉线）",
                    "room_id": room_id,
                },
                room=room_id,
            )
            self._drop_room(room_id)
            return

        room.state = RoomState.GAME_OVER
        room.winner = other_id
        room.game_over_reason = "opponent_disconnected"
        # Match settlement / stats / replay persistence is ticket #12; this
        # ticket owns the room state and the player-visible game_over frame.
        await self._publisher.emit(
            "game_over",
            {"winner": other_id, "reason": "opponent_disconnected"},
            room=room_id,
        )
        self._spawn(self._cleanup_room_after(room_id, self.ended_room_retention_seconds))

    async def _cleanup_room_after(self, room_id: str, delay: float) -> None:
        await asyncio.sleep(delay)
        self._drop_room(room_id)

    # ------------------------------------------------------------------ rooms

    def _drop_room(self, room_id: str) -> bool:
        room = self.rooms.get(room_id)
        if room is not None:
            # Players may still be connected when the room disappears (host
            # dissolved / opponent dropped / TTL reaping). Release the flag or
            # the friend invite guard keeps saying "you are in a game".
            self._release_presence_game(room)
        return self.rooms.pop(room_id, None) is not None

    def _recycle_host_waiting_rooms(self, player_id: str) -> list[str]:
        reaped: list[str] = []
        for room_id, room in list(self.rooms.items()):
            if room.state != RoomState.WAITING:
                continue
            entries = list(room.players.items())
            if len(entries) != 1 or entries[0][0] != player_id:
                continue
            self._drop_room(room_id)
            reaped.append(room_id)
        return reaped

    def _drop_my_other_waiting_rooms(self, player_id: str, keep_room_id: str) -> list[str]:
        reaped: list[str] = []
        for room_id, room in list(self.rooms.items()):
            if room_id == keep_room_id or room.state != RoomState.WAITING:
                continue
            seats = list(room.players)
            if len(seats) == 1 and seats[0] == player_id:
                self._drop_room(room_id)
                reaped.append(room_id)
        return reaped

    def _remove_from_match_queue(self, sid: str) -> bool:
        for index, entry in enumerate(self.match_queue):
            if entry.get("sid") == sid:
                self.match_queue.pop(index)
                return True
        return False

    def findBySocket(self, sid: str) -> tuple[Room, str] | None:
        for room in self.rooms.values():
            for player_id, player in room.players.items():
                if player.socket_id == sid:
                    return room, player_id
        return None
