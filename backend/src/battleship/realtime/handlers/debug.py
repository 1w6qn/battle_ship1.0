"""调试事件门禁。

旧栈 14 个 `test_*` 事件默认拒绝；只有显式 `ENABLE_TEST_EVENTS=1` 才放行。
新栈保留同样的开关，并且额外支持 `DEBUG_ADMIN_USER_IDS` 白名单（开关打开时
仍只允许名单里的登录账号）。

实现策略：**开关关闭时一个调试 handler 都不注册**；未登记事件由 realtime 的
catch-all 返回明确的 ack 错误（见 `realtime/server.py`），而不是 Socket.IO 的
未知事件静默超时。开关打开后，14 个 handler 才注册，并且仍要过白名单；
真正的实现（`DEBUG_IMPLEMENTATIONS`）按事件增量登记。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from ...contracts.events_in import DEBUG_EVENTS

if TYPE_CHECKING:
    import socketio

    from ...config import Settings
    from ...infra.metrics import MetricsRegistry

DEBUG_EVENT_DISABLED_MESSAGE = "调试事件未启用"
DEBUG_EVENT_FORBIDDEN_MESSAGE = "调试事件未对你的账号开放"

# 事件名 -> 实现。后续票登记真实实现；未登记时明确返回"尚未实现"，
# 绝不假装成功（旧栈 `test_win_game` 的"成功但毫无反应"就是这种坑）。
DEBUG_IMPLEMENTATIONS: dict[str, Callable[..., Awaitable[Any]]] = {}


async def debug_actor_allowed(
    sio: "socketio.AsyncServer",
    sid: str,
    settings: "Settings",
) -> bool:
    whitelist = settings.debug_admin_user_ids
    if not whitelist:
        return True  # 未配白名单：与旧行为一致（仅本地/自建环境应打开开关）
    try:
        session = await sio.get_session(sid)
    except Exception:
        return False
    user_id = session.get("user_id") if isinstance(session, dict) else None
    return user_id is not None and str(user_id) in whitelist


def _make_handler(
    event: str,
    sio: "socketio.AsyncServer",
    settings: "Settings",
    metrics: "MetricsRegistry",
):
    async def handler(sid: str, data: dict[str, Any] | None = None, *args: Any):
        started = time.perf_counter()
        error = False
        try:
            if not settings.enable_test_events:
                error = True
                return {"status": "error", "message": DEBUG_EVENT_DISABLED_MESSAGE}
            if not await debug_actor_allowed(sio, sid, settings):
                error = True
                return {"status": "error", "message": DEBUG_EVENT_FORBIDDEN_MESSAGE}

            implementation = DEBUG_IMPLEMENTATIONS.get(event)
            if implementation is None:
                error = True
                return {
                    "status": "error",
                    "message": f"调试事件 {event} 尚未实现",
                }
            result = await implementation(sid, data or {}, sio=sio, settings=settings)
            return result
        finally:
            metrics.record_socket_event(
                event, (time.perf_counter() - started) * 1000, error=error
            )

    return handler


def register_debug_implementations(battle: Any, magic: Any = None) -> None:
    """Register ticket #9's debug events (only usable behind the gate)."""

    async def test_win_game(sid: str, data: dict[str, Any], *,
                            sio: "socketio.AsyncServer", settings: "Settings") -> dict:
        return await battle.debug_win(data.get("room_id"), data.get("player_id"))

    async def test_lose_game(sid: str, data: dict[str, Any], *,
                             sio: "socketio.AsyncServer", settings: "Settings") -> dict:
        return await battle.debug_lose(data.get("room_id"), data.get("player_id"))

    DEBUG_IMPLEMENTATIONS["test_win_game"] = test_win_game
    DEBUG_IMPLEMENTATIONS["test_lose_game"] = test_lose_game
    DEBUG_IMPLEMENTATIONS["test_win_game"] = test_win_game
    DEBUG_IMPLEMENTATIONS["test_lose_game"] = test_lose_game

    if magic is not None:
        async def test_add_specific_magic_card(
            sid: str, data: dict[str, Any], *,
            sio: "socketio.AsyncServer", settings: "Settings",
        ) -> dict:
            return await magic.debug_add_card(
                data.get("room_id"), data.get("player_id"), data.get("card_name")
            )

        async def test_add_all_magic_cards(
            sid: str, data: dict[str, Any], *,
            sio: "socketio.AsyncServer", settings: "Settings",
        ) -> dict:
            return await magic.debug_add_all_cards(
                data.get("room_id"), data.get("player_id")
            )

        DEBUG_IMPLEMENTATIONS["test_add_specific_magic_card"] = test_add_specific_magic_card
        DEBUG_IMPLEMENTATIONS["test_add_all_magic_cards"] = test_add_all_magic_cards


def register_debug_handlers(
    sio: "socketio.AsyncServer",
    settings: "Settings",
    metrics: "MetricsRegistry",
) -> None:
    # 默认拒绝：开关没开就完全不注册，避免公网玩家通过 test_* 事件作弊。
    if not settings.enable_test_events:
        return
    for event in DEBUG_EVENTS:
        sio.on(event, _make_handler(event, sio, settings, metrics))
