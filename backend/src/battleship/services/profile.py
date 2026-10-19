"""Profile reads owned by the session/auth ticket.

Scope note: rank, level and badge projections live in ticket #15. What this
module must get right now is the **privacy contract** from DECISIONS D13:

* show_stats / show_fav_cards are only flags -- the stats and favourite-card
  data are still sent, exactly like the legacy /user_stats;
* show_history really does filter the history payload (the legacy endpoint did
  that, and only the server can enforce it);
* missing profile rows fall back to the legacy defaults without writing a row.

The self profile is intentionally a superset of what the ticket tests need; #15
extends the rank/level/badge parts.
"""

from __future__ import annotations

import json
from typing import Any

from ..repositories import Database

PROFILE_USER_FIELDS = (
    "id",
    "username",
    "signature",
    "avatar",
    "wins",
    "losses",
    "current_streak",
    "longest_streak",
    "created_at",
)

PUBLIC_STATS_FIELDS = (
    "id",
    "username",
    "wins",
    "losses",
    "current_streak",
    "longest_streak",
    "created_at",
    "signature",
    "avatar",
)

# Same defaults as the legacy db._PROFILE_DEFAULTS (show_history defaults to 0).
PROFILE_DEFAULTS: dict[str, Any] = {
    "title_id": "",
    "tags": [],
    "status_text": "",
    "frame_id": "none",
    "card_bg_id": "deep",
    "show_stats": 1,
    "show_fav_cards": 1,
    "show_history": 0,
    "show_guestbook": 1,
    "show_rank": 1,
    "friend_requests_open": 1,
    "updated_at": 0,
}

_FLAG_FIELDS = (
    "show_stats",
    "show_fav_cards",
    "show_history",
    "show_guestbook",
    "show_rank",
    "friend_requests_open",
)


def _parse_tags(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(item) for item in raw if item]
    try:
        data = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return [str(item) for item in data if item] if isinstance(data, list) else []


def profile_extra(uow, user_id: str) -> dict[str, Any]:
    """Read the profile row, filling legacy defaults in memory (never writing)."""
    row = uow.social.get_profile(user_id) or {}
    data = dict(PROFILE_DEFAULTS)
    data.update({key: value for key, value in row.items() if value is not None})
    data["tags"] = _parse_tags(row.get("tags"))
    for flag in _FLAG_FIELDS:
        value = row.get(flag)
        data[flag] = int(PROFILE_DEFAULTS[flag] if value is None else value)
    data["updated_at"] = int(row.get("updated_at") or 0)
    return data


def fav_cards(uow, user_id: str, limit: int = 3) -> list[dict[str, Any]]:
    """Favourite cards are data, not a permission decision (D13)."""
    return [
        {
            "name": str(row.get("card_name") or ""),
            "uses": int(row.get("uses") or 0),
        }
        for row in uow.stats.top_user_cards(user_id, limit)
        if row.get("card_name")
    ]


def build_own_profile(database: Database, user_id: str) -> dict[str, Any] | None:
    with database.unit_of_work() as uow:
        user = uow.users.get(user_id)
        if user is None:
            return None
        profile = {
            field: getattr(user, field, None)
            for field in PROFILE_USER_FIELDS
        }
        extra = profile_extra(uow, user_id)
        profile.update(extra)
        profile["rank"] = uow.stats.get_rank(user_id)
        profile["counters"] = uow.stats.get_counters(user_id)
        profile["fav_cards"] = fav_cards(uow, user_id)
        profile["mine"] = False
        profile["counts"] = {"like": 0, "flower": 0}
        profile["name_style"] = ""
    return profile


def public_stats(database: Database, user: Any, viewer_id: str | None,
                 limit: int = 20) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Legacy /user_stats projection with the D13 privacy flags preserved."""
    user_id = str(user.id)
    is_self = bool(viewer_id) and str(viewer_id) == user_id
    with database.unit_of_work() as uow:
        stats = {field: getattr(user, field, None) for field in PUBLIC_STATS_FIELDS}
        extra = profile_extra(uow, user_id)
        for flag in _FLAG_FIELDS:
            stats[flag] = extra[flag]
        stats["title_id"] = extra["title_id"]
        stats["tags"] = extra["tags"]
        stats["status_text"] = extra["status_text"]
        stats["frame_id"] = extra["frame_id"]
        stats["card_bg_id"] = extra["card_bg_id"]
        # D13: flags are sent for the frontend to draw/hide the section, but the
        # data itself keeps flowing exactly as it did in the legacy stack.
        stats["fav_cards"] = fav_cards(uow, user_id)
        stats["counts"] = {"like": 0, "flower": 0}
        stats["mine"] = False
        stats["name_style"] = ""
        stats["rank_info"] = None
        if is_self or stats["show_history"]:
            history = uow.matches.history_for_user(user_id, limit)
        else:
            history = []
    return stats, history
