"""Socket.IO ASGI 适配层。

新的 socket 事件适配层按领域迁移到 `handlers/*`。当前负责：
连接计数、会话身份落盘、续局提示/重连 token、房间与重连事件接线、
未登记事件的明确拒绝，以及 `/metrics` 需要的事件计数。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import socketio

from ..contracts.events_in import is_debug_event
from ..http.session import session_from_cookie_header, session_user_id, session_username
from ..infra.logging import get_logger, log_context
from ..services.gameplay import GameplayService
from ..services.rooms import Connection, RoomService
from .emitter import SocketIoPublisher
from .handlers.battle import register_battle_handlers
from .handlers.debug import DEBUG_EVENT_DISABLED_MESSAGE, register_debug_handlers
from .handlers.reconnect import register_reconnect_handlers
from .handlers.room import register_room_handlers

if TYPE_CHECKING:
    from ..config import Settings
    from ..infra.metrics import MetricsRegistry

logger = get_logger("realtime")


def create_socket_server(
    settings: "Settings",
    metrics: "MetricsRegistry",
    rooms: RoomService | None = None,
    gameplay: GameplayService | None = None,
) -> socketio.AsyncServer:
    rooms = rooms or RoomService()
    gameplay = gameplay or GameplayService(
        rooms, turn_timeout_seconds=settings.turn_timeout_seconds
    )
    sio = socketio.AsyncServer(
        async_mode="asgi",
        cors_allowed_origins=settings.cors_origins or [],
        logger=False,
        engineio_logger=False,
    )

    @sio.event
    async def connect(sid: str, environ: dict, auth=None) -> bool:
        metrics.connection_opened()
        # Carry the signed-cookie identity onto the socket. ticket #7 reads this
        # instead of trusting a client-supplied user_id/player_id claim.
        cookie_header = (environ or {}).get("HTTP_COOKIE") or (environ or {}).get("COOKIE")
        session = session_from_cookie_header(
            settings.secret_key.get_secret_value(), cookie_header
        )
        await sio.save_session(
            sid,
            {
                "user_id": session_user_id(session),
                "username": session_username(session),
            },
        )
        # A returning account may still sit in an unfinished room: push
        # resume_game + a fresh reconnect token so the client can rejoin.
        await rooms.notify_resume(
            Connection(
                sid=sid,
                user_id=session_user_id(session),
                username=session_username(session),
            )
        )
        with log_context(event="connect"):
            logger.info(
                "socket connected",
                extra={"socket_id": sid, "authenticated": bool(session_user_id(session))},
            )
        return True

    @sio.event
    async def disconnect(sid: str, reason=None) -> None:
        metrics.connection_closed()
        # Start the 30s grace in a background task. This handler must never emit
        # or wait on the grace window (the legacy eventlet hub deadlock).
        await rooms.handle_disconnect(sid)
        with log_context(event="disconnect"):
            logger.info("socket disconnected", extra={"socket_id": sid, "reason": str(reason)})

    @sio.on("debug_status")
    async def debug_status(sid: str, data=None) -> dict:
        return {
            "status": "success",
            "enabled": bool(settings.enable_test_events),
            "whitelist_configured": bool(settings.debug_admin_user_ids),
        }

    # namespace 级 catch-all：python-socketio 传参顺序是 (event, sid, data)。
    @sio.on("*")
    async def unknown_event(event: str, sid: str, *args) -> dict:
        started = time.perf_counter()
        name = str(event)
        if is_debug_event(name):
            # 开关关闭时调试 handler 没有注册，由这里给出与旧栈一致的拒绝。
            message = DEBUG_EVENT_DISABLED_MESSAGE
        else:
            message = f"未登记的事件: {name}"
        with log_context(event=name):
            logger.warning("unhandled socket event", extra={"debug_event": is_debug_event(name)})
        metrics.record_socket_event(
            name, (time.perf_counter() - started) * 1000, error=True
        )
        return {"status": "error", "message": message}

    publisher = SocketIoPublisher(sio)
    rooms.bind(publisher)
    gameplay.bind(publisher)
    register_room_handlers(sio, rooms)
    register_battle_handlers(sio, gameplay)
    register_reconnect_handlers(sio, rooms)
    register_debug_handlers(sio, settings, metrics)
    return sio
