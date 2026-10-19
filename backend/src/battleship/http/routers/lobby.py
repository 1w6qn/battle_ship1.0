"""Lobby HTTP surface needed by ticket #14.

Only the routes this ticket's behaviour depends on: the online counter. The
remaining 48 legacy routes stay with ticket #19. The counter reads the single
presence table the lobby broadcasts from (CLAUDE #17), so the home panel and
lobby_state can never disagree.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ...domain.lobby.rules import visible_rooms

router = APIRouter(tags=["lobby"], include_in_schema=False)


@router.get("/api/online_count")
def online_count(request: Request):
    presence = request.app.state.presence
    return JSONResponse({"online_count": presence.online_count()})


@router.get("/api/home_stats")
def home_stats(request: Request):
    """Read-only home panel aggregate: online / queue split / joinable rooms.

    Same sources as lobby_state, and deliberately read-only: subscribing to the
    lobby just to show three numbers would add every home-screen visitor to the
    lobby member list. A failed read degrades to nulls (HTTP 200) because a
    decorative panel must not blank the home screen.
    """
    try:
        presence = request.app.state.presence
        rooms = request.app.state.rooms
        queue = list(rooms.match_queue)
        ranked = sum(1 for entry in queue if entry.get("mode") == "ranked")
        online = presence.snapshot()
        joinable = visible_rooms(rooms.get_all_rooms().values(), set(online))
        return JSONResponse({
            "online_count": presence.online_count(),
            "queue": {"casual": len(queue) - ranked, "ranked": ranked},
            "lobby_rooms": len(joinable),
        })
    except Exception:  # noqa: BLE001 - decorative panel must not 500
        return JSONResponse({"online_count": None, "queue": None, "lobby_rooms": None})
