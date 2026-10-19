"""Legacy profile-card save endpoint (ticket #15).

GET /api/profile is owned by the auth router; this router only adds the POST that
validates the 11 writable fields against the unlock rules. Error shapes are the
frozen legacy shapes (D19), not the structured rewrite envelope.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ...services.profile import save_profile_card
from ..session import read_session, session_user_id

router = APIRouter(tags=["profile"])


async def _payload(request: Request) -> Any:
    try:
        data = await request.json()
    except Exception:
        data = None
    if data is not None:
        return data
    try:
        form = await request.form()
    except Exception:
        return None
    return {key: form.get(key) for key in form.keys()} if form else None


@router.post("/api/profile/card")
async def save_card(request: Request):
    user_id = session_user_id(read_session(request))
    if not user_id:
        return JSONResponse({"success": False, "error": "未登录"}, status_code=401)
    payload = await _payload(request)
    status, body = save_profile_card(request.app.state.database, user_id, payload)
    return JSONResponse(body, status_code=status)
