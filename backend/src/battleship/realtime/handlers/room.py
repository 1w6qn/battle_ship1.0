"""Socket adapters for room creation / seating (ticket #7).

Only protocol translation: pull the trusted connection identity, delegate to the
service, return its ack. No business rule is allowed to grow here.
"""

from __future__ import annotations

from typing import Any

import socketio

from ..identity import connection_from_sio
from ...services.rooms import RoomService


def register_room_handlers(sio: socketio.AsyncServer, rooms: RoomService) -> None:
    @sio.on("create_room")
    async def create_room(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await rooms.create_room(connection, data)

    @sio.on("join_room")
    async def join_room(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await rooms.join_room(connection, data)

    @sio.on("create_ai_room")
    async def create_ai_room(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await rooms.create_ai_room(connection, data)
