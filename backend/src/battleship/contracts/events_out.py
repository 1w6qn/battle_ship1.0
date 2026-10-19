"""Socket.IO 出站事件清单、事件信封与 ack 形状。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# 旧栈服务端 -> 客户端事件（从 server.py 的 emit('...') 字面量冻结而来）。
OUTBOUND_EVENTS: tuple[str, ...] = (
    "achievements_unlocked",
    "active_effects",
    "attack_result",
    "attacks_updated",
    "board_attacks_updated",
    "chain_request",
    "chain_resolved",
    "chat_message",
    "dice_discard_complete",
    "dice_discard_request",
    "dice_rolled",
    "error",
    "field_magic_updated",
    "frozen_area",
    "game_canceled",
    "game_log",
    "game_message",
    "game_over",
    "game_state",
    "hand_updated",
    "holy_heart_activated",
    "holy_heart_interrupted",
    "holy_heart_turn_updated",
    "lanyu_recalled",
    "last_stand_cells",
    "lingqi_complete",
    "lingqi_waiting",
    "lobby_chat",
    "lobby_chat_history",
    "lobby_hello",
    "lobby_state",
    "magic_chain_updated",
    "match_canceled",
    "match_queued",
    "message",
    "opponent_disconnected",
    "opponent_reconnected",
    "phase_updated",
    "placement_done",
    "placement_request",
    "player_ships_updated",
    "priority_request",
    "priority_setting_updated",
    "priority_waiting",
    "priority_waiting_end",
    "quick_chat",
    "rank_changed",
    "reconnect_token",
    "reconnect_warning",
    "reinforcement_activated",
    "reinforcement_turn_updated",
    "reset_gameboard",
    "resume_game",
    "revealed_positions",
    "room_sync",
    "rps_result",
    "sacrifice_cancelled",
    "sacrifice_request",
    "shenji_waiting",
    "shenji_waiting_end",
    "shenwei_hole",
    "shenwei_hole_restored",
    "shield_absorbed",
    "shields_added",
    "ship_sacrificed",
    "ships_updated",
    "spectate_board",
    "spectate_chat",
    "spectate_count_changed",
    "spectate_ended",
    "spectate_roster",
    "spectate_sync",
    "spectate_you",
    "taoyuan_complete",
    "taoyuan_waiting",
    "trap_expired",
    "trap_set",
    "trap_triggered",
    "turn_change",
    "turn_skipped",
    "wangyang_complete",
    "xp_gained",
)


class OutboundEventEnvelope(BaseModel):
    """出站信封。to 与 room 都是 Socket.IO 的目标语义，二者可只填一个。"""

    event: str = Field(min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)
    namespace: str = "/"
    to: str | None = None
    room: str | None = None
    skip_sid: str | None = None


class AckResponse(BaseModel):
    """Socket.IO ack 的通用形状；旧前端按 status 判断成功/失败。"""

    status: Literal["success", "error"] = "success"
    message: str | None = None
    data: dict[str, Any] | None = None