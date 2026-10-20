"""Stable, machine-readable socket error codes (ticket #43).

The frontend maps a code to a player-facing sentence and only falls back to the
server `message` when a code is absent (UI redesign spec section 9). Codes are
additive: every existing payload keeps its `message`, and a missing code is a
legitimate legacy shape, not an error.

One catalog only. Services import a code from here instead of spelling a string
twice, so the wire vocabulary cannot drift between the error frame (`error`)
and the operation ack.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

#: Fallback for an error ack that carries no more specific code yet.
OPERATION_FAILED = "operation_failed"

# Seats / rooms
INVALID_SEAT = "invalid_seat"
INVALID_ROOM = "invalid_room"
ROOM_NOT_FOUND = "room_not_found"
ROOM_FULL = "room_full"
IDENTITY_FAILED = "identity_failed"
GAME_OVER = "game_over"
NOT_IN_ROOM = "not_in_room"

# Placement / RPS / turn
PLACEMENT_INVALID = "placement_invalid"
NO_PENDING_PLACEMENT = "no_pending_placement"
INVALID_RPS_CHOICE = "invalid_rps_choice"
OPPONENT_DISCONNECTED = "opponent_disconnected"
CHAIN_BUSY = "chain_busy"
INVALID_TURN = "invalid_turn"

# Lobby / matchmaking / spectate
NOT_IN_LOBBY = "not_in_lobby"
CHAT_TOO_FAST = "chat_too_fast"
EMPTY_MESSAGE = "empty_message"
ROOM_CREATE_FAILED = "room_create_failed"
ALREADY_QUEUED = "already_queued"
SPECTATE_DENIED = "spectate_denied"

# Protocol
UNKNOWN_EVENT = "unknown_event"
DEBUG_DISABLED = "debug_disabled"
DEBUG_FORBIDDEN = "debug_forbidden"

#: Every stable code the server may put on the wire (order is not a contract).
SOCKET_ERROR_CODES: tuple[str, ...] = (
    OPERATION_FAILED,
    INVALID_SEAT,
    INVALID_ROOM,
    ROOM_NOT_FOUND,
    ROOM_FULL,
    IDENTITY_FAILED,
    GAME_OVER,
    NOT_IN_ROOM,
    PLACEMENT_INVALID,
    NO_PENDING_PLACEMENT,
    INVALID_RPS_CHOICE,
    OPPONENT_DISCONNECTED,
    CHAIN_BUSY,
    INVALID_TURN,
    NOT_IN_LOBBY,
    CHAT_TOO_FAST,
    EMPTY_MESSAGE,
    ROOM_CREATE_FAILED,
    ALREADY_QUEUED,
    SPECTATE_DENIED,
    UNKNOWN_EVENT,
    DEBUG_DISABLED,
    DEBUG_FORBIDDEN,
)


class SocketError(BaseModel):
    """One error on the socket: the code is stable, the message is for humans."""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


def error_detail(code: str, message: str) -> dict[str, str]:
    """The single shape used by both an `error` frame and an operation ack."""

    return {"code": code, "message": message}


__all__ = [
    "ALREADY_QUEUED",
    "CHAIN_BUSY",
    "CHAT_TOO_FAST",
    "DEBUG_DISABLED",
    "DEBUG_FORBIDDEN",
    "EMPTY_MESSAGE",
    "GAME_OVER",
    "IDENTITY_FAILED",
    "INVALID_ROOM",
    "INVALID_RPS_CHOICE",
    "INVALID_SEAT",
    "INVALID_TURN",
    "NOT_IN_LOBBY",
    "NOT_IN_ROOM",
    "NO_PENDING_PLACEMENT",
    "OPERATION_FAILED",
    "OPPONENT_DISCONNECTED",
    "PLACEMENT_INVALID",
    "ROOM_CREATE_FAILED",
    "ROOM_FULL",
    "ROOM_NOT_FOUND",
    "SOCKET_ERROR_CODES",
    "SPECTATE_DENIED",
    "SocketError",
    "UNKNOWN_EVENT",
    "error_detail",
]
