"""Chain stack item and result shapes.

Ticket #12 owns the full chain engine (10s response window, negation, display
delay). Ticket #10 only needs the frozen item/result *shapes* so a card can be
queued and resolved without inventing a second representation. The dataclasses
here serialize to the same keys the legacy `ChainItem.__dict__` /
`ChainResult.__dict__` produced on the wire.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .cards import MagicCard


@dataclass
class ChainItem:
    player_id: str
    card: MagicCard
    targets: Any = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    negated: bool = False
    negated_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "card": self.card.to_payload(),
            "targets": self.targets,
            "timestamp": self.timestamp,
            "negated": self.negated,
            "negated_by": self.negated_by,
        }


@dataclass
class ChainResult:
    card: MagicCard
    caster: str
    success: bool = True
    message: str = ""
    negate_target: bool = False
    negated_skip: bool = False
    negated_by: str | None = None
    affected_positions: list[Any] = field(default_factory=list)
    game_over: bool = False

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "card": self.card.to_payload(),
            "caster": self.caster,
            "success": self.success,
            "message": self.message,
        }
        if self.negate_target:
            payload["negate_target"] = True
        if self.negated_skip:
            payload["negated_skip"] = True
            payload["negated_by"] = self.negated_by
        if self.affected_positions:
            payload["affected_positions"] = [
                _position_payload(pos) for pos in self.affected_positions
            ]
        if self.game_over:
            payload["game_over"] = True
        return payload


def _position_payload(position: Any) -> Any:
    if isinstance(position, dict):
        return position
    if all(hasattr(position, key) for key in ("x", "y")):
        return {
            "x": int(position.x),
            "y": int(position.y),
            "hit": bool(getattr(position, "hit", False)),
            "ship_sunk": bool(getattr(position, "ship_sunk", False)),
        }
    return position


__all__ = ["ChainItem", "ChainResult"]
