"""魔法卡 hook 事件目录（ticket #36 首版）。

事件名是 domain 内部常量，不是 Socket.IO 协议：发射它们不会产生任何出站帧，
也不进回放/观战日志。`effects.emit(room, event, payload)` 的 event 一律取这里
的常量；新增时点先登记再使用（事件目录是唯一真相）。

命名沿用现有领域词汇：出牌 / 连锁 / 回合 / 阶段 / 攻击 / 伤害 / 击沉 / 摸牌 /
场地 / 终局。
"""

from __future__ import annotations

from typing import Final

#: 出牌宣告之后、扣牌与入连锁之前；filter 可改写目标或否决。
CAST_BEFORE: Final[str] = "cast_before"
#: 支付完成：牌已离开手牌并进入连锁；此后失败只能按连锁规则退牌。
CAST_PAID: Final[str] = "cast_paid"
#: 连锁上一张牌结算完成（无效化与早退都已落定）。
CHAIN_RESOLVED: Final[str] = "chain_resolved"
#: 小回合开始，行动者已确定、攻击次数已重置。
TURN_START: Final[str] = "turn_start"
#: 小回合结束、行动者换人之前；turn 边界租约在这里过期。
TURN_END: Final[str] = "turn_end"
#: 大回合开始（重新猜拳/攻击顺序重排之后）。
ROUND_START: Final[str] = "round_start"
#: 大回合结束；round 边界租约在这里过期。
ROUND_END: Final[str] = "round_end"
#: 进入新阶段（准备 / 战斗 / 结束）。
PHASE_ENTER: Final[str] = "phase_enter"
#: 一次攻击命中；filter 可改写伤害、击沉或直接否决。
ATTACK_HIT: Final[str] = "attack_hit"
#: 伤害真正落到棋盘之后（护盾/免疫已经处理完）。
DAMAGE_APPLIED: Final[str] = "damage_applied"
#: 一艘船被击沉（炮击路径）。
SHIP_SUNK: Final[str] = "ship_sunk"
#: 一艘船被效果直接摧毁（非炮击路径）。
SHIP_DESTROYED: Final[str] = "ship_destroyed"
#: 某玩家的剩余船数变化（增援、复活、摧毁都算）。
SHIP_COUNT_CHANGED: Final[str] = "ship_count_changed"
#: 摸牌入手（尚未公开给对手）。
CARD_DRAWN: Final[str] = "card_drawn"
#: 一张牌进入弃牌堆。
CARD_DISCARDED: Final[str] = "card_discarded"
#: 场地魔法上场（顶替旧场地之后）。
FIELD_ENTERED: Final[str] = "field_entered"
#: 场地魔法离场（拆除或被顶替之前）。
FIELD_LEFT: Final[str] = "field_left"
#: 终局判定完成、winner 已写入。
GAME_OVER: Final[str] = "game_over"

#: 目录的权威清单；顺序即文档顺序，不含语义。
HOOK_EVENTS: Final[tuple[str, ...]] = (
    CAST_BEFORE,
    CAST_PAID,
    CHAIN_RESOLVED,
    TURN_START,
    TURN_END,
    ROUND_START,
    ROUND_END,
    PHASE_ENTER,
    ATTACK_HIT,
    DAMAGE_APPLIED,
    SHIP_SUNK,
    SHIP_DESTROYED,
    SHIP_COUNT_CHANGED,
    CARD_DRAWN,
    CARD_DISCARDED,
    FIELD_ENTERED,
    FIELD_LEFT,
    GAME_OVER,
)

__all__ = [
    "CAST_BEFORE",
    "CAST_PAID",
    "CHAIN_RESOLVED",
    "TURN_START",
    "TURN_END",
    "ROUND_START",
    "ROUND_END",
    "PHASE_ENTER",
    "ATTACK_HIT",
    "DAMAGE_APPLIED",
    "SHIP_SUNK",
    "SHIP_DESTROYED",
    "SHIP_COUNT_CHANGED",
    "CARD_DRAWN",
    "CARD_DISCARDED",
    "FIELD_ENTERED",
    "FIELD_LEFT",
    "GAME_OVER",
    "HOOK_EVENTS",
]
