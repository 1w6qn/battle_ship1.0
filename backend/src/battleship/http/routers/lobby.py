"""Lobby HTTP surface needed by ticket #14.

Only the routes this ticket's behaviour depends on: the online counter. The
remaining 48 legacy routes stay with ticket #19. The counter reads the single
presence table the lobby broadcasts from (CLAUDE #17), so the home panel and
lobby_state can never disagree.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["lobby"], include_in_schema=False)


@router.get("/api/online_count")
def online_count(request: Request):
    presence = request.app.state.presence
    return JSONResponse({"online_count": presence.online_count()})
