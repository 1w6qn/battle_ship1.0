"""Progress/stats tables: card usage, counters, achievements, xp, rank, perks, anticheat.

Persistence only. Business policy (when to award xp, replay retention, suspicion
thresholds) belongs in services/domain and is intentionally not implemented here.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .mapping import instance_dict
from .models import (
    AnticheatFlag,
    AnticheatOverride,
    CardUsage,
    MatchSuspicion,
    UserAchievement,
    UserCardUsage,
    UserCounters,
    UserPerk,
    UserRank,
    UserXp,
)

COUNTER_ADD_FIELDS = ("sunk_total", "matches_played", "flawless_wins")
COUNTER_FIELDS = ("sunk_total", "matches_played", "flawless_wins", "fastest_win_sec")


def _limit(value: int, maximum: int = 100) -> int:
    return min(max(1, int(value)), maximum)


def _now() -> int:
    return int(time.time())


class StatsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------ card usage

    def increment_card_usage(self, card_name: str, *, delta: int = 1, now: int | None = None) -> None:
        now = _now() if now is None else now
        statement = sqlite_insert(CardUsage).values(
            card_name=card_name, uses=delta, updated_at=now
        )
        statement = statement.on_conflict_do_update(
            index_elements=["card_name"],
            set_={
                "uses": CardUsage.uses + statement.excluded.uses,
                "updated_at": statement.excluded.updated_at,
            },
        )
        self.session.execute(statement)

    def card_uses(self, card_name: str) -> int:
        return int(
            self.session.scalar(
                select(CardUsage.uses).where(CardUsage.card_name == card_name)
            )
            or 0
        )

    def top_cards(self, limit: int = 10) -> list[dict[str, Any]]:
        statement = (
            select(CardUsage.card_name, CardUsage.uses, CardUsage.updated_at)
            .order_by(CardUsage.uses.desc(), CardUsage.card_name)
            .limit(_limit(limit))
        )
        return [dict(row._mapping) for row in self.session.execute(statement)]

    def increment_user_card_usage(
        self, user_id: str, card_name: str, *, delta: int = 1, now: int | None = None
    ) -> None:
        now = _now() if now is None else now
        statement = sqlite_insert(UserCardUsage).values(
            user_id=user_id, card_name=card_name, uses=delta, updated_at=now
        )
        statement = statement.on_conflict_do_update(
            index_elements=["user_id", "card_name"],
            set_={
                "uses": UserCardUsage.uses + statement.excluded.uses,
                "updated_at": statement.excluded.updated_at,
            },
        )
        self.session.execute(statement)

    def user_card_uses(self, user_id: str, card_name: str) -> int:
        return int(
            self.session.scalar(
                select(UserCardUsage.uses).where(
                    UserCardUsage.user_id == user_id,
                    UserCardUsage.card_name == card_name,
                )
            )
            or 0
        )

    def top_user_cards(self, user_id: str, limit: int = 3) -> list[dict[str, Any]]:
        statement = (
            select(UserCardUsage.card_name, UserCardUsage.uses, UserCardUsage.updated_at)
            .where(UserCardUsage.user_id == user_id)
            .order_by(UserCardUsage.uses.desc(), UserCardUsage.card_name)
            .limit(_limit(limit))
        )
        return [dict(row._mapping) for row in self.session.execute(statement)]

    # -------------------------------------------------------------- counters

    def get_counters(self, user_id: str) -> dict[str, Any]:
        counters = self.session.get(UserCounters, user_id)
        if counters is None:
            return {
                "user_id": user_id,
                "sunk_total": 0,
                "matches_played": 0,
                "flawless_wins": 0,
                "fastest_win_sec": 0,
                "updated_at": 0,
            }
        data = instance_dict(counters)
        for field in COUNTER_FIELDS:
            data[field] = max(0, int(data.get(field) or 0))
        data["updated_at"] = int(data.get("updated_at") or 0)
        return data

    def bump_counters(self, user_id: str, *, now: int | None = None, **deltas: int) -> dict[str, Any]:
        """Add counts; fastest_win_sec keeps the smallest non-zero value (legacy rule)."""
        unknown = set(deltas) - set(COUNTER_FIELDS)
        if unknown:
            raise ValueError(f"unknown user_counters columns: {sorted(unknown)}")
        now = _now() if now is None else now
        values = {field: 0 for field in COUNTER_ADD_FIELDS}
        insert_values = {"user_id": user_id, "updated_at": now, **values}
        set_values: dict[str, Any] = {"updated_at": now}

        for field in COUNTER_ADD_FIELDS:
            raw = deltas.get(field)
            if raw is None:
                continue
            value = max(0, int(raw))
            insert_values[field] = value
            set_values[field] = getattr(UserCounters, field) + value

        fastest = deltas.get("fastest_win_sec")
        if fastest is not None:
            candidate = int(fastest)
            if candidate > 0:
                insert_values["fastest_win_sec"] = candidate
                current = UserCounters.fastest_win_sec
                set_values["fastest_win_sec"] = case(
                    (func.coalesce(current, 0) == 0, candidate),
                    else_=func.min(current, candidate),
                )

        statement = sqlite_insert(UserCounters).values(**insert_values)
        statement = statement.on_conflict_do_update(
            index_elements=["user_id"], set_=set_values
        )
        self.session.execute(statement)
        self.session.flush()
        return self.get_counters(user_id)

    # ---------------------------------------------------------- achievements

    def unlock_achievement(self, user_id: str, badge_id: str, *, unlocked_at: int) -> bool:
        statement = sqlite_insert(UserAchievement).values(
            user_id=user_id, badge_id=badge_id, unlocked_at=unlocked_at
        )
        statement = statement.on_conflict_do_nothing(
            index_elements=["user_id", "badge_id"]
        )
        result = self.session.execute(statement)
        return bool(result.rowcount)

    def list_achievements(self, user_id: str) -> list[dict[str, Any]]:
        statement = (
            select(UserAchievement.badge_id, UserAchievement.unlocked_at)
            .where(UserAchievement.user_id == user_id)
            .order_by(UserAchievement.unlocked_at, UserAchievement.badge_id)
        )
        return [dict(row._mapping) for row in self.session.execute(statement)]

    # -------------------------------------------------------------------- xp

    def get_xp(self, user_id: str) -> int:
        return int(self.session.scalar(select(UserXp.xp).where(UserXp.user_id == user_id)) or 0)

    def add_xp(self, user_id: str, delta: int, *, now: int | None = None) -> int:
        """XP only grows: a non-positive delta returns the current value."""
        now = _now() if now is None else now
        amount = int(delta)
        if amount <= 0:
            return self.get_xp(user_id)
        statement = sqlite_insert(UserXp).values(
            user_id=user_id, xp=amount, updated_at=now
        )
        statement = statement.on_conflict_do_update(
            index_elements=["user_id"],
            set_={"xp": UserXp.xp + statement.excluded.xp, "updated_at": now},
        )
        self.session.execute(statement)
        self.session.flush()
        return self.get_xp(user_id)

    # ------------------------------------------------------------------ perks

    def grant_perk(self, user_id: str, perk: str, *, granted_at: int) -> bool:
        statement = sqlite_insert(UserPerk).values(
            user_id=user_id, perk=perk, granted_at=granted_at
        )
        statement = statement.on_conflict_do_nothing(index_elements=["user_id", "perk"])
        result = self.session.execute(statement)
        return bool(result.rowcount)

    def list_perks(self, user_id: str) -> list[str]:
        statement = (
            select(UserPerk.perk)
            .where(UserPerk.user_id == user_id)
            .order_by(UserPerk.granted_at, UserPerk.perk)
        )
        return list(self.session.scalars(statement))

    # ------------------------------------------------------------------- rank

    def get_rank(self, user_id: str) -> dict[str, Any]:
        rank = self.session.get(UserRank, user_id)
        if rank is None:
            return {
                "user_id": user_id,
                "points": 0,
                "is_admiral": 0,
                "ranked_wins": 0,
                "ranked_losses": 0,
                "updated_at": 0,
            }
        data = instance_dict(rank)
        for field in ("points", "is_admiral", "ranked_wins", "ranked_losses"):
            data[field] = max(0, int(data.get(field) or 0))
        data["updated_at"] = int(data.get("updated_at") or 0)
        return data

    def add_rank_points(
        self,
        user_id: str,
        delta: int,
        *,
        is_admiral: bool | None = None,
        now: int | None = None,
    ) -> dict[str, Any]:
        """Floor points at zero; a positive/negative delta counts as a win/loss."""
        now = _now() if now is None else now
        change = int(delta)
        won = 1 if change > 0 else 0
        lost = 1 if change < 0 else 0
        insert_values = {
            "user_id": user_id,
            "points": max(0, change),
            "is_admiral": 1 if is_admiral else 0,
            "ranked_wins": won,
            "ranked_losses": lost,
            "updated_at": now,
        }
        set_values: dict[str, Any] = {
            "points": func.max(0, UserRank.points + change),
            "ranked_wins": UserRank.ranked_wins + won,
            "ranked_losses": UserRank.ranked_losses + lost,
            "updated_at": now,
        }
        if is_admiral is not None:
            set_values["is_admiral"] = 1 if is_admiral else 0
        statement = sqlite_insert(UserRank).values(**insert_values)
        statement = statement.on_conflict_do_update(
            index_elements=["user_id"], set_=set_values
        )
        self.session.execute(statement)
        self.session.flush()
        return self.get_rank(user_id)

    def rank_leaderboard(self, limit: int = 10) -> list[dict[str, Any]]:
        statement = (
            select(
                UserRank.user_id,
                UserRank.points,
                UserRank.is_admiral,
                UserRank.ranked_wins,
                UserRank.ranked_losses,
                UserRank.updated_at,
            )
            .order_by(
                UserRank.points.desc(),
                func.coalesce(UserRank.updated_at, 0),
                UserRank.user_id,
            )
            .limit(_limit(limit))
        )
        return [dict(row._mapping) for row in self.session.execute(statement)]

    # ------------------------------------------------------------- anticheat

    def record_anticheat_flag(
        self,
        match_id: str,
        *,
        rule: str,
        severity: str,
        detail: str,
        created_at: int,
    ) -> None:
        values = {
            "match_id": match_id,
            "rule": rule,
            "severity": severity,
            "detail": detail,
            "created_at": created_at,
        }
        statement = sqlite_insert(AnticheatFlag).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=["match_id"],
            set_={key: statement.excluded[key] for key in values if key != "match_id"},
        )
        self.session.execute(statement)

    def get_anticheat_flag(self, match_id: str) -> dict[str, Any] | None:
        flag = self.session.get(AnticheatFlag, match_id)
        return instance_dict(flag) if flag is not None else None

    def record_suspicion(
        self,
        *,
        match_id: str,
        user_id: str,
        score: int,
        level: str | None,
        created_at: int,
    ) -> None:
        values = {
            "match_id": match_id,
            "user_id": user_id,
            "score": score,
            "level": level,
            "created_at": created_at,
        }
        statement = sqlite_insert(MatchSuspicion).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=["match_id"],
            set_={key: statement.excluded[key] for key in values if key != "match_id"},
        )
        self.session.execute(statement)

    def list_suspicions(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        statement = (
            select(
                MatchSuspicion.match_id,
                MatchSuspicion.user_id,
                MatchSuspicion.score,
                MatchSuspicion.level,
                MatchSuspicion.created_at,
            )
            .where(MatchSuspicion.user_id == user_id)
            .order_by(MatchSuspicion.created_at.desc())
            .limit(_limit(limit))
        )
        return [dict(row._mapping) for row in self.session.execute(statement)]

    def record_override(
        self,
        *,
        user_id: str,
        level: int,
        cleared: int,
        reason: str,
        actor: str,
        created_at: int,
    ) -> int:
        override = AnticheatOverride(
            user_id=user_id,
            level=level,
            cleared=cleared,
            reason=reason,
            actor=actor,
            created_at=created_at,
        )
        self.session.add(override)
        self.session.flush()
        return int(override.id)

    def latest_override(self, user_id: str) -> dict[str, Any] | None:
        statement = (
            select(AnticheatOverride)
            .where(AnticheatOverride.user_id == user_id)
            .order_by(AnticheatOverride.id.desc())
            .limit(1)
        )
        override = self.session.scalar(statement)
        return instance_dict(override) if override is not None else None