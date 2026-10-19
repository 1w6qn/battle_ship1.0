"""Gameplay use cases: placement, RPS, phases, turn timer.

The socket layer only translates frames into calls on this service; every rule
lives in :mod:`battleship.domain.placement` / :mod:`battleship.domain.battle`.
Rooms are in-memory (no room table), so this ticket writes no SQL and needs no
unit of work; match settlement (#12) enters through `repositories.UnitOfWork`.

Two seams are injected so later tickets do not have to edit this file:

* `draw_hook(room, player_id) -> Any` -- ticket #10 owns the real deck/hand.
  The RPS resolution calls it once for the first player and twice for the
  second, exactly the frozen 1/2 draw contract; its return value is what
  `game_state.winner_card` / `loser_cards` carry.
* `fire_hook(room, player_id, x, y)` -- ticket #9 owns attack effects. The
  turn watchdog picks an attackable random cell and hands it over; without the
  hook the watchdog reports that firing is not wired yet instead of faking a
  shot or declaring a loss.

`TURN_TIMEOUT_SECONDS` (default 90, 0 disables) only performs fallback
actions. It never declares a loser, and every successful action by the current
attacker restarts the clock.
"""

from __future__ import annotations

import asyncio
import inspect
import random
import time
from typing import Any, Callable

from ..contracts.identity import ai_player_id
from ..domain import battle as battle_rules
from ..domain import placement as placement_rules
from ..domain.placement import PlacementError
from ..domain.room import Room, RoomPhase, RoomState, rank_payload
from ..infra.logging import get_logger
from .rooms import Connection, EventPublisher, NullPublisher, RoomService

logger = get_logger("gameplay")

INVALID_SEAT = {"status": "error", "message": "无效的房间或玩家"}
FINISHED_GAME = {"status": "error", "message": "对局已结束"}
NO_PENDING_PLACEMENT = {"status": "error", "message": "没有等待放置的战舰"}
OPPONENT_DISCONNECTED = "对手已掉线，等待重连中"
DEFAULT_TURN_TIMEOUT_SECONDS = 90
DEFAULT_TICK_SECONDS = 1.0


def _state_value(room: Room) -> str:
    """Accept both the enum and a legacy plain string stored by older flows."""

    return getattr(room.state, "value", room.state)


def _phase_value(room: Room) -> str:
    return getattr(room.current_phase, "value", room.current_phase)


class GameplayService:
    """Use cases for one room's placement / RPS / phase / turn lifecycle."""

    def __init__(
        self,
        rooms: RoomService,
        *,
        turn_timeout_seconds: int = DEFAULT_TURN_TIMEOUT_SECONDS,
        tick_seconds: float = DEFAULT_TICK_SECONDS,
        draw_hook: Callable[[Room, str], Any] | None = None,
        fire_hook: Callable[[Room, str, int, int], Any] | None = None,
        rng: Any | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.rooms = rooms
        self.turn_timeout_seconds = int(turn_timeout_seconds)
        self.tick_seconds = float(tick_seconds)
        self.draw_hook = draw_hook
        self.fire_hook = fire_hook
        # Default to the module-level RNG, exactly like the legacy handlers, so
        # `random.seed(...)` (and monkeypatching) keeps tests reproducible.
        self.rng = rng or random
        self.clock = clock or (lambda: time.time())
        self._publisher: EventPublisher = NullPublisher()
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------------ wiring

    def bind(self, publisher: EventPublisher) -> None:
        self._publisher = publisher

    def start(self) -> None:
        """Start the turn watchdog on the running event loop (idempotent)."""

        if self._task is not None:
            return
        self._task = asyncio.get_running_loop().create_task(self._watch_loop())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _watch_loop(self) -> None:
        while True:
            await asyncio.sleep(self.tick_seconds)
            try:
                await self.sweep_timeouts()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # one bad room must not stop the watchdog
                logger.error(
                    "turn watchdog sweep failed",
                    extra={"error_type": type(error).__name__},
                    exc_info=error,
                )

    # --------------------------------------------------------------- helpers

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
    def _frozen_reason(room: Room, player_id: str) -> str | None:
        for pid in room.disconnected:
            if pid != player_id:
                return OPPONENT_DISCONNECTED
        return None

    def _start_timer(self, room: Room, now: float | None = None) -> None:
        room.turn_started_at = self.clock() if now is None else now
        room.turn_timer_attacker = room.current_attacker or None

    def _touch_turn(self, room: Room, player_id: str) -> None:
        if room.current_attacker == player_id:
            self._start_timer(room)

    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value

    async def _draw(self, room: Room, player_id: str) -> Any:
        """Draw seam: explicit hook first, then a room-level `draw_card`.

        Ticket #10 may implement `Room.draw_card` without touching this service;
        until then the hook default returns None (legacy draws from an empty deck
        also yield None).
        """

        if self.draw_hook is not None:
            return await self._maybe_await(self.draw_hook(room, player_id))
        method = getattr(room, "draw_card", None)
        if callable(method):
            return await self._maybe_await(method(player_id))
        return None

    async def _emit_message(self, room: Room, player_id: str, note: str) -> None:
        player = room.players.get(player_id)
        if player is not None and player.socket_id:
            await self._publisher.emit("message", {"text": note}, to=player.socket_id)
        await self._publisher.emit(
            "game_message", {"message": note, "type": "warning"}, room=room.id
        )

    # ------------------------------------------------------------- placement

    async def place_ships(self, connection: Connection,
                          data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        room, player_id = self._seat(connection, data)
        if room is None:
            return dict(INVALID_SEAT)
        if _state_value(room) == RoomState.GAME_OVER.value:
            return dict(FINISHED_GAME)

        player = room.players[player_id]
        try:
            ships = placement_rules.validate_placement(
                data.get("ships"), placement_rules.expected_ship_count(player)
            )
        except PlacementError as error:
            return {"status": "error", "message": str(error)}
        placement_rules.apply_placement(player, ships)

        # AI room: the human's submission also fills the AI seat (legacy).
        if room.is_ai_room:
            seat_id = ai_player_id(room.id)
            ai = room.players.get(seat_id)
            if ai is not None and seat_id != player_id and not ai.ships:
                placement_rules.auto_place_ai(room, seat_id, self.rng)

        if placement_rules.all_players_placed(room):
            # Deliberate direct assignment (DECISIONS D1): the legacy handler has
            # no state gate, so re-placing during battle falls back to RPS.
            room.state = RoomState.ROCK_PAPER_SCISSORS
            room.rps_choices = {}
            room.rps_processed = False
            await self._publisher.emit(
                "game_state",
                {"state": RoomState.ROCK_PAPER_SCISSORS.value, **rank_payload(room)},
                room=room.id,
            )

        self._touch_turn(room, player_id)
        return {"status": "success"}

    async def cancel_placement(self, connection: Connection,
                               data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        room, player_id = self._seat(connection, data)
        if room is None:
            return dict(INVALID_SEAT)

        pending = (room.magic_temp_data or {}).get("pending_placement")
        if not pending or pending.get("caster") != player_id:
            return dict(NO_PENDING_PLACEMENT)

        # Ticket #10 replaces this body with _finish_placement (attack-budget
        # adjustments for reinforcement / last stand). Opening placement never
        # creates pending_placement, so today this only clears the panel.
        room.magic_temp_data.pop("pending_placement", None)
        player = room.players.get(player_id)
        if player is not None and player.socket_id:
            await self._publisher.emit(
                "message", {"text": "已放弃剩余放置"}, to=player.socket_id
            )
        return {"status": "success"}

    # ------------------------------------------------------------------- RPS

    async def rps_choice(self, connection: Connection,
                         data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        room, player_id = self._seat(connection, data)
        if room is None:
            return dict(INVALID_SEAT)
        if _state_value(room) == RoomState.GAME_OVER.value:
            return dict(FINISHED_GAME)

        choice = data.get("choice")
        if choice not in battle_rules.RPS_CHOICES:
            return {"status": "error", "message": "无效的出拳"}

        if room.is_ai_room:
            ai_id = ai_player_id(room.id)
            if ai_id in room.players and ai_id not in room.rps_choices:
                forced = getattr(room, "test_ai_rps_choice", None)
                room.rps_choices[ai_id] = (
                    forced
                    if forced in battle_rules.RPS_CHOICES
                    else self.rng.choice(battle_rules.RPS_CHOICES)
                )
                if hasattr(room, "test_ai_rps_choice"):
                    delattr(room, "test_ai_rps_choice")

        room.rps_choices[player_id] = choice

        if len(room.rps_choices) == len(room.players) and not room.rps_processed:
            room.rps_processed = True
            outcome = battle_rules.resolve_rps(room.rps_choices, list(room.players))
            await self._publisher.emit("rps_result", outcome.to_dict(), room=room.id)

            if outcome.status == "tie" or len(outcome.order) < 2:
                room.rps_choices = {}
                room.rps_processed = False
                return {"status": "success", "message": "平局，重新猜拳"}

            room.attack_order = list(outcome.order)
            winner, loser = outcome.order[0], outcome.order[1]
            room.current_attacker = winner
            room.attacks_remaining = battle_rules.attacks_remaining_for(
                room.players[winner]
            )

            # Frozen draw contract: first player 1 card, second player 2 cards.
            winner_card = await self._draw(room, winner)
            loser_card1 = await self._draw(room, loser)
            loser_card2 = await self._draw(room, loser)

            room.state = RoomState.ATTACKING
            if not room.match_started_at:
                room.match_started_at = self.clock()
            room.current_phase = RoomPhase.PREPARATION
            self._start_timer(room)

            await self._publisher.emit(
                "game_state",
                {
                    "state": RoomState.ATTACKING.value,
                    "current_attacker": winner,
                    "current_phase": RoomPhase.PREPARATION.value,
                    "attacks_remaining": room.attacks_remaining,
                    "winner_card": winner_card,
                    "loser_cards": [loser_card1, loser_card2],
                    "round": room.round,
                    "attack_order": list(room.attack_order),
                    **rank_payload(room),
                },
                room=room.id,
            )

        return {"status": "success"}

    # ---------------------------------------------------------------- phases

    async def _emit_phase(self, room: Room) -> None:
        await self._publisher.emit(
            "phase_updated",
            {
                "current_phase": _phase_value(room),
                "current_attacker": room.current_attacker,
            },
            room=room.id,
        )

    async def enter_battle_phase(self, connection: Connection,
                                 data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        room, player_id = self._seat(connection, data)
        if room is None:
            return dict(INVALID_SEAT)
        if _state_value(room) == RoomState.GAME_OVER.value:
            return dict(FINISHED_GAME)
        frozen = self._frozen_reason(room, player_id)
        if frozen:
            return {"status": "error", "message": frozen}

        error = battle_rules.enter_battle(room, player_id)
        if error:
            return {"status": "error", "message": error}

        await self._publisher.emit(
            "attacks_updated",
            {
                "current_attacker": room.current_attacker,
                "attacks_remaining": room.attacks_remaining,
            },
            room=room.id,
        )
        await self._emit_phase(room)
        self._touch_turn(room, player_id)
        return {"status": "success"}

    async def enter_end_phase(self, connection: Connection,
                              data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        room, player_id = self._seat(connection, data)
        if room is None:
            return dict(INVALID_SEAT)
        if _state_value(room) == RoomState.GAME_OVER.value:
            return dict(FINISHED_GAME)
        frozen = self._frozen_reason(room, player_id)
        if frozen:
            return {"status": "error", "message": frozen}

        error = battle_rules.enter_end(room, player_id)
        if error:
            return {"status": "error", "message": error}

        await self._emit_phase(room)
        self._touch_turn(room, player_id)
        return {"status": "success", "message": "已进入结束阶段"}

    async def _apply_turn_end(self, room: Room, player_id: str) -> dict | None:
        result = battle_rules.resolve_turn_end(room, player_id)
        if result is None:
            return None

        if result.kind == "skip_stages":
            await self._emit_phase(room)
            await self._publisher.emit(
                "turn_skipped",
                {
                    "skipped": player_id,
                    "current_attacker": room.current_attacker,
                    "round": room.round,
                },
                room=room.id,
            )
            self._start_timer(room)
            return {"status": "success", "message": "神之宣告：对方本回合被跳过"}

        if result.kind == "new_round":
            await self._publisher.emit(
                "game_state",
                {
                    "state": RoomState.ROCK_PAPER_SCISSORS.value,
                    "round": room.round,
                    **rank_payload(room),
                },
                room=room.id,
            )
            self._start_timer(room)
            return {"status": "success", "new_round": True}

        await self._emit_phase(room)
        await self._publisher.emit(
            "turn_change",
            {
                "current_attacker": room.current_attacker,
                "attacks_remaining": room.attacks_remaining,
                "phase": _phase_value(room),
            },
            room=room.id,
        )
        self._start_timer(room)
        return {"status": "success"}

    async def end_turn(self, connection: Connection,
                       data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        room, player_id = self._seat(connection, data)
        if room is None:
            return dict(INVALID_SEAT)
        if _state_value(room) == RoomState.GAME_OVER.value:
            return dict(FINISHED_GAME)
        frozen = self._frozen_reason(room, player_id)
        if frozen:
            return {"status": "error", "message": frozen}
        if room.chain or room.chain_waiting:
            return {"status": "error", "message": battle_rules.CHAIN_BUSY_ERROR}

        ack = await self._apply_turn_end(room, player_id)
        if ack is None:
            return {"status": "error", "message": battle_rules.END_TURN_ERROR}
        return ack

    # --------------------------------------------------------------- timeout

    async def sweep_timeouts(self, now: float | None = None) -> list[str]:
        """One watchdog pass. Returns the rooms that performed a fallback action."""

        if self.turn_timeout_seconds <= 0:
            return []
        now = self.clock() if now is None else now
        acted: list[str] = []
        for room in list(self.rooms.get_all_rooms().values()):
            if _state_value(room) != RoomState.ATTACKING.value:
                continue
            if room.is_ai_room:
                continue  # AI turns are driven by the AI layer, not the watchdog
            player_id = room.current_attacker
            if not player_id or player_id not in room.players:
                continue
            if room.turn_timer_attacker != player_id:
                self._start_timer(room, now)
                continue
            if room.turn_started_at is None:
                self._start_timer(room, now)
                continue
            if now - room.turn_started_at < self.turn_timeout_seconds:
                continue
            if room.chain or room.chain_waiting:
                continue
            if room.disconnected:
                continue
            temp = room.magic_temp_data or {}
            if (
                temp.get("pending_placement")
                or temp.get("pending_shenji")
                or any(
                    isinstance(pick, dict) and pick.get("player") == player_id
                    for pick in room.pending_ship_picks
                )
            ):
                continue
            if await self._timeout_action(room, player_id, now):
                acted.append(room.id)
        return acted

    async def _timeout_action(self, room: Room, player_id: str, now: float) -> bool:
        note: str | None = None
        if _phase_value(room) == "preparation":
            if battle_rules.enter_battle(room, player_id) is None:
                await self._publisher.emit(
                    "attacks_updated",
                    {
                        "current_attacker": room.current_attacker,
                        "attacks_remaining": room.attacks_remaining,
                    },
                    room=room.id,
                )
                await self._emit_phase(room)
                note = "思考超时：已自动进入战斗阶段"

        elif _phase_value(room) == "battle":
            player = room.players[player_id]
            cells = battle_rules.attackable_cells(player)
            if not cells or room.attacks_remaining <= 0:
                if battle_rules.enter_end(room, player_id) is None:
                    await self._emit_phase(room)
                    note = "思考超时：已自动进入结束阶段"
            else:
                x, y = self.rng.choice(cells)
                if self.fire_hook is None:
                    # Ticket #9 owns attack effects; do not fake a shot.
                    note = "思考超时：自动开火待攻击能力接入"
                else:
                    await self._maybe_await(self.fire_hook(room, player_id, x, y))
                    note = f"思考超时：已自动开火 ({x},{y})"

        elif _phase_value(room) == "end":
            ack = await self._apply_turn_end(room, player_id)
            if ack is not None:
                note = (
                    "思考超时：已自动进入新的大回合"
                    if ack.get("new_round")
                    else "思考超时：已自动交出回合"
                )

        if note is None:
            self._start_timer(room, now)
            return False

        await self._emit_message(room, player_id, note)
        # end_turn already restarted the clock for the next attacker; the other
        # fallback actions happened on the same player's clock.
        if room.turn_timer_attacker == player_id:
            self._start_timer(room, now)
        return True