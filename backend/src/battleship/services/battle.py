"""Attack / surrender / match-ending use cases (ticket #9).

The socket layer only translates frames; every rule lives in
battleship.domain.battle and persistence in SettlementService. This module owns
the wire frames that the legacy handler emitted, in the same order:

shield_absorbed -> player_ships_updated -> ships_updated -> game_log ->
attack_result -> game_over / attacks_updated

Magic-card effects (subsidy, trap, demon contract, vampire, battle spirit,
wuxian) are injected hooks so ticket #10 can extend the same sink path instead
of forking it.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any, Awaitable, Callable

from ..domain import battle as battle_rules
from ..domain import replay as replay_rules
from ..domain.battle import AttackOutcome
from ..domain.room import Player, PlayerShip, Room, RoomState
from ..infra.logging import get_logger
from .rooms import Connection, EventPublisher, NullPublisher, RoomService
from .settlement import SettlementResult, SettlementService

logger = get_logger("battle")

INVALID_SEAT = {"status": "error", "message": "无效的房间或玩家"}
FINISHED_GAME = {"status": "error", "message": "对局已结束"}

SinkHook = Callable[[Room, str, PlayerShip], Any]
DamageHook = Callable[[Room, str, AttackOutcome], Any]
ExhaustedHook = Callable[[Room, str], Any]


class BattleService:
    def __init__(
        self,
        rooms: RoomService,
        settlement: SettlementService | None = None,
        *,
        clock: Callable[[], float] | None = None,
        touch_turn: Callable[[Room, str], None] | None = None,
    ) -> None:
        self.rooms = rooms
        self.settlement = settlement or SettlementService(None)
        self.clock = clock or time.time
        self.touch_turn = touch_turn
        self._publisher: EventPublisher = NullPublisher()
        self.sink_hooks: list[SinkHook] = []
        self.damage_hooks: list[DamageHook] = []
        self.attacks_exhausted_hooks: list[ExhaustedHook] = []

    def bind(self, publisher: EventPublisher) -> None:
        self._publisher = publisher

    # ----------------------------------------------------------------- helpers

    def _seat(self, connection: Connection, data: dict[str, Any]):
        room = self.rooms.get_room(data.get("room_id"))
        player_id = data.get("player_id")
        if (
            room is None
            or not player_id
            or player_id not in room.players
            or not self.rooms.identity_ok(room, str(player_id), connection)
        ):
            return None, None
        return room, str(player_id)

    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value

    @staticmethod
    def _name(room: Room, player_id: str) -> str:
        player = room.players.get(player_id)
        return (player.name or player_id) if player else player_id

    async def _add_log(self, room: Room, text: str, event_type: str = "info",
                       detail: dict | None = None) -> dict:
        entry = {
            "ts": int(self.clock()),
            "type": event_type,
            "text": text,
            "detail": detail,
        }
        room.game_logs.append(entry)
        # The recorder's single 38-point feed: every game log is also a replay
        # step (it never writes back to game_logs and never emits).
        replay_rules.note(room, entry)
        await self._publisher.emit("game_log", entry, room=room.id)
        return entry

    async def _emit_ships_updated(self, room: Room) -> None:
        for pid, player in room.players.items():
            opponent_id = room.opponent_of(pid)
            opponent = room.players.get(opponent_id) if opponent_id else None
            if not player.socket_id:
                continue
            await self._publisher.emit(
                "ships_updated",
                {
                    "player_remaining_ships": player.remaining_ships,
                    "opponent_remaining_ships": opponent.remaining_ships
                    if opponent
                    else 0,
                },
                to=player.socket_id,
            )

    async def _emit_player_ships(self, room: Room, player_id: str) -> None:
        player = room.players.get(player_id)
        if player is None or not player.socket_id:
            return
        await self._publisher.emit(
            "player_ships_updated",
            {"ships": battle_rules.player_ships_payload(player)},
            to=player.socket_id,
        )

    # ---------------------------------------------------------------- attacks

    async def attack(self, connection: Connection,
                     data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        # Legacy _require_live_room runs before the handler identity check: an
        # already-finished room always answers "对局已结束".
        existing = self.rooms.get_room(data.get("room_id"))
        if existing is not None and existing.state == RoomState.GAME_OVER:
            return dict(FINISHED_GAME)
        room, player_id = self._seat(connection, data)
        if room is None:
            return dict(INVALID_SEAT)
        if room.state == RoomState.GAME_OVER:
            return dict(FINISHED_GAME)
        frozen = self._frozen_reason(room, player_id)
        if frozen:
            return {"status": "error", "message": frozen}
        return await self._perform_attack(room, player_id, data.get("x"), data.get("y"))

    async def fire(self, room: Room, player_id: str, x: int, y: int) -> dict:
        """Turn-watchdog seam: same rules, no socket identity check."""

        if room.state == RoomState.GAME_OVER or player_id not in room.players:
            return dict(FINISHED_GAME)
        return await self._perform_attack(room, player_id, x, y)

    @staticmethod
    def _frozen_reason(room: Room, player_id: str) -> str | None:
        for pid in room.disconnected:
            if pid != player_id:
                return "对手已掉线，等待重连中"
        return None

    async def _perform_attack(self, room: Room, player_id: str,
                              raw_x: Any, raw_y: Any) -> dict:
        error = battle_rules.attack_error(room, player_id, raw_x, raw_y)
        if error:
            return {"status": "error", "message": error}
        # Ticket #8's _require_live_room reset the 90s clock on every effective
        # action by the current attacker; the battle handler bypasses that
        # decorator, so it must call the same seam explicitly.
        if self.touch_turn is not None:
            self.touch_turn(room, player_id)
        coords = battle_rules.normalize_attack_coords(raw_x, raw_y)
        assert not isinstance(coords, str)
        x, y = coords

        outcome = battle_rules.resolve_attack(room, player_id, x, y)
        defender_id = outcome.defender

        if outcome.last_chance:
            await self._finish_game(
                room,
                player_id,
                defender_id,
                log_text=(
                    f"第{room.round}回合 · {self._name(room, defender_id)} "
                    f"触发回光返照失败并判负"
                ),
                log_detail={"winner": player_id, "loser": defender_id},
            )
            return {"status": "success", "game_over": True}

        if outcome.shield_blocked:
            ship = outcome.sunk_ship
            # The hit ship is not part of the outcome when a shield absorbs it;
            # rebuild its positions for the frozen shield_absorbed payload.
            position_payload = []
            for candidate in room.players[defender_id].ships:
                if any(pos.x == x and pos.y == y for pos in candidate.positions):
                    position_payload = [
                        {"x": pos.x, "y": pos.y} for pos in candidate.positions
                    ]
                    break
            await self._publisher.emit(
                "shield_absorbed",
                {"player": defender_id, "positions": position_payload},
                room=room.id,
            )
            await self._emit_player_ships(room, defender_id)

        if outcome.sunk_ship is not None:
            await self._emit_player_ships(room, defender_id)
            for hook in self.sink_hooks:
                await self._maybe_await(hook(room, defender_id, outcome.sunk_ship))

        if outcome.damage_dealt:
            await self._emit_ships_updated(room)
            for hook in self.damage_hooks:
                await self._maybe_await(hook(room, player_id, outcome))
            if outcome.last_stand_win:
                await self._finish_game(
                    room,
                    player_id,
                    defender_id,
                    log_text=(
                        f"第{room.round}回合 · {self._name(room, player_id)} "
                        f"绝处逢生击杀敌舰获胜"
                    ),
                    log_detail={"winner": player_id, "loser": defender_id},
                )
                return {"status": "success", "game_over": True}

        note = ""
        if outcome.shield_blocked:
            note = "，被护盾挡下"
        elif outcome.ship_sunk:
            note = "，击沉战舰"
        await self._add_log(
            room,
            f"第{room.round}回合 · {self._name(room, player_id)} 攻击 ({x},{y}) — "
            f"{'命中' if outcome.hit else '未命中'}{note}",
            "attack",
            {
                "attacker": player_id,
                "target": {"x": x, "y": y},
                "hit": outcome.hit,
                "ship_sunk": outcome.ship_sunk,
                "shield_blocked": outcome.shield_blocked,
            },
        )
        await self._publisher.emit("attack_result", outcome.to_payload(), room=room.id)

        if outcome.defender_wiped_out:
            await self._finish_game(
                room,
                player_id,
                defender_id,
                log_text=(
                    f"第{room.round}回合 · {self._name(room, player_id)} 获胜，游戏结束"
                ),
            )
            return {"status": "success", "game_over": True}

        if room.attacks_remaining == 0:
            for hook in self.attacks_exhausted_hooks:
                await self._maybe_await(hook(room, player_id))
            if room.attacks_remaining == 0:
                await self._publisher.emit(
                    "attacks_updated",
                    {
                        "current_attacker": room.current_attacker,
                        "attacks_remaining": room.attacks_remaining,
                    },
                    room=room.id,
                )
        return {"status": "success"}

    # --------------------------------------------------------------- ending

    async def finish_game(self, room: Room, winner_id: str, loser_id: str,
                          *, reason: str | None = None,
                          log_text: str | None = None,
                          log_detail: dict | None = None) -> SettlementResult:
        """Public ending seam for magic cards (ticket #10).

        Magic wipes must enter the same idempotent funnel as attacks and
        surrender; otherwise a card that sinks the last ship would flip the
        room state without writing a match row.
        """

        if log_text is None:
            log_text = (
                f"第{room.round}回合 · {self._name(room, winner_id)} 获胜，游戏结束"
            )
        return await self._finish_game(
            room, winner_id, loser_id, log_text=log_text,
            log_detail=log_detail, reason=reason,
        )

    # --------------------------------------------------------------- ending

    async def _finish_game(
        self,
        room: Room,
        winner_id: str,
        loser_id: str,
        *,
        log_text: str | None = None,
        log_detail: dict | None = None,
        reason: str | None = None,
    ) -> SettlementResult:
        # Idempotent like legacy _finish_game_win: an already-ended room never
        # records a second match. (The disconnect path sets game_over_reason
        # itself in RoomService and uses settle_forfeit.)
        if room.state == RoomState.GAME_OVER:
            return room.settlement_result or SettlementResult(ok=True, skipped=True)

        room.state = RoomState.GAME_OVER
        room.winner = winner_id
        if log_text:
            await self._add_log(
                room,
                log_text,
                "result",
                log_detail or {"winner": winner_id, "loser": loser_id},
            )
        result = await asyncio.to_thread(
            self.settlement.settle, room, winner_id, loser_id
        )
        # Legacy _finalize_match always released the presence "in a game" flag,
        # even when persistence failed, so friends can invite again immediately.
        self.rooms.release_presence(room)
        await self._emit_game_over(room, winner_id, reason, result)
        return result

    async def _emit_game_over(self, room: Room, winner_id: str,
                              reason: str | None,
                              result: SettlementResult) -> None:
        payload: dict[str, Any] = {"winner": winner_id}
        if reason:
            payload["reason"] = reason
        # match_id is only present when it really was persisted; the client uses
        # its absence to hide the replay entry (legacy _game_over_payload).
        if result.match_id:
            payload["match_id"] = result.match_id
        await self._publisher.emit("game_over", payload, room=room.id)

    async def settle_forfeit(self, room: Room, winner_id: str, loser_id: str,
                             reason: str) -> SettlementResult:
        """Disconnect-timeout hook: room state is already set by RoomService."""

        result = await asyncio.to_thread(
            self.settlement.settle, room, winner_id, loser_id
        )
        self.rooms.release_presence(room)
        await self._emit_game_over(room, winner_id, reason, result)
        return result

    async def surrender(self, connection: Connection,
                        data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        # Legacy surrender falls back to the session identity when player_id is
        # omitted (unlike attack, which always requires the explicit seat id).
        if not data.get("player_id"):
            data = dict(data)
            data["player_id"] = connection.user_id or connection.sid
        existing = self.rooms.get_room(data.get("room_id"))
        if existing is not None and existing.state == RoomState.GAME_OVER:
            return dict(FINISHED_GAME)
        room, player_id = self._seat(connection, data)
        if room is None:
            return {"status": "error", "message": "你不在这个房间"}
        if room.state == RoomState.GAME_OVER:
            return dict(FINISHED_GAME)
        opponent_id = room.opponent_of(player_id)
        if not opponent_id:
            return {"status": "error", "message": "你不在这个房间"}
        # Record the surrender step before settlement finalizes/resets the
        # recorder (legacy did exactly this, and the order is load-bearing).
        actor = self._name(room, player_id)
        replay_rules.note_action(
            room,
            "surrender",
            f"{actor} 投降了",
            {"player": player_id, "winner": opponent_id},
            actor,
        )
        await self._finish_game(
            room, opponent_id, player_id, reason="surrender"
        )
        return {"status": "success"}

    # --------------------------------------------------------------- debug

    async def debug_win(self, room_id: str | None, player_id: str | None) -> dict:
        """test_win_game parity: state/winner + emit only, never settlement."""

        room = self.rooms.get_room(room_id)
        if room is None or not player_id or player_id not in room.players:
            return {"status": "error", "message": "无效的房间或玩家"}
        room.state = RoomState.GAME_OVER
        room.winner = str(player_id)
        await self._publisher.emit(
            "game_over", {"winner": str(player_id)}, room=room.id
        )
        return {"status": "success", "message": "游戏胜利已设置"}

    async def debug_lose(self, room_id: str | None, player_id: str | None) -> dict:
        room = self.rooms.get_room(room_id)
        if room is None or not player_id or player_id not in room.players:
            return {"status": "error", "message": "无效的房间或玩家"}
        opponent_id = room.opponent_of(str(player_id))
        room.state = RoomState.GAME_OVER
        room.winner = opponent_id or ""
        await self._publisher.emit(
            "game_over", {"winner": room.winner}, room=room.id
        )
        return {"status": "success", "message": "游戏失败已设置"}
