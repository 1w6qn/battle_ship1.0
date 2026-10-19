"""Effect lifetimes (ticket #11): the single flag/board cleanup vocabulary.

Two whitelists decide which per-player flags survive a turn/big-round boundary.
Every caller passes one of them to prune_effect_flags; there is no second
inline list anywhere (the legacy stack hit a silent bug exactly because both
the constant and an inline copy existed).
"""

from __future__ import annotations

from typing import Any

from ..room import Room

#: Effects whose card text is "this turn / this big round".
FLAGS_KEEP_ACROSS_TURN: frozenset[str] = frozenset({
    "no_draw",           # 无中生有: rest of the big round
    "prediction",        # 神机妙算: until the opponent's end phase resolves
    "forced_kill",       # 余音绕梁: this and the next attack phase
    "subsidy",           # 百亿补贴: rest of the big round
    "subsidy_bonus",     # accumulated bonus, same lifetime
    "vampire",           # 饮血: rest of the big round
    "treasure_hunter",   # 八方来财: rest of the big round
    "last_stand_win",    # 绝处逢生 "kill and win" lives until the match ends
})

#: At the end of a big round only "kill and win" survives.
FLAGS_KEEP_ACROSS_ROUND: frozenset[str] = frozenset({"last_stand_win"})

#: key -> human text. The legacy stack emitted three helper-only event names
#: (holy_heart_cleared / reinforcement_cleared / demon_contract_cleared) that are
#: not in the frozen 82-literal outbound table; ticket #11 keeps the contract
#: exact and tells the client through game_message + active_effects instead.
_MULTITURN_EFFECTS: tuple[tuple[str, str], ...] = (
    ("holy_heart", "无暇圣心效果已终止"),
    ("reinforcement_check", "极限增援效果已终止"),
    ("demon_contract", "恶魔契约效果已终止"),
)
_MULTITURN_PREFIXES: tuple[str, ...] = ("prediction", "prediction_initial_")


def prune_effect_flags(room: Room, keep: frozenset[str]) -> bool:
    """Drop every per-player flag outside keep; returns whether anything changed."""

    changed = False
    for player in room.players.values():
        flags = player.effect_flags
        before = dict(vars(flags))
        after = {key: value for key, value in before.items() if key in keep}
        if after != before:
            flags.__dict__ = after
            changed = True
    return changed


def clear_board_effects(room: Room, player_ids: list[str], why: str = "") -> list[tuple[str, dict]]:
    """Terminate board-scoped effects on the boards that were just replaced.

    Returns the wire frames the caller must emit (this module never emits).
    """

    ids = [str(pid) for pid in player_ids or []]
    if not ids:
        return []
    effects = room.game_effects if isinstance(room.game_effects, dict) else {}
    frames: list[tuple[str, dict]] = []

    # Excluded (神威!) ships belong to the replaced board; restore-at-expiry
    # would otherwise append ghost ships (6 -> 8 ships in the legacy bug).
    entries = effects.get("excluded_ships")
    if entries:
        if len(ids) >= len(room.players):
            effects.pop("excluded_ships", None)
        else:
            kept = [e for e in entries if e.get("player") not in ids]
            if kept:
                effects["excluded_ships"] = kept
            else:
                effects.pop("excluded_ships", None)

    holes = effects.get("shenwei_holes") or []
    for pid in ids:
        mine = [h for h in holes if isinstance(h, dict) and str(h.get("player")) == pid]
        if not mine:
            continue
        for hole in mine:
            holes.remove(hole)
        frames.append(("shenwei_hole_restored", {"player": pid}))
    if not holes:
        effects.pop("shenwei_holes", None)

    area = effects.get("frozen_area")
    if isinstance(area, dict) and str(area.get("owner")) in ids:
        effects.pop("frozen_area", None)
        frames.append(("frozen_area", {"cleared": True}))
    return frames


def clear_multiturn_effects(room: Room, why: str = "") -> list[tuple[str, dict]]:
    """Terminate cross-round countdown effects when a board is replaced."""

    effects = room.game_effects if isinstance(room.game_effects, dict) else {}
    frames: list[tuple[str, dict]] = []
    for key, text in _MULTITURN_EFFECTS:
        if key not in effects:
            continue
        effects.pop(key, None)
        frames.append(("game_message", {"message": text, "type": "info", "reason": why}))
        if key == "demon_contract":
            from .interaction import clear_ship_picks_by_reason

            clear_ship_picks_by_reason(room, "demon_contract")
    for key in list(effects):
        if any(str(key).startswith(prefix) for prefix in _MULTITURN_PREFIXES):
            effects.pop(key, None)
    return frames


__all__ = [
    "FLAGS_KEEP_ACROSS_ROUND",
    "FLAGS_KEEP_ACROSS_TURN",
    "clear_board_effects",
    "clear_multiturn_effects",
    "prune_effect_flags",
]