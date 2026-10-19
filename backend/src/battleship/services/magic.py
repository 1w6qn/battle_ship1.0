"""Magic-card use cases: deck/hand sync, targets, registry dispatch (ticket #10).

The socket layer only translates frames. This service owns the protocol-level
order the legacy handler had:

1. identity -> target sanitisation -> frozen/chain/priority/magic-blocked gates;
2. hand membership -> can_play_magic_card -> per-card requirement checks;
3. remove the card and push it on the chain stack;
4. resolve the stack (ticket #12 replaces this direct resolution with the real
   response window), refund on a failed effect, then re-push the authoritative
   hand / ships / effects / phase frames.

No business rule lives here: card behaviour is in
battleship.domain.magic.effects and registered in battleship.domain.magic.registry.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any, Awaitable, Callable

from ..domain import battle as battle_rules
from ..domain import replay as replay_rules
from ..domain.magic import deck as deck_rules
from ..domain.magic import registry
from ..domain.magic.cards import MagicCard, card_from_payload
from ..domain.magic import chain as chain_rules
from ..domain.magic.chain import CHAIN_RESPONSE_SECONDS, ChainItem, ChainResult
from ..domain.magic.effects.base import EffectContext, EffectResult
from ..domain.spectate.rules import AREA_TARGET_BOARDS
from ..domain.magic.rules import (
    action_wait_reason,
    can_play_magic_card,
    field_magic_name,
    lanyu_requirement_reason,
    last_attack_requirement_reason,
    playability_reason,
    wangyang_requirement_reason,
    woxin_requirement_reason,
)
from ..domain.room import Player, Room, RoomPhase, RoomState, build_room_sync
from ..domain.room.sync import EFFECT_BADGES, _spectate_chain_payload, card_payload
from ..infra.logging import get_logger
from ..infra.timers import TaskRegistry
from .rooms import Connection, EventPublisher, NullPublisher, RoomService
from .settlement import SettlementService

logger = get_logger("magic")

INVALID_SEAT = {"status": "error", "message": "无效的房间或玩家"}
FINISHED_GAME = {"status": "error", "message": "对局已结束"}
OPPONENT_DISCONNECTED = "对手已掉线，等待重连中"
CHAIN_BUSY = "连锁响应中，请先响应连锁"
UNIMPLEMENTED = "【{name}】效果尚未接入（后续批次），本张卡未消耗"

#: Fields a client may stage through select_magic_target (whitelist, not blacklist).
SELECTION_TARGET_KEYS = frozenset({
    "caster_choice", "opponent_choice", "card_index", "ship_indices",
    "effect_choice", "prediction", "index", "target_area", "target_line",
    "source", "source_index", "chosen_index",
})

KNOWN_CHOICE_IDS = frozenset({
    "taoyuan_choice", "lingqi_choice", "bury_choice", "wangyang_choice",
    "shield_choice",
})

CARD_DESCRIPTIONS: dict[str, str] = {}


def _init_descriptions() -> None:
    from ..domain.magic.cards import MAGIC_CARDS

    for card in MAGIC_CARDS:
        CARD_DESCRIPTIONS.setdefault(card.name, card.description)


_init_descriptions()


class MagicService:
    def __init__(
        self,
        rooms: RoomService,
        settlement: SettlementService | None = None,
        *,
        clock: Callable[[], float] | None = None,
        rng: Any | None = None,
        touch_turn: Callable[[Room, str], None] | None = None,
        chain_display_delay_seconds: float = 1.2,
        chain_response_seconds: float = CHAIN_RESPONSE_SECONDS,
        ai_chain_delay_seconds: float = 0.8,
        timers: TaskRegistry | None = None,
    ) -> None:
        self.rooms = rooms
        self.settlement = settlement
        self.clock = clock or time.time
        self.rng = rng
        self.touch_turn = touch_turn
        # 0 reproduces the pre-display-delay behaviour exactly (tests/headless).
        self.chain_display_delay_seconds = max(0.0, float(chain_display_delay_seconds))
        self.chain_response_seconds = max(0.0, float(chain_response_seconds))
        self.ai_chain_delay_seconds = max(0.0, float(ai_chain_delay_seconds))
        self.timers = timers or TaskRegistry()
        self._publisher: EventPublisher = NullPublisher()
        self.finish_hook: Callable[..., Awaitable[Any]] | None = None
        # Ticket #13 (priority) fills this; without it the chain still resolves.
        self.priority_continue_hook: Callable[..., Awaitable[Any]] | None = None
        # A destroyed room must not leave a 10s timer or a display task behind.
        hooks = getattr(rooms, "destroy_hooks", None)
        if hooks is not None:
            hooks.append(self.cancel_room_timers)

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
    def _state(room: Room) -> str:
        return getattr(room.state, "value", room.state)

    @staticmethod
    def _phase(room: Room) -> str:
        return getattr(room.current_phase, "value", room.current_phase)

    def _frozen_reason(self, room: Room, player_id: str) -> str | None:
        for pid in room.disconnected:
            if pid != player_id:
                return OPPONENT_DISCONNECTED
        return None

    async def _add_log(self, room: Room, text: str, event_type: str = "magic",
                       detail: dict | None = None) -> None:
        entry = {
            "ts": int(self.clock()),
            "type": event_type,
            "text": text,
            "detail": detail,
        }
        room.game_logs.append(entry)
        # Same single replay feed as BattleService.add_log (ticket #18).
        replay_rules.note(room, entry)
        await self._publisher.emit("game_log", entry, room=room.id)

    async def _emit_hand(self, player: Player) -> None:
        if not player.socket_id:
            return
        await self._publisher.emit(
            "hand_updated",
            {"hand": [card_payload(card) for card in player.magic_hand]},
            to=player.socket_id,
        )

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
                    "opponent_remaining_ships": opponent.remaining_ships if opponent else 0,
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

    @staticmethod
    def _badges(player: Player) -> list[dict[str, Any]]:
        badges: list[dict[str, Any]] = []
        flags = player.effect_flags
        for attr, label, expiry, suffix in EFFECT_BADGES:
            if not getattr(flags, attr, None):
                continue
            badges.append({
                "name": label,
                "key": attr,
                "label": f"{label}·{suffix}" if suffix else label,
                "description": CARD_DESCRIPTIONS.get(label, ""),
                "expires": expiry,
            })
        return badges

    async def _emit_active_effects(self, room: Room) -> None:
        for pid, player in room.players.items():
            if not player.socket_id:
                continue
            opponent_id = room.opponent_of(pid)
            opponent = room.players.get(opponent_id) if opponent_id else None
            await self._publisher.emit(
                "active_effects",
                {
                    "self": self._badges(player),
                    "opponent": self._badges(opponent) if opponent else [],
                },
                to=player.socket_id,
            )

    # -------------------------------------------------------------------- draw

    async def draw(self, room: Room, player_id: str) -> MagicCard | None:
        """Gameplay draw hook: shared deck + duplicate rule + hand frame."""

        result = deck_rules.draw_card(room, player_id, rng=self.rng)
        player = room.players.get(player_id)
        if player is not None and result.card is not None:
            await self._emit_hand(player)
        return result.card

    # --------------------------------------------------------------- play card

    async def use_magic_card(self, connection: Connection,
                             data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        existing = self.rooms.get_room(data.get("room_id"))
        if existing is not None and existing.state == RoomState.GAME_OVER:
            return dict(FINISHED_GAME)
        room, player_id = self._seat(connection, data)
        if room is None:
            return dict(INVALID_SEAT)
        if room.state == RoomState.GAME_OVER:
            return dict(FINISHED_GAME)
        try:
            card = card_from_payload(data.get("card"))
        except Exception as error:  # noqa: BLE001 - client data, never crash the handler
            return {"status": "error", "message": f"魔法卡数据无效: {error}"}

        targets, target_error = sanitize_targets(data.get("targets", {}), card.name)
        if target_error:
            return {"status": "error", "message": target_error}

        frozen = self._frozen_reason(room, player_id)
        if frozen:
            return {"status": "error", "message": frozen}
        player = room.players[player_id]
        opponent_id = room.opponent_of(player_id)
        if opponent_id is None:
            return {"status": "error", "message": "房间人数不足"}

        if room.chain_waiting or room.chain_resolving:
            return {"status": "error", "message": CHAIN_BUSY}
        wait = action_wait_reason(room, player_id)
        if wait:
            return {"status": "error", "message": wait}
        if player.magic_blocked:
            return {"status": "error", "message": "你的魔法卡已被看破，本回合无法使用"}
        if not any(
            candidate.name == card.name and candidate.speed == card.speed
            for candidate in player.magic_hand
        ):
            return {"status": "error", "message": "你没有这张魔法卡"}
        if not can_play_magic_card(room, player_id, card):
            return {"status": "error", "message": playability_reason(room, player_id, card)}
        for reason in (
            last_attack_requirement_reason(room, player_id, card),
            wangyang_requirement_reason(room, player_id, card),
            woxin_requirement_reason(room, player_id, card),
            lanyu_requirement_reason(room, player_id, card),
        ):
            if reason:
                return {"status": "error", "message": reason}
        if not registry.is_implemented(card):
            return {
                "status": "error",
                "message": UNIMPLEMENTED.format(name=card.name),
            }

        # Remove the declared copy, then push it on the chain. Non-field cards
        # go to the shared discard pile immediately (legacy).
        for index, candidate in enumerate(player.magic_hand):
            if candidate.name == card.name and candidate.speed == card.speed:
                player.magic_hand.pop(index)
                break
        if card.type != "场地":
            room.magic_discard.append(card)
        await self._emit_hand(player)
        # Replay: the card leaves the hand at this instant, not at resolution.
        replay_rules.note_card_played(room, player_id, card)

        room.chain.append(ChainItem(player_id, card, targets, self.clock()))
        await self._publisher.emit(
            "magic_chain_updated", _spectate_chain_payload(room), room=room.id
        )
        # The response window starts on the opponent; a card that nobody can
        # answer falls through both passes and resolves (after the display
        # delay, unless it is 0).
        await self._open_chain_window(room, player_id)
        return {"status": "success", "message": f"魔法卡{card.name}已加入连锁"}

    # ------------------------------------------------------------ chain engine

    async def _open_chain_window(self, room: Room, caster_id: str) -> None:
        room.chain_passes = 0
        await self._advance_chain_window(room, room.opponent_of(caster_id))

    async def _advance_chain_window(self, room: Room, player_id: str | None,
                                    *, display_delay: bool = True) -> None:
        """Hand the window to the player who may respond, or resolve.

        A player who cannot respond is recorded as a pass and the window moves
        to the opponent; two consecutive passes end the chain. `display_delay`
        is False only on the 10-second timeout path (legacy: that path must not
        add a second pause after the window already stayed open for 10s).
        """

        while True:
            if not player_id or player_id not in room.players:
                await self.resolve_chain(room)
                return
            if chain_rules.can_respond(room, player_id):
                room.chain_window = player_id
                room.chain_waiting = True
                room.chain_timer += 1
                token = room.chain_timer
                top = room.chain[-1]
                player = room.players[player_id]
                await self._publisher.emit(
                    "chain_request",
                    {
                        "card": card_payload(top.card),
                        # Self-chain: the window can come back to the last
                        # caster, so the client must not assume "opponent".
                        "caster": top.player_id,
                        "speed3_cards": [
                            card_payload(card)
                            for card in chain_rules.speed3_cards(player)
                        ],
                        "countdown": CHAIN_RESPONSE_SECONDS,
                    },
                    to=player.socket_id,
                )
                self._schedule_chain_timeout(room.id, token)
                if player_id.startswith("ai-"):
                    self._schedule_ai_response(room.id, token)
                return
            room.chain_passes += 1
            if room.chain_passes >= 2:
                await self._finish_chain(room, display_delay=display_delay)
                return
            player_id = room.opponent_of(player_id)

    async def _finish_chain(self, room: Room, *, display_delay: bool = True) -> bool:
        """End the chain; returns True when a delayed resolve task was queued."""

        if not display_delay or self.chain_display_delay_seconds <= 0:
            await self.resolve_chain(room)
            return False
        room.chain_timer += 1
        token = room.chain_timer
        room.chain_display_token = token
        room.chain_display_deadline = (
            time.monotonic() + self.chain_display_delay_seconds + 5.0
        )
        task = self.timers.spawn(room.id, self._chain_display_then_resolve(room.id, token))
        if task is None:
            # No running loop: never leave the chain hanging; resolve inline.
            chain_rules.clear_display(room)
            await self.resolve_chain(room)
            return False
        return True

    async def _chain_display_then_resolve(self, room_id: str, token: int) -> None:
        await asyncio.sleep(self.chain_display_delay_seconds)
        room = self.rooms.get_room(room_id)
        if room is None or room.chain_display_token != token:
            return
        chain_rules.clear_display(room)
        if not chain_rules.display_still_current(room, token):
            return
        await self.resolve_chain(room)

    def _schedule_chain_timeout(self, room_id: str, token: int) -> None:
        self.timers.spawn(room_id, self._chain_timeout(room_id, token))

    async def _chain_timeout(self, room_id: str, token: int) -> None:
        await asyncio.sleep(self.chain_response_seconds)
        room = self.rooms.get_room(room_id)
        if room is None or not room.chain_waiting or room.chain_timer != token:
            return
        window_player = room.chain_window
        room.chain_waiting = False
        room.chain_window = None
        room.chain_passes += 1
        if room.chain_passes >= 2 or window_player is None:
            # The 10s window already displayed the chain; no extra pause.
            await self.resolve_chain(room)
            return
        await self._advance_chain_window(
            room, room.opponent_of(window_player), display_delay=False
        )

    def _schedule_ai_response(self, room_id: str, token: int) -> None:
        self.timers.spawn(room_id, self._ai_chain_respond(room_id, token))

    async def _ai_chain_respond(self, room_id: str, token: int) -> None:
        """Hard AI: spend 失灵！ when it can, otherwise pass immediately."""

        await asyncio.sleep(self.ai_chain_delay_seconds)
        room = self.rooms.get_room(room_id)
        if room is None or getattr(room.state, "value", room.state) == "game_over":
            return
        if not room.chain_waiting or room.chain_timer != token:
            return
        ai_id = room.chain_window
        if not ai_id or not ai_id.startswith("ai-"):
            return
        player = room.players.get(ai_id)
        if player is None:
            return
        card = next((card for card in player.magic_hand if card.name == "失灵！"), None)
        if card is None or not chain_rules.ai_can_negate_chain_top(room, ai_id):
            await self.chain_response(
                None, {"room_id": room_id, "player_id": ai_id, "chain": False}
            )
            return
        ack = await self.chain_response(
            None,
            {
                "room_id": room_id,
                "player_id": ai_id,
                "chain": True,
                "card": {"name": card.name},
                "targets": [],
            },
        )
        if not (ack and ack.get("status") == "success"):
            await self.chain_response(
                None, {"room_id": room_id, "player_id": ai_id, "chain": False}
            )

    async def chain_response(self, connection: Connection | None,
                             data: dict[str, Any] | None = None) -> dict:
        """Answer the open window: play a speed-3 card or pass.

        `connection=None` is the internal AI path: the player id is trusted
        because no client can reach this method without the socket adapter,
        which always passes a verified connection.
        """

        data = data if isinstance(data, dict) else {}
        room = self.rooms.get_room(data.get("room_id"))
        player_id = data.get("player_id")
        if (
            room is None
            or not player_id
            or player_id not in room.players
            or (connection is not None
                and not self.rooms.identity_ok(room, str(player_id), connection))
        ):
            return dict(INVALID_SEAT)

        chain = bool(data.get("chain", False))
        card_payload_data = data.get("card")
        raw_targets = data.get("targets", [])
        if isinstance(raw_targets, dict):
            targets, target_error = sanitize_targets(
                raw_targets,
                card_payload_data.get("name")
                if isinstance(card_payload_data, dict)
                else None,
            )
            if target_error:
                return {"status": "error", "message": target_error}
        else:
            targets = raw_targets

        if not room.chain_waiting:
            return {"status": "error", "message": "没有待处理的连锁请求"}
        if room.chain_window and room.chain_window != player_id:
            return {"status": "error", "message": "当前不是你的连锁响应窗口"}

        # Closing the window is what makes late/stale answers impossible.
        room.chain_waiting = False
        room.chain_window = None

        if chain and card_payload_data:
            try:
                card = card_from_payload(card_payload_data)
            except Exception as error:  # noqa: BLE001 - client data
                return {"status": "error", "message": f"魔法卡数据无效: {error}"}
            player = room.players[str(player_id)]
            # 看破！ suppress: pass and advance, never leave the window half-open.
            if player.magic_blocked:
                await self._pass_after_refusal(room, str(player_id))
                return {"status": "error", "message": "你的魔法卡已被看破，无法连锁"}

            hand_card = next(
                (
                    candidate
                    for candidate in player.magic_hand
                    if candidate.name == card.name and candidate.speed == card.speed
                ),
                None,
            )
            if hand_card is None:
                return {"status": "error", "message": "你没有这张魔法卡"}
            card = hand_card
            if int(card.speed) != 3:
                return {"status": "error", "message": "只能使用速阶3的卡牌进行连锁"}

            # Same playability gate as a normal play (禁忌果实 / 绝处逢生).
            if not can_play_magic_card(room, str(player_id), card):
                await self._pass_after_refusal(room, str(player_id))
                return {"status": "error", "message": "当前无法使用这张魔法卡"}

            for index, candidate in enumerate(player.magic_hand):
                if candidate.name == card.name and candidate.speed == card.speed:
                    player.magic_hand.pop(index)
                    break
            room.magic_discard.append(card)
            await self._emit_hand(player)
            # Replay: chained play is a play, recorded at the same moment.
            replay_rules.note_card_played(room, str(player_id), card, chained=True)

            room.chain.append(ChainItem(str(player_id), card, targets, self.clock()))
            await self._publisher.emit(
                "magic_chain_updated", _spectate_chain_payload(room), room=room.id
            )
            # A new card clears the pass count; the window goes to the opponent
            # and can come back for self-chaining.
            room.chain_passes = 0
            await self._advance_chain_window(room, room.opponent_of(str(player_id)))
            return {"status": "success", "message": f"魔法卡{card.name}已加入连锁"}

        room.chain_passes += 1
        if room.chain_passes >= 2:
            await self._finish_chain(room)
        else:
            await self._advance_chain_window(room, room.opponent_of(str(player_id)))
        return {"status": "success", "message": "放弃连锁"}

    async def _pass_after_refusal(self, room: Room, player_id: str) -> None:
        room.chain_passes += 1
        if room.chain_passes >= 2:
            await self._finish_chain(room)
        else:
            await self._advance_chain_window(room, room.opponent_of(player_id))

    async def resolve_chain(self, room: Room) -> list[ChainResult]:
        """Resolve once; a re-entrant call during async effects is a no-op."""

        if room.chain_resolving:
            return []
        room.chain_resolving = True
        try:
            return await self._resolve_chain(room)
        finally:
            room.chain_resolving = False

    async def _resolve_chain(self, room: Room) -> list[ChainResult]:
        """Resolve LIFO. Negated items are skipped (DECISIONS D2)."""

        results: list[ChainResult] = []
        while room.chain:
            item = room.chain.pop()
            if getattr(item, "negated", False):
                by = getattr(item, "negated_by", None)
                detail = (
                    f"{item.card.name}被{by}无效化"
                    if by
                    else f"{item.card.name}被无效化"
                )
                result = ChainResult(
                    card=item.card,
                    caster=item.player_id,
                    success=False,
                    message=detail,
                    negated_skip=True,
                    negated_by=by,
                )
                # A negated field card only goes to the discard pile; it must
                # never replace or tear down the field already in play.
                if item.card.type == "场地" and room.field_magic is not item.card:
                    room.magic_discard.append(item.card)
                suffix = f"但被{by}无效化" if by else "但被无效化"
                await self._add_log(
                    room,
                    f"第{room.round}回合 · {self._name(room, item.player_id)} 使用了"
                    f"【{item.card.name}】{suffix}",
                    "magic",
                    {"caster": item.player_id, "card": item.card.name},
                )
                results.append(result)
                continue

            effect = registry.effect_for(item.card)
            if effect is None:
                effect_result = EffectResult(
                    False, UNIMPLEMENTED.format(name=item.card.name)
                )
            else:
                try:
                    effect_result = await effect(self._context(room, item))
                except Exception as error:  # one bad card must not kill the room
                    logger.error(
                        "magic effect failed",
                        extra={
                            "room_id": room.id,
                            "card": item.card.name,
                            "error_type": type(error).__name__,
                        },
                        exc_info=error,
                    )
                    effect_result = EffectResult(
                        False, "魔法卡效果结算失败，卡牌已退回手牌"
                    )

            chain_result = ChainResult(
                card=item.card,
                caster=item.player_id,
                success=effect_result.success,
                message=effect_result.message,
                negate_target=effect_result.negate_target,
                affected_positions=effect_result.affected_positions,
                game_over=effect_result.game_over,
            )
            await self._add_log(
                room,
                f"第{room.round}回合 · {self._name(room, item.player_id)} 使用了"
                f"【{item.card.name}】"
                + (
                    f"，{effect_result.message}"
                    if effect_result.success and effect_result.message
                    else ""
                ),
                "magic",
                {"caster": item.player_id, "card": item.card.name},
            )
            if not effect_result.success and not effect_result.game_over:
                await self._refund(
                    room, item.player_id, item.card, effect_result.message
                )
            elif effect_result.success:
                entry = {
                    "card": item.card,
                    "caster": item.player_id,
                    "timestamp": self.clock(),
                    "round": room.round,
                }
                ledger = room.game_effects.get("stolen_cards") or {}
                if id(item.card) in ledger:
                    entry["stolen"] = True
                room.magic_history.append(entry)

            # Negation marks the item directly below *after* this one resolved,
            # which is exactly the next item to pop.
            if chain_result.negate_target and room.chain:
                room.chain[-1].negated = True
                room.chain[-1].negated_by = item.card.name
            results.append(chain_result)

        await self._publisher.emit(
            "chain_resolved",
            {"results": [result.to_dict() for result in results]},
            room=room.id,
        )
        room.chain = []
        room.chain_waiting = False
        room.chain_window = None
        room.chain_passes = 0
        chain_rules.clear_display(room)
        # The stolen-card ledger is merged; clear it so ids cannot be reused.
        room.game_effects.pop("stolen_cards", None)

        await self._emit_active_effects(room)
        for player in room.players.values():
            await self._emit_hand(player)
        await self._emit_ships_updated(room)
        for pid in room.players:
            await self._emit_player_ships(room, pid)
        # Legacy order: phase_updated comes after every sync frame, even on the
        # game-over path (game_over itself was emitted by the effect).
        await self._publisher.emit(
            "phase_updated",
            {
                "current_phase": self._phase(room),
                "current_attacker": room.current_attacker,
            },
            room=room.id,
        )

        # A priority prompt interrupted by a speed-3 response resumes now.
        cont = room.priority_continue
        if cont and self.priority_continue_hook is not None:
            room.priority_continue = None
            await self._maybe_await(self.priority_continue_hook(room, cont))
        return results

    # ------------------------------------------------------- timer lifecycle

    def cancel_room_timers(self, room_id: str) -> int:
        """Destroy hook: cancel every background wait owned by one room."""

        room = self.rooms.get_room(room_id)
        if room is not None:
            chain_rules.clear_display(room)
        return self.timers.cancel_room(room_id)

    def pending_chain_tasks(self, room_id: str | None = None) -> int:
        return self.timers.pending(room_id)

    async def stop(self) -> None:
        """Server shutdown: cancel every chain/display/AI wait."""

        await self.timers.cancel_all()

    def _context(self, room: Room, item: ChainItem) -> EffectContext:
        opponent_id = room.opponent_of(item.player_id)
        assert opponent_id is not None

        async def emit(event: str, data: dict[str, Any], *, to: str | None = None,
                       room_id: str | None = None) -> None:
            await self._publisher.emit(event, data, to=to, room=room_id)

        async def draw(player_id: str) -> MagicCard | None:
            return await self.draw(room, player_id)

        async def log(text: str, event_type: str = "magic",
                      detail: dict | None = None) -> None:
            await self._add_log(room, text, event_type, detail)

        async def finish(winner: str, loser: str, reason: str) -> None:
            await self.finish(room, winner, loser, reason)

        async def sync_ships() -> None:
            await self._emit_ships_updated(room)

        async def sync_player_ships(player_id: str) -> None:
            await self._emit_player_ships(room, player_id)

        async def sync_hand(player_id: str) -> None:
            player = room.players.get(player_id)
            if player is not None:
                await self._emit_hand(player)

        async def sync_active_effects() -> None:
            await self._emit_active_effects(room)

        async def on_ship_sunk(player_id: str, ship: Any) -> None:
            await self.on_ship_sunk(room, player_id, ship, magic=True)

        async def notify_treasure(times: int, exclude: str | None) -> None:
            await self.notify_treasure(room, times, exclude_player_id=exclude)

        async def grant_attacks(n: int) -> int:
            gained = battle_rules.grant_extra_attacks(room, item.player_id, n)
            if gained:
                await self._publisher.emit(
                    "attacks_updated",
                    {
                        "current_attacker": room.current_attacker,
                        "attacks_remaining": room.attacks_remaining,
                    },
                    room=room.id,
                )
            return gained

        async def maybe_wuxian() -> bool:
            return await self.maybe_wuxian(room, item.player_id)

        async def emit_passthrough(event: str, data: dict[str, Any], *,
                                   to: str | None = None,
                                   room: str | None = None) -> None:
            await self._publisher.emit(event, data, to=to, room=room)

        return EffectContext(
            room=room,
            caster_id=item.player_id,
            opponent_id=opponent_id,
            card=item.card,
            targets=item.targets if isinstance(item.targets, dict) else {},
            emit=emit_passthrough,
            draw=draw,
            log=log,
            finish=finish,
            sync_ships=sync_ships,
            sync_player_ships=sync_player_ships,
            sync_hand=sync_hand,
            sync_active_effects=sync_active_effects,
            on_ship_sunk=on_ship_sunk,
            notify_treasure=notify_treasure,
            grant_attacks=grant_attacks,
            maybe_wuxian=maybe_wuxian,
        )

    async def _refund(self, room: Room, player_id: str, card: MagicCard,
                      message: str) -> None:
        player = room.players.get(player_id)
        if player is None:
            return
        if not any(candidate is card for candidate in player.magic_hand):
            player.magic_hand.append(card)
        for index, candidate in enumerate(room.magic_discard):
            if candidate is card:
                room.magic_discard.pop(index)
                break
        await self._emit_hand(player)
        if player.socket_id:
            await self._publisher.emit("message", {"text": message}, to=player.socket_id)

    # ------------------------------------------------------------------ ending

    async def finish(self, room: Room, winner: str, loser: str, reason: str) -> Any:
        if self.finish_hook is None:
            return None
        return await self._maybe_await(
            self.finish_hook(room, winner, loser, reason=reason)
        )

    # --------------------------------------------------------------- target API

    async def select_magic_target(self, connection: Connection,
                                  data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        room, player_id = self._seat(connection, data)
        if room is None:
            return dict(INVALID_SEAT)
        target_data = data.get("target_data")
        if not isinstance(target_data, dict):
            return {"status": "error", "message": "目标数据格式错误"}
        safe = {
            key: value for key, value in target_data.items()
            if key in SELECTION_TARGET_KEYS
        }
        room.magic_temp_data = {**(room.magic_temp_data or {}), **safe}
        temp_data_id = data.get("temp_data_id")
        if temp_data_id in KNOWN_CHOICE_IDS:
            return await self.confirm_magic_target({
                "room_id": room.id,
                "player_id": player_id,
                "temp_data_id": temp_data_id,
                "target_data": safe,
            })
        return {"status": "success"}

    async def confirm_magic_target(self, connection: Connection | dict[str, Any],
                                   data: dict[str, Any] | None = None) -> dict:
        # select_magic_target re-enters through a plain dict (legacy shape).
        if isinstance(connection, dict):
            payload = connection
            room = self.rooms.get_room(payload.get("room_id"))
            player_id = payload.get("player_id")
            if room is None or not player_id or player_id not in room.players:
                return dict(INVALID_SEAT)
        else:
            payload = data if isinstance(data, dict) else {}
            room, player_id = self._seat(connection, payload)
            if room is None:
                return dict(INVALID_SEAT)
        temp_data_id = payload.get("temp_data_id")
        if temp_data_id not in KNOWN_CHOICE_IDS:
            return {"status": "error", "message": "无效的临时数据ID"}
        # Every known choice in batch A belongs to #11 (ship pick / placement /
        # discard choice); refusing explicitly is better than a silent no-op.
        return {
            "status": "error",
            "message": "当前没有待处理的魔法卡选择",
        }

    async def get_magic_temp_data(self, connection: Connection,
                                  data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        room, player_id = self._seat(connection, data)
        if room is None:
            return dict(INVALID_SEAT)
        temp = room.magic_temp_data or {}
        pending = temp.get("pending_placement") or {}
        shenji = temp.get("pending_shenji") or {}
        top_pick = self._top_ship_pick(room, player_id)
        owners = {
            temp.get("caster"),
            temp.get("caster_id"),
            pending.get("caster") if isinstance(pending, dict) else None,
            shenji.get("caster") if isinstance(shenji, dict) else None,
            player_id if top_pick is not None else None,
        }
        if player_id not in owners:
            return {"status": "error", "message": "没有等待你处理的魔法卡选择"}
        return {"status": "success", "data": temp}

    @staticmethod
    def _top_ship_pick(room: Room, player_id: str) -> dict[str, Any] | None:
        mine = [
            pick for pick in room.pending_ship_picks
            if isinstance(pick, dict) and pick.get("player") == player_id
        ]
        return mine[0] if mine else None

    async def get_discard_pile(self, connection: Connection,
                               data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        room, _player_id = self._seat(connection, data)
        if room is None:
            return dict(INVALID_SEAT)
        cards = deck_rules.unique_discard_pile(room.magic_discard)
        return {
            "status": "success",
            "discard_pile": [card_payload(card) for card in cards],
        }

    async def cancel_magic_selection(self, connection: Connection,
                                     data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        room, player_id = self._seat(connection, data)
        if room is None:
            return dict(INVALID_SEAT)
        temp = room.magic_temp_data or {}
        pending = temp.get("pending_placement")
        if pending and pending.get("caster") == player_id:
            return {"status": "error", "message": "放置尚未完成，请用放置面板的「放弃」"}
        if temp.get("caster") and temp.get("caster") != player_id:
            return {"status": "error", "message": "当前不是你的选择"}
        cancelled = temp.get("type")
        cards = temp.get("cards")
        if cancelled == "wangyang_choice":
            for card in cards or []:
                if isinstance(card, MagicCard):
                    room.magic_discard.append(card)
            own = temp.get("own_card")
            if isinstance(own, MagicCard):
                room.magic_discard.append(own)
        elif isinstance(cards, list):
            room.magic_deck.extend(card for card in cards if isinstance(card, MagicCard))
        room.magic_temp_data = {}
        player = room.players.get(player_id)
        if player and player.socket_id:
            await self._publisher.emit("message", {"text": "已取消本次选择"}, to=player.socket_id)
        return {"status": "success", "message": "已取消本次选择"}

    # --------------------------------------------------------------- battl

    async def notify_treasure(self, room: Room, times: int = 1,
                              exclude_player_id: str | None = None) -> int:
        """八方来财: every holder draws once per ship-count change."""

        total = 0
        holders = [
            pid for pid, player in room.players.items()
            if getattr(player.effect_flags, "treasure_hunter", False)
        ]
        for pid in holders:
            if exclude_player_id is not None and pid == exclude_player_id:
                continue
            for _ in range(max(0, int(times))):
                await self.draw(room, pid)
                total += 1
        return total

    async def on_ship_sunk(self, room: Room, defender_id: str, ship: Any,
                           *, magic: bool = False) -> None:
        """Shared sink side effects injected into BattleService (ticket #9 seam)."""

        defender = room.players.get(defender_id)
        if defender is None:
            return
        flags = defender.effect_flags
        if flags.subsidy:
            flags.subsidy_bonus = int(getattr(flags, "subsidy_bonus", 0) or 0) + 3
            if defender.socket_id:
                await self._publisher.emit(
                    "message", {"text": "百亿补贴生效，你的攻击次数 +3"},
                    to=defender.socket_id,
                )
        if "holy_heart" in room.game_effects:
            room.game_effects.pop("holy_heart", None)
            await self._publisher.emit(
                "holy_heart_interrupted",
                {"reason": "有战舰被击沉，无暇圣心效果中断"},
                room=room.id,
            )
        if getattr(ship, "trap", False):
            # 守株待兔 is an interactive sacrifice card (#11); the flag is only
            # ever set by that card, so batch A never reaches this branch.
            ship.trap = False
        if magic:
            await self.notify_treasure(room, 1, exclude_player_id=None)
        else:
            last = room.last_attack or {}
            await self.notify_treasure(room, 1, exclude_player_id=last.get("attacker"))

    async def on_damage(self, room: Room, attacker_id: str, outcome: Any) -> None:
        attacker = room.players.get(attacker_id)
        if attacker is None:
            return
        if attacker.effect_flags.vampire:
            await self.draw(room, attacker_id)
            if attacker.socket_id:
                await self._publisher.emit(
                    "message", {"text": "饮血效果发动，抽一张卡"}, to=attacker.socket_id
                )
        if attacker.effect_flags.battle_spirit:
            gained = battle_rules.grant_extra_attacks(room, attacker_id, 1)
            if gained:
                await self._publisher.emit(
                    "attacks_updated",
                    {
                        "current_attacker": room.current_attacker,
                        "attacks_remaining": room.attacks_remaining,
                    },
                    room=room.id,
                )
                if attacker.socket_id:
                    await self._publisher.emit(
                        "message", {"text": "越战越勇效果发动，攻击次数净增加1"},
                        to=attacker.socket_id,
                    )

    async def on_attacks_exhausted(self, room: Room, player_id: str) -> None:
        await self.maybe_wuxian(room, player_id)

    async def maybe_wuxian(self, room: Room, player_id: str) -> bool:
        player = room.players.get(player_id)
        if player is None or not getattr(player.effect_flags, "wuxian", False):
            return False
        if field_magic_name(room) == "教皇旨意":
            return False
        if room.current_attacker != player_id:
            return False
        if room.attacks_remaining > 0:
            return False
        if player.damage_dealt_this_turn > 0:
            return False
        player.effect_flags.wuxian = False
        room.attacks_remaining += 3
        await self._add_log(
            room,
            f"第{room.round}回合 · {self._name(room, player_id)} 触发五险一金，攻击次数 +3",
            "magic",
            {"player": player_id, "card": "五险一金"},
        )
        if player.socket_id:
            await self._publisher.emit(
                "message",
                {"text": "五险一金生效：攻击次数已用尽且未造成伤害，攻击次数 +3"},
                to=player.socket_id,
            )
        await self._publisher.emit(
            "attacks_updated",
            {
                "current_attacker": room.current_attacker,
                "attacks_remaining": room.attacks_remaining,
            },
            room=room.id,
        )
        await self._emit_active_effects(room)
        return True

    # ------------------------------------------------------------------ debug

    async def debug_add_card(self, room_id: str | None, player_id: str | None,
                             card_name: str) -> dict:
        from ..domain.magic.cards import card_by_name

        room = self.rooms.get_room(room_id)
        if room is None or not player_id or player_id not in room.players:
            return {"status": "error", "message": "无效的房间或玩家"}
        card = card_by_name(card_name)
        if card is None:
            return {"status": "error", "message": f"未找到名为 {card_name} 的魔法卡"}
        room.players[player_id].magic_hand.append(card)
        await self._emit_hand(room.players[player_id])
        return {"status": "success", "message": f"已添加 {card_name}"}

    async def debug_add_all_cards(self, room_id: str | None,
                                  player_id: str | None) -> dict:
        from ..domain.magic.cards import MAGIC_CARDS

        room = self.rooms.get_room(room_id)
        if room is None or not player_id or player_id not in room.players:
            return {"status": "error", "message": "无效的房间或玩家"}
        room.players[player_id].magic_hand = list(MAGIC_CARDS)
        await self._emit_hand(room.players[player_id])
        return {"status": "success", "message": f"已添加 {len(MAGIC_CARDS)} 张魔法卡到手牌"}

    @staticmethod
    def _name(room: Room, player_id: str) -> str:
        player = room.players.get(player_id)
        return (player.name or player_id) if player else player_id


# --------------------------------------------------------------------- helpers


def sanitize_targets(targets: Any, card_name: str) -> tuple[dict[str, Any], str | None]:
    """Validate/normalise target_area, target_line and target_cells (legacy copy)."""

    if not isinstance(targets, dict):
        return {}, None

    area = targets.get("target_area")
    if isinstance(area, dict):
        for key in ("x1", "y1", "x2", "y2"):
            if key not in area:
                return targets, "目标区域参数缺失"
            try:
                value = int(area[key])
            except (TypeError, ValueError):
                return targets, "目标区域坐标非法"
            if not (0 <= value <= 5):
                return targets, "目标区域坐标超出棋盘范围"
            area[key] = value

    line = targets.get("target_line")
    if isinstance(line, dict):
        if line.get("type") not in ("row", "col"):
            return targets, "目标行列参数非法"
        try:
            index = int(line.get("index"))
        except (TypeError, ValueError):
            return targets, "目标行列坐标非法"
        if not (0 <= index <= 5):
            return targets, "目标行列坐标超出棋盘范围"
        line["index"] = index

    for key in ("target_cells", "selected_cells"):
        cells = targets.get(key)
        if isinstance(cells, list):
            for cell in cells:
                if not isinstance(cell, dict):
                    return targets, "目标格子格式错误"
                try:
                    x, y = int(cell["x"]), int(cell["y"])
                except (KeyError, TypeError, ValueError):
                    return targets, "目标格子坐标非法"
                if not (0 <= x <= 5 and 0 <= y <= 5):
                    return targets, "目标格子坐标超出棋盘范围"
                cell["x"], cell["y"] = x, y

    declared = AREA_TARGET_BOARDS.get(card_name)
    if declared is not None:
        board = targets.get("board")
        if declared in ("self", "opponent"):
            if board is not None and board != declared:
                return targets, "目标棋盘归属与卡牌不一致"
            targets["board"] = declared
        elif declared == "choice" and board not in ("self", "opponent"):
            return targets, "请选择目标棋盘（自己或对方）"
    return targets, None


__all__ = [
    "AREA_TARGET_BOARDS",
    "MagicService",
    "SELECTION_TARGET_KEYS",
    "sanitize_targets",
]
