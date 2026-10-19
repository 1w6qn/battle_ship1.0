"""Chain negation cards: 失灵！ / 平等条约 / 加百列之光 (ticket #12).

These three are registered here, not in batch A, because their behaviour is the
chain engine's other half: they mark the item directly below them on the stack
as negated, and they may also tear down an already-placed field card when the
stack is empty. The target/immunity rule `negation_target` is shared with the
resolution engine (one implementation, DECISIONS #1).

Legacy reference: server.py:13318-13341 (`_tear_down_field_magic`),
14431-14467 (平等条约), 14846-14882 (加百列之光), 15036-15081 (失灵！).
"""

from __future__ import annotations

from typing import Any

from ...battle import frozen_ship_count
from ..cards import MagicCard
from ..chain import equal_treaty_verdict, negation_target
from ..registry import register
from .base import EffectContext, EffectResult


# --------------------------------------------------------------- field magic


def _clear_field_effects(room: Any, field_name: str) -> bool:
    """Clear room-level markers left by a torn-down field card.

    Returns True when the attack budget was recomputed and the caller must
    emit `attacks_updated`.
    """

    had_papal = bool(room.game_effects.get("papal_edict"))
    room.game_effects.pop("demon_contract", None)
    room.game_effects.pop("papal_edict", None)
    # A pending "sacrifice" ship-pick belongs to the demon contract; leaving it
    # queued would make a later click resolve as a sacrifice (legacy fix).
    room.pending_ship_picks = [
        pick for pick in (room.pending_ship_picks or [])
        if not (isinstance(pick, dict) and pick.get("reason") == "demon_contract")
    ]
    if getattr(room.state, "value", room.state) != "attacking":
        return False
    player_id = room.current_attacker
    if not player_id or player_id not in room.players:
        return False
    if not had_papal and field_name not in ("伊甸园", "教皇旨意"):
        return False
    player = room.players[player_id]
    bonus = int(getattr(player.effect_flags, "subsidy_bonus", 0) or 0)
    base = max(0, player.remaining_ships - frozen_ship_count(player))
    room.attacks_remaining = max(0, base + bonus)
    return True


def _tear_down_field_magic(room: Any) -> tuple[MagicCard | None, bool]:
    """Remove the active field card; returns (torn card, attacks changed)."""

    field = room.field_magic
    if not field:
        return None, False
    room.magic_discard.append(field)
    changed = _clear_field_effects(room, getattr(field, "name", ""))
    room.field_magic = None
    room.field_magic_owner = None
    return field, changed


async def _emit_field_teardown(ctx: EffectContext, torn: MagicCard,
                               attacks_changed: bool) -> None:
    await ctx.emit(
        "field_magic_updated",
        {"player_id": ctx.caster_id, "card": None},
        room=ctx.room.id,
    )
    if attacks_changed:
        await ctx.emit(
            "attacks_updated",
            {
                "current_attacker": ctx.room.current_attacker,
                "attacks_remaining": ctx.room.attacks_remaining,
            },
            room=ctx.room.id,
        )


# --------------------------------------------------------------- the cards


@register("失灵！")
async def shiling(ctx: EffectContext) -> EffectResult:
    # In a chain: negate the item directly below (self-negation included).
    if ctx.room.chain:
        target, why = negation_target(ctx.room, "失灵！")
        if target is None:
            return EffectResult(False, why or "没有可无效化的魔法卡")
        return EffectResult(True, f"将无效化{target.card.name}", negate_target=True)

    # No chain: tear down an already-placed field card (either owner's).
    if ctx.room.field_magic:
        torn, attacks_changed = _tear_down_field_magic(ctx.room)
        await _emit_field_teardown(ctx, torn, attacks_changed)
        return EffectResult(True, f"成功无效化场地魔法「{getattr(torn, 'name', '')}」")

    # Otherwise fall back to the last card the opponent played this round.
    history = ctx.room.magic_history
    if history and history[-1].get("caster") != ctx.caster_id:
        last = history[-1]
        last_card = last.get("card")
        last_name = getattr(last_card, "name", None)
        if last_name in ("看破！", "加百列之光"):
            return EffectResult(False, "该魔法免疫失灵！")
        if last.get("round", ctx.room.round) != ctx.room.round:
            return EffectResult(False, "对方上一张魔法卡不是本回合使用的，失灵！无法无效化")
        history.pop()
        return EffectResult(True, f"无效化了{last_name}（若其效果已结算则不会回滚）")
    return EffectResult(False, "没有可无效化的魔法卡")


@register("加百列之光")
async def gabriel(ctx: EffectContext) -> EffectResult:
    """Negate the stack item below, or tear a field card when the stack is empty.

    No owner check: a later card in the same chain may overturn an earlier one,
    including one its caster played (legacy multi-level negation fix).
    """

    negated_count = 0
    chain_negated = False
    if ctx.room.chain:
        negated_count += 1
        chain_negated = True

    if not chain_negated and ctx.room.field_magic is None and ctx.room.magic_history:
        last = ctx.room.magic_history[-1]
        if last.get("caster") != ctx.caster_id:
            ctx.room.magic_history.pop()
            negated_count += 1
            chain_negated = True

    torn = None
    attacks_changed = False
    if not chain_negated and ctx.room.field_magic:
        torn, attacks_changed = _tear_down_field_magic(ctx.room)
        negated_count += 1

    if negated_count == 0:
        return EffectResult(False, "没有可无效化的魔法卡或场地魔法")
    if torn is not None:
        await _emit_field_teardown(ctx, torn, attacks_changed)
        return EffectResult(True, f"成功无效化场地魔法「{getattr(torn, 'name', '')}」")
    return EffectResult(True, "成功无效化连锁中的魔法卡", negate_target=chain_negated)


@register("平等条约")
async def equal_treaty(ctx: EffectContext) -> EffectResult:
    target, why = negation_target(ctx.room, "平等条约")
    if target is None:
        return EffectResult(False, why or "没有可无效化的魔法卡")
    # 看破！ can suppress this card inside the same chain, after it was played.
    if getattr(ctx.caster, "magic_blocked", False):
        return EffectResult(
            False, "你已被看破！压制，本回合魔法卡无效，平等条约无法发动"
        )
    would_change, reason = equal_treaty_verdict(ctx.room, target)
    if not would_change:
        return EffectResult(False, f"没有可无效化的船数改变效果（{reason}）")
    return EffectResult(True, f"将无效化{target.card.name}", negate_target=True)


__all__ = ["gabriel", "shiling", "equal_treaty"]
