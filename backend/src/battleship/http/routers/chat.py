"""Public read-only game data needed by ticket #14: the quick-chat catalog.

The text lives only on the server (the socket event accepts an id), so the
client must fetch it. Public like the legacy route: guests can play too and the
catalog carries no user data.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ...domain.social import quick_chat

router = APIRouter(tags=["chat"], include_in_schema=False)


@router.get("/api/quick_chat")
def quick_chat_catalog():
    return JSONResponse(
        {
            "success": True,
            "groups": list(quick_chat.GROUPS),
            "items": quick_chat.catalog(),
        }
    )
