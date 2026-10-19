"""user_profile, likes, wall messages, friendships and friend messages."""

from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .mapping import instance_dict
from .models import (
    FriendMessage,
    ProfileLike,
    ProfileMessage,
    UserFriend,
    UserProfile,
)

PROFILE_COLUMNS = frozenset(
    {
        "title_id",
        "tags",
        "status_text",
        "frame_id",
        "card_bg_id",
        "show_stats",
        "show_fav_cards",
        "show_history",
        "updated_at",
        "show_guestbook",
        "show_rank",
        "friend_requests_open",
        "allow_spectate",
        "allow_replay",
    }
)


class ProfileUpdateError(ValueError):
    """The caller tried to write a column that is not part of user_profile."""


class SocialRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ---------------------------------------------------------------- profile

    def get_profile(self, user_id: str | None) -> dict[str, Any] | None:
        if not user_id:
            return None
        profile = self.session.get(UserProfile, user_id)
        return instance_dict(profile) if profile is not None else None

    def save_profile(
        self,
        user_id: str,
        fields: Mapping[str, Any] | None = None,
        *,
        updated_at: int | None = None,
    ) -> dict[str, Any]:
        """Partial upsert. Unspecified columns keep their old value / DB default."""
        values = dict(fields or {})
        unknown = set(values) - PROFILE_COLUMNS
        if unknown:
            raise ProfileUpdateError(f"unknown user_profile columns: {sorted(unknown)}")
        if updated_at is not None:
            values["updated_at"] = updated_at

        statement = sqlite_insert(UserProfile).values(user_id=user_id, **values)
        if values:
            statement = statement.on_conflict_do_update(
                index_elements=["user_id"], set_=values
            )
        else:
            statement = statement.on_conflict_do_nothing(index_elements=["user_id"])
        self.session.execute(statement)
        self.session.flush()
        profile = self.get_profile(user_id)
        assert profile is not None  # the statement above guarantees the row
        return profile

    # ------------------------------------------------------------------ likes

    def add_reaction(
        self, from_user_id: str, to_user_id: str, kind: str, *, created_at: int
    ) -> bool:
        statement = sqlite_insert(ProfileLike).values(
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            kind=kind,
            created_at=created_at,
        )
        statement = statement.on_conflict_do_nothing(
            index_elements=["from_user_id", "to_user_id", "kind"]
        )
        result = self.session.execute(statement)
        return bool(result.rowcount)

    def remove_reaction(self, from_user_id: str, to_user_id: str, kind: str) -> bool:
        result = self.session.execute(
            delete(ProfileLike).where(
                ProfileLike.from_user_id == from_user_id,
                ProfileLike.to_user_id == to_user_id,
                ProfileLike.kind == kind,
            )
        )
        return bool(result.rowcount)

    def reaction_counts(self, to_user_id: str) -> dict[str, int]:
        statement = (
            select(ProfileLike.kind, func.count())
            .where(ProfileLike.to_user_id == to_user_id)
            .group_by(ProfileLike.kind)
        )
        return {kind: int(count) for kind, count in self.session.execute(statement)}

    # ---------------------------------------------------------- wall messages

    def add_wall_message(
        self,
        *,
        to_user_id: str,
        from_user_id: str,
        from_name: str,
        content: str,
        created_at: int,
    ) -> int:
        message = ProfileMessage(
            to_user_id=to_user_id,
            from_user_id=from_user_id,
            from_name=from_name,
            content=content,
            created_at=created_at,
            deleted=0,
        )
        self.session.add(message)
        self.session.flush()
        return int(message.id)

    def list_wall_messages(
        self, to_user_id: str, *, limit: int = 20, before_id: int | None = None
    ) -> list[dict[str, Any]]:
        safe_limit = min(max(1, int(limit)), 100)
        statement = (
            select(
                ProfileMessage.id,
                ProfileMessage.to_user_id,
                ProfileMessage.from_user_id,
                ProfileMessage.from_name,
                ProfileMessage.content,
                ProfileMessage.created_at,
            )
            .where(
                ProfileMessage.to_user_id == to_user_id,
                ProfileMessage.deleted == 0,
            )
            .order_by(ProfileMessage.id.desc())
            .limit(safe_limit)
        )
        if before_id is not None:
            statement = statement.where(ProfileMessage.id < int(before_id))
        return [dict(row._mapping) for row in self.session.execute(statement)]

    def soft_delete_wall_message(self, message_id: int, to_user_id: str) -> bool:
        result = self.session.execute(
            update(ProfileMessage)
            .where(
                ProfileMessage.id == message_id,
                ProfileMessage.to_user_id == to_user_id,
                ProfileMessage.deleted == 0,
            )
            .values(deleted=1)
        )
        return bool(result.rowcount)

    # -------------------------------------------------------------- friends

    def get_friend(self, user_id: str, friend_id: str) -> UserFriend | None:
        return self.session.get(UserFriend, (user_id, friend_id))

    def friend_status(self, user_id: str, friend_id: str) -> str | None:
        friend = self.get_friend(user_id, friend_id)
        return friend.status if friend is not None else None

    def upsert_friend(
        self, user_id: str, friend_id: str, status: str, *, now: int
    ) -> str:
        """Create/update one directed edge. Returns "created" or "updated"."""
        friend = self.get_friend(user_id, friend_id)
        if friend is None:
            self.session.add(
                UserFriend(
                    user_id=user_id,
                    friend_id=friend_id,
                    status=status,
                    created_at=now,
                    updated_at=now,
                )
            )
            self.session.flush()
            return "created"
        friend.status = status
        friend.updated_at = now
        self.session.flush()
        return "updated"

    def list_friends(self, user_id: str, status: str | None = None) -> list[dict[str, Any]]:
        statement = select(
            UserFriend.friend_id,
            UserFriend.status,
            UserFriend.created_at,
            UserFriend.updated_at,
        ).where(UserFriend.user_id == user_id)
        if status is not None:
            statement = statement.where(UserFriend.status == status)
        statement = statement.order_by(UserFriend.friend_id)
        return [dict(row._mapping) for row in self.session.execute(statement)]

    def delete_friend(self, user_id: str, friend_id: str) -> bool:
        result = self.session.execute(
            delete(UserFriend).where(
                UserFriend.user_id == user_id,
                UserFriend.friend_id == friend_id,
            )
        )
        return bool(result.rowcount)

    # ------------------------------------------------------- friend messages

    def add_friend_message(
        self, from_uid: str, to_uid: str, body: str, *, created_at: int
    ) -> int:
        message = FriendMessage(
            from_uid=from_uid, to_uid=to_uid, body=body, created_at=created_at, read_at=0
        )
        self.session.add(message)
        self.session.flush()
        return int(message.id)

    def list_friend_messages(
        self,
        me: str,
        other: str,
        *,
        limit: int = 50,
        before_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Oldest first (the UI appends); fetch newest N then reverse."""
        if not me or not other:
            return []
        safe_limit = min(max(1, int(limit)), 100)
        statement = (
            select(
                FriendMessage.id,
                FriendMessage.from_uid,
                FriendMessage.to_uid,
                FriendMessage.body,
                FriendMessage.created_at,
                FriendMessage.read_at,
            )
            .where(
                or_(
                    and_(FriendMessage.from_uid == me, FriendMessage.to_uid == other),
                    and_(FriendMessage.from_uid == other, FriendMessage.to_uid == me),
                )
            )
            .order_by(FriendMessage.id.desc())
            .limit(safe_limit)
        )
        if before_id is not None:
            statement = statement.where(FriendMessage.id < int(before_id))
        rows = list(self.session.execute(statement))
        return [dict(row._mapping) for row in reversed(rows)]

    def unread_count(self, to_uid: str) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(FriendMessage)
                .where(FriendMessage.to_uid == to_uid, FriendMessage.read_at == 0)
            )
            or 0
        )

    def mark_friend_messages_read(self, *, to_uid: str, from_uid: str, read_at: int) -> int:
        result = self.session.execute(
            update(FriendMessage)
            .where(
                FriendMessage.to_uid == to_uid,
                FriendMessage.from_uid == from_uid,
                FriendMessage.read_at == 0,
            )
            .values(read_at=read_at)
        )
        return int(result.rowcount or 0)