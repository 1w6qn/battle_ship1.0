"""The single match-settlement transaction boundary (ticket #9, DECISIONS D12).

One match ending writes, in this order and in one SQLAlchemy unit of work:

1. matches (mode = ranked / casual / ai / custom / NULL)
2. match_logs
3. match_replays (a version-1 placeholder until ticket #18 supplies the real blob)
4. users wins / losses / current_streak / longest_streak
5. user_counters (sunk_total / matches_played / flawless_wins / fastest_win_sec)
6. registered settlement hooks (rank / xp / achievements / anticheat, tickets #15/#16)

Any failure rolls the whole unit of work back: there is never a match row without
its log/replay/stats. Settlement is idempotent per room (room.settled), so a
surrender racing a disconnect forfeit cannot double-count the same match.

Business code never writes SQL here; the UnitOfWork repositories are the only
persistence surface.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from ..domain.room import Room
from ..domain.settlement import SettlementFacts, settlement_facts
from ..infra.logging import get_logger
from ..repositories import Database, UnitOfWork

logger = get_logger("settlement")

REPLAY_PLACEHOLDER_VERSION = 1


@dataclass(frozen=True)
class SettlementContext:
    """Everything a settlement hook may need, frozen before the commit."""

    match_id: str
    timestamp: int
    facts: SettlementFacts
    replay_saved: bool
    replay: Any = None


@dataclass(frozen=True)
class SettlementResult:
    ok: bool
    match_id: str | None = None
    skipped: bool = False
    error: str | None = None


#: A hook runs inside the same unit of work, after the core rows.
SettlementHook = Callable[[Room, UnitOfWork, SettlementContext], None]
ReplayBuilder = Callable[[Room], Any]


class SettlementService:
    """Persist one finished match, exactly once, atomically."""

    def __init__(
        self,
        database: Database | None = None,
        *,
        replay_builder: ReplayBuilder | None = None,
        hooks: Sequence[SettlementHook] | None = None,
    ) -> None:
        self.database = database
        self.replay_builder = replay_builder
        self.hooks: list[SettlementHook] = list(hooks or ())
        self._lock = threading.Lock()

    def add_hook(self, hook: SettlementHook) -> None:
        self.hooks.append(hook)

    def settle(self, room: Room, winner_id: str, loser_id: str) -> SettlementResult:
        with self._lock:
            if room.settled:
                cached = room.settlement_result
                return SettlementResult(
                    ok=True,
                    match_id=getattr(cached, "match_id", None),
                    skipped=True,
                )

            try:
                facts = settlement_facts(room, winner_id, loser_id)
            except KeyError as error:
                logger.error(
                    "settlement skipped: seat missing",
                    extra={"room_id": room.id, "missing": str(error)},
                )
                return SettlementResult(
                    ok=False, skipped=True, error=f"seat missing: {error}"
                )

            if self.database is None or (
                not facts.winner_user_id and not facts.loser_user_id
            ):
                # Legacy record_match is only called when at least one seat has
                # an account id. Domain/unit callers also have no persistence;
                # mark the room so a repeated finish does not re-run effects.
                result = SettlementResult(ok=True, skipped=True)
                room.settled = True
                room.settlement_result = result
                return result

            match_id = str(uuid.uuid4())
            timestamp = int(time.time())
            try:
                replay = self._build_replay(room)
                context = SettlementContext(
                    match_id=match_id,
                    timestamp=timestamp,
                    facts=facts,
                    replay_saved=bool(facts.winner_user_id or facts.loser_user_id),
                    replay=replay,
                )
                with self.database.unit_of_work() as uow:
                    self._write_match(uow, room, context)
                    if facts.count_stats:
                        self._write_user_stats(uow, facts)
                    for hook in self.hooks:
                        hook(room, uow, context)
            except Exception as error:  # noqa: BLE001 - the UoW already rolled back
                logger.error(
                    "match settlement failed; transaction rolled back",
                    extra={
                        "room_id": room.id,
                        "winner": winner_id,
                        "loser": loser_id,
                        "error_type": type(error).__name__,
                    },
                    exc_info=error,
                )
                return SettlementResult(ok=False, error=str(error))

            result = SettlementResult(ok=True, match_id=match_id)
            room.match_id = match_id
            room.settled = True
            room.settlement_result = result
            return result

    # ------------------------------------------------------------------ writes

    def _build_replay(self, room: Room) -> Any:
        if self.replay_builder is not None:
            return self.replay_builder(room)
        # Ticket #18 replaces this placeholder with the real replay payload.
        # Version 1 keeps legacy readers from rejecting the row outright, while
        # the explicit placeholder flag tells #18 it is not a real recording.
        return {
            "version": REPLAY_PLACEHOLDER_VERSION,
            "placeholder": True,
            "room_id": room.id,
            "winner": room.winner or None,
            "round": room.round,
            "steps": [],
        }

    def _write_match(self, uow: UnitOfWork, room: Room,
                     context: SettlementContext) -> None:
        facts = context.facts
        uow.matches.create(
            match_id=context.match_id,
            # Legacy falls back to the seat id (guest sid / ai-*) for matches.
            winner_id=facts.winner_user_id or facts.winner_id,
            loser_id=facts.loser_user_id or facts.loser_id,
            timestamp=context.timestamp,
            mode=facts.mode,
        )
        uow.matches.add_log(
            context.match_id,
            json.dumps(room.game_logs or [], ensure_ascii=False),
        )
        if context.replay_saved:
            uow.replays.save(
                context.match_id,
                context.replay,
                winner_user_id=facts.winner_user_id,
                loser_user_id=facts.loser_user_id,
                created_at=context.timestamp,
            )

    def _write_user_stats(self, uow: UnitOfWork, facts: SettlementFacts) -> None:
        winner = uow.users.get(facts.winner_user_id)
        if winner is not None:
            streak = int(winner.current_streak or 0) + 1
            uow.users.update(
                facts.winner_user_id,
                wins=int(winner.wins or 0) + 1,
                current_streak=streak,
                longest_streak=max(streak, int(winner.longest_streak or 0)),
            )
            uow.stats.bump_counters(
                facts.winner_user_id,
                sunk_total=facts.winner_sunk,
                matches_played=1,
                flawless_wins=1 if facts.winner_flawless else 0,
                fastest_win_sec=facts.duration_seconds,
            )

        loser = uow.users.get(facts.loser_user_id)
        if loser is not None:
            uow.users.update(
                facts.loser_user_id,
                losses=int(loser.losses or 0) + 1,
                current_streak=0,
            )
            uow.stats.bump_counters(
                facts.loser_user_id,
                sunk_total=facts.loser_sunk,
                matches_played=1,
            )
