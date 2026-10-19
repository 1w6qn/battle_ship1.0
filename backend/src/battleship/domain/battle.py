"""Battle phase rules: RPS, attack budget, phase ladder and turn switching.

Everything here is pure room mutation; the service layer owns identity checks,
wire frames and the turn watchdog. Attack **effects** (hits, sinking, shields)
belong to ticket #9 and are deliberately absent: this module only decides how
many shots a player gets and when a phase may advance.

Legacy reference: port map 13-domain-rules §2/§3 (server.py:4252-4290,
5755-5840, 5877-5932, 6003-6355, 10969-10987).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Sequence

from .room import (
    BOARD_SIZE,
    Player,
    Room,
    RoomPhase,
    RoomState,
    alive_ships,
)


def _value(value) -> str:
    """Accept both the enum and the legacy plain string stored by old flows."""

    return getattr(value, "value", value)


RPS_CHOICES: tuple[str, ...] = ("rock", "paper", "scissors")
RPS_BEATS: dict[str, str] = {
    "rock": "scissors",
    "paper": "rock",
    "scissors": "paper",
}

ENTER_BATTLE_ERROR = "无法进入战斗阶段"
ENTER_END_ERROR = "当前不是你的战斗阶段"
ATTACKS_LEFT_ERROR = "你还有剩余攻击次数，无法进入结束阶段"
END_TURN_ERROR = "无法结束当前回合"
CHAIN_BUSY_ERROR = "连锁结算中，请等待响应窗口结束后再结束回合"


@dataclass(frozen=True)
class RpsOutcome:
    status: Literal["win", "tie"]
    message: str
    winner: str | None = None
    loser: str | None = None
    choices: dict[str, str] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Legacy `RPSResult.to_dict` shape, key for key."""

        return {
            "status": self.status,
            "message": self.message,
            "winner": self.winner,
            "loser": self.loser,
            "choices": self.choices,
            "order": self.order,
        }


@dataclass(frozen=True)
class TurnEnd:
    """Outcome of a legal `end_turn`."""

    kind: Literal["next_player", "new_round", "skip_stages"]
    current_attacker: str
    round: int


def resolve_rps(choices: dict[str, str], players: Sequence[str]) -> RpsOutcome:
    """Pure RPS resolution. Ties (including invalid stored values) clear nothing
    here; the service resets `rps_choices`/`rps_processed` exactly like legacy."""

    first, second = players[0], players[1]
    c1, c2 = choices[first], choices[second]

    if c1 == c2:
        return RpsOutcome("tie", "平局，重新猜拳")
    if c1 not in RPS_BEATS or c2 not in RPS_BEATS:
        # Dirty data must never raise KeyError mid-game (legacy fallback).
        return RpsOutcome("tie", "出拳无效，重新猜拳")

    winner, loser = (first, second) if RPS_BEATS[c1] == c2 else (second, first)
    return RpsOutcome(
        status="win",
        message=f"{winner} 获胜",
        winner=winner,
        loser=loser,
        choices={first: c1, second: c2},
        order=[winner, loser],
    )


def frozen_ship_count(player: Player) -> int:
    """Only **living** frozen ships subtract an attack (port map §3.1).

    Dead ships stay in `player.ships`, while `remaining_ships` already excludes
    them; counting a sunk frozen ship again would subtract it twice.
    """

    return sum(1 for ship in alive_ships(player) if getattr(ship, "frozen", None))


def attacks_remaining_for(player: Player) -> int:
    """Attack budget = remaining (alive) ships minus living frozen ships."""

    return max(0, int(player.remaining_ships or 0) - frozen_ship_count(player))


#: Readable alias for callers that ask "how many attacks does this player get?".
attacks_for_player = attacks_remaining_for


def attackable_cells(player: Player) -> list[tuple[int, int]]:
    """Cells this player has not fired at yet (the legacy `_attackable_cells`)."""

    attacked = {(attack.x, attack.y) for attack in (player.attacks or [])}
    return [
        (x, y)
        for x in range(BOARD_SIZE)
        for y in range(BOARD_SIZE)
        if (x, y) not in attacked
    ]


def can_enter_end(room: Room, player_id: str) -> bool:
    player = room.players[player_id]
    return room.attacks_remaining <= 0 or not attackable_cells(player)


def enter_battle(room: Room, player_id: str) -> str | None:
    """preparation -> battle. Returns the legacy error text or None."""

    if room.current_attacker != player_id or _value(room.current_phase) != "preparation":
        return ENTER_BATTLE_ERROR
    room.current_phase = RoomPhase.BATTLE
    player = room.players[player_id]
    room.attacks_remaining = attacks_remaining_for(player)
    if player.effect_flags.double_attacks:
        # 火力全开 doubles the budget that already exists (not a recount).
        room.attacks_remaining = max(0, room.attacks_remaining) * 2
        player.effect_flags.double_attacks = False
    return None


def enter_end(room: Room, player_id: str) -> str | None:
    """battle -> end, only when no shot is left or no cell is attackable."""

    if room.current_attacker != player_id or _value(room.current_phase) != "battle":
        return ENTER_END_ERROR
    if room.attacks_remaining > 0 and attackable_cells(room.players[player_id]):
        return ATTACKS_LEFT_ERROR

    room.current_phase = RoomPhase.END
    flags = room.players[player_id].effect_flags
    if getattr(flags, "forced_kill", 0) > 0:
        flags.forced_kill -= 1
    flags.battle_spirit = False
    return None


def resolve_turn_end(room: Room, player_id: str) -> TurnEnd | None:
    """end -> opponent preparation, or a new big round back to RPS.

    Skip markers from magic cards are consumed here (they are phase-engine
    state, not card effects): `skip_opponent_turn` skips the opponent's whole
    turn **and flips the round**, `skip_next_turn` skips the next turn, and
    `skip_opponent_stages` skips the opponent inside this big round without
    flipping it.
    """

    if room.current_attacker != player_id or _value(room.current_phase) != "end":
        return None

    order = list(room.attack_order or room.players)
    if player_id not in order:
        return None
    current_index = order.index(player_id)
    next_index = (current_index + 1) % len(order)
    next_attacker = order[next_index]

    if room.skip_opponent_turn and room.skip_opponent_turn == next_attacker:
        room.skip_opponent_turn = None
        next_index = (next_index + 1) % len(order)
        next_attacker = order[next_index]
    if room.skip_next_turn and room.skip_next_turn == next_attacker:
        room.skip_next_turn = None
        next_index = (next_index + 1) % len(order)
        next_attacker = order[next_index]

    skip_stages = False
    if room.skip_opponent_stages and room.skip_opponent_stages == next_attacker:
        room.skip_opponent_stages = None
        skip_stages = True
        next_index = (next_index + 1) % len(order)
        next_attacker = order[next_index]

    if next_index == 0:
        if skip_stages:
            room.current_attacker = next_attacker
            room.current_phase = RoomPhase.PREPARATION
            room.attacks_remaining = 0
            room.state = RoomState.ATTACKING
            return TurnEnd("skip_stages", next_attacker, room.round)

        room.round += 1
        room.state = RoomState.ROCK_PAPER_SCISSORS
        room.rps_choices = {}
        room.rps_processed = False
        room.current_phase = RoomPhase.PREPARATION
        room.skip_opponent_turn = None
        room.skip_next_turn = None
        for seat in room.players.values():
            seat.magic_blocked = False
            seat.damage_dealt_this_turn = 0
        return TurnEnd("new_round", room.current_attacker, room.round)

    room.current_attacker = next_attacker
    room.current_phase = RoomPhase.PREPARATION
    room.players[next_attacker].damage_dealt_this_turn = 0
    room.attacks_remaining = attacks_remaining_for(room.players[next_attacker])
    return TurnEnd("next_player", next_attacker, room.round)