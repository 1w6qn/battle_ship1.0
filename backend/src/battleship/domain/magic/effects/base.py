"""Effect contract shared by every magic-card branch.

Effects are pure room mutation plus injected async callbacks. They never import
a framework, a database or a socket library -- that is what lets the service
layer own wire frames, logging and settlement while the card behaviour stays in
one registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from ..cards import MagicCard
from ...room import Player, PlayerShip, Room


@dataclass
class EffectResult:
    success: bool = True
    message: str = ""
    temp_data_id: str | None = None
    game_over: bool = False
    affected_positions: list[Any] = field(default_factory=list)


Emit = Callable[..., Awaitable[None]]
AsyncInt = Callable[[int], Awaitable[Any]]
AsyncNone = Callable[[], Awaitable[None]]
AsyncPlayer = Callable[[str], Awaitable[None]]
AsyncDraw = Callable[[str], Awaitable[Any]]
AsyncSink = Callable[[str, PlayerShip], Awaitable[None]]
AsyncFinish = Callable[[str, str, str], Awaitable[None]]


@dataclass
class EffectContext:
    room: Room
    caster_id: str
    opponent_id: str
    card: MagicCard
    targets: dict[str, Any]
    emit: Emit
    draw: AsyncDraw
    log: Callable[..., Awaitable[None]]
    finish: AsyncFinish
    sync_ships: AsyncNone
    sync_player_ships: AsyncPlayer
    sync_hand: AsyncPlayer
    sync_active_effects: AsyncNone
    on_ship_sunk: AsyncSink
    notify_treasure: AsyncInt
    grant_attacks: AsyncInt
    maybe_wuxian: Callable[[], Awaitable[bool]]

    @property
    def caster(self) -> Player:
        return self.room.players[self.caster_id]

    @property
    def opponent(self) -> Player:
        return self.room.players[self.opponent_id]

    @property
    def phase(self) -> str:
        return getattr(self.room.current_phase, "value", self.room.current_phase)

    def area(self) -> dict[str, int] | None:
        area = (self.targets or {}).get("target_area")
        return area if isinstance(area, dict) else None

    def line(self) -> dict[str, Any] | None:
        line = (self.targets or {}).get("target_line")
        return line if isinstance(line, dict) else None

    def cells(self, key: str = "target_cells") -> list[dict[str, int]] | None:
        cells = (self.targets or {}).get(key)
        return cells if isinstance(cells, list) else None

    def board_side(self) -> str | None:
        board = (self.targets or {}).get("board")
        return board if board in ("self", "opponent") else None

    def name(self, player_id: str) -> str:
        player = self.room.players.get(player_id)
        return (player.name or player_id) if player else player_id


__all__ = ["EffectContext", "EffectResult"]
