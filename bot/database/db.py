"""
NeuroAntiSpam Database Layer
Async SQLAlchemy with SQLite (dev) / PostgreSQL (prod)
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from sqlalchemy import (
    Column, Integer, BigInteger, String, Boolean, Float,
    DateTime, Text, JSON, ForeignKey, UniqueConstraint, Index, select, update, delete, func
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, relationship

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class Group(Base):
    __tablename__ = "groups"

    id = Column(BigInteger, primary_key=True)          # Telegram chat_id
    title = Column(String(255))
    username = Column(String(100), nullable=True)
    owner_id = Column(BigInteger, nullable=True)
    added_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    # Settings stored as JSON
    settings = Column(JSON, default=dict)

    members = relationship("GroupMember", back_populates="group", cascade="all, delete-orphan")
    spam_logs = relationship("SpamLog", back_populates="group", cascade="all, delete-orphan")
    custom_phrases = relationship("SpamPhrase", back_populates="group", cascade="all, delete-orphan")

    def get_setting(self, key: str, default=None):
        s = self.settings or {}
        return s.get(key, default)

    def update_setting(self, key: str, value):
        if self.settings is None:
            self.settings = {}
        self.settings = {**self.settings, key: value}


class GroupMember(Base):
    __tablename__ = "group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id"),
        Index("idx_member_group_user", "group_id", "user_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(BigInteger, ForeignKey("groups.id", ondelete="CASCADE"))
    user_id = Column(BigInteger)
    username = Column(String(100), nullable=True)
    full_name = Column(String(255), nullable=True)
    warnings = Column(Integer, default=0)
    message_count = Column(Integer, default=0)
    is_whitelisted = Column(Boolean, default=False)
    is_blacklisted = Column(Boolean, default=False)
    is_muted = Column(Boolean, default=False)
    mute_until = Column(DateTime, nullable=True)
    is_shadowbanned = Column(Boolean, default=False)
    joined_at = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)

    group = relationship("Group", back_populates="members")


class SpamLog(Base):
    __tablename__ = "spam_logs"
    __table_args__ = (
        Index("idx_spam_group_time", "group_id", "detected_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(BigInteger, ForeignKey("groups.id", ondelete="CASCADE"))
    user_id = Column(BigInteger)
    username = Column(String(100), nullable=True)
    message_text = Column(Text)
    spam_score = Column(Float)
    detection_method = Column(String(50))   # ml / keyword / regex / ai
    action_taken = Column(String(50))       # banned / kicked / muted / warned / deleted
    detected_at = Column(DateTime, default=datetime.utcnow)
    confirmed = Column(Boolean, nullable=True)  # None=pending, True=confirmed, False=false_positive

    group = relationship("Group", back_populates="spam_logs")


class SpamPhrase(Base):
    __tablename__ = "spam_phrases"
    __table_args__ = (
        Index("idx_phrase_group", "group_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(BigInteger, ForeignKey("groups.id", ondelete="CASCADE"), nullable=True)
    phrase = Column(Text)
    weight = Column(Float, default=1.0)
    is_regex = Column(Boolean, default=False)
    is_global = Column(Boolean, default=False)  # shared across all groups
    added_by = Column(BigInteger, nullable=True)
    added_at = Column(DateTime, default=datetime.utcnow)
    hit_count = Column(Integer, default=0)

    group = relationship("Group", back_populates="custom_phrases")


class TrainingData(Base):
    """ML training samples collected from user reports."""
    __tablename__ = "training_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    text = Column(Text)
    is_spam = Column(Boolean)
    source = Column(String(50))   # report / auto / manual
    added_at = Column(DateTime, default=datetime.utcnow)
    used_in_training = Column(Boolean, default=False)


class FloodTracker(Base):
    __tablename__ = "flood_tracker"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(BigInteger)
    user_id = Column(BigInteger)
    message_count = Column(Integer, default=0)
    window_start = Column(DateTime, default=datetime.utcnow)


class RaidTracker(Base):
    __tablename__ = "raid_tracker"

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(BigInteger, unique=True)
    join_count = Column(Integer, default=0)
    window_start = Column(DateTime, default=datetime.utcnow)
    raid_active = Column(Boolean, default=False)


class Database:
    def __init__(self, url: str):
        self.url = url
        self.engine = None
        self.session_factory = None

    async def initialize(self):
        self.engine = create_async_engine(self.url, echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        logger.info("Database tables created/verified")

    def session(self) -> AsyncSession:
        return self.session_factory()

    # ─── Group ─────────────────────────────────────────────────────────────────

    async def get_or_create_group(self, chat_id: int, title: str = "", username: str = None) -> Group:
        async with self.session() as s:
            group = await s.get(Group, chat_id)
            if not group:
                group = Group(
                    id=chat_id,
                    title=title,
                    username=username,
                    settings=self._default_settings(),
                )
                s.add(group)
                await s.commit()
                await s.refresh(group)
            return group

    def _default_settings(self) -> dict:
        return {
            "mode": "medium",
            "spam_threshold": 0.75,
            "captcha_enabled": True,
            "captcha_timeout": 60,
            "flood_enabled": True,
            "flood_limit": 5,
            "flood_window": 10,
            "antilink_enabled": True,
            "antilink_new_only": True,
            "new_user_quarantine": True,
            "quarantine_msgs": 5,
            "shadowban_enabled": False,
            "raid_protection": True,
            "raid_threshold": 10,
            "language_filter": None,
            "welcome_message": None,
            "welcome_enabled": True,
            "notify_admin": True,
            "notify_channel_id": None,
            "log_actions": True,
            "night_mode_enabled": False,
            "night_mode_start": 23,
            "night_mode_end": 7,
            "auto_delete_spam": True,
            "max_warnings": 3,
        }

    async def update_group_settings(self, group_id: int, settings: dict):
        async with self.session() as s:
            await s.execute(
                update(Group)
                .where(Group.id == group_id)
                .values(settings={**settings})
            )
            await s.commit()

    async def get_all_groups(self) -> List[Group]:
        async with self.session() as s:
            result = await s.execute(select(Group).where(Group.is_active == True))
            return result.scalars().all()

    # ─── Members ───────────────────────────────────────────────────────────────

    async def get_or_create_member(self, group_id: int, user_id: int,
                                   username: str = None, full_name: str = None) -> GroupMember:
        async with self.session() as s:
            result = await s.execute(
                select(GroupMember)
                .where(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
            )
            member = result.scalar_one_or_none()
            if not member:
                member = GroupMember(
                    group_id=group_id, user_id=user_id,
                    username=username, full_name=full_name,
                )
                s.add(member)
                await s.commit()
                await s.refresh(member)
            else:
                # Update last seen
                member.last_seen = datetime.utcnow()
                if username:
                    member.username = username
                member.message_count += 1
                await s.commit()
            return member

    async def add_warning(self, group_id: int, user_id: int) -> int:
        async with self.session() as s:
            result = await s.execute(
                select(GroupMember)
                .where(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
            )
            member = result.scalar_one_or_none()
            if member:
                member.warnings += 1
                await s.commit()
                return member.warnings
            return 1

    async def reset_warnings(self, group_id: int, user_id: int):
        async with self.session() as s:
            await s.execute(
                update(GroupMember)
                .where(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
                .values(warnings=0)
            )
            await s.commit()

    async def set_mute(self, group_id: int, user_id: int, until: Optional[datetime]):
        async with self.session() as s:
            await s.execute(
                update(GroupMember)
                .where(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
                .values(is_muted=until is not None, mute_until=until)
            )
            await s.commit()

    async def set_whitelist(self, group_id: int, user_id: int, value: bool):
        async with self.session() as s:
            await s.execute(
                update(GroupMember)
                .where(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
                .values(is_whitelisted=value)
            )
            await s.commit()

    async def set_blacklist(self, group_id: int, user_id: int, value: bool):
        async with self.session() as s:
            await s.execute(
                update(GroupMember)
                .where(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
                .values(is_blacklisted=value)
            )
            await s.commit()

    async def set_shadowban(self, group_id: int, user_id: int, value: bool):
        async with self.session() as s:
            await s.execute(
                update(GroupMember)
                .where(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
                .values(is_shadowbanned=value)
            )
            await s.commit()

    # ─── Spam Logs ─────────────────────────────────────────────────────────────

    async def log_spam(self, group_id: int, user_id: int, username: str,
                       text: str, score: float, method: str, action: str) -> int:
        async with self.session() as s:
            log = SpamLog(
                group_id=group_id, user_id=user_id, username=username,
                message_text=text[:4000], spam_score=score,
                detection_method=method, action_taken=action,
            )
            s.add(log)
            await s.commit()
            return log.id

    async def get_group_stats(self, group_id: int, days: int = 7) -> Dict[str, Any]:
        since = datetime.utcnow() - timedelta(days=days)
        async with self.session() as s:
            total = await s.execute(
                select(func.count(SpamLog.id))
                .where(SpamLog.group_id == group_id, SpamLog.detected_at >= since)
            )
            by_action = await s.execute(
                select(SpamLog.action_taken, func.count(SpamLog.id))
                .where(SpamLog.group_id == group_id, SpamLog.detected_at >= since)
                .group_by(SpamLog.action_taken)
            )
            by_method = await s.execute(
                select(SpamLog.detection_method, func.count(SpamLog.id))
                .where(SpamLog.group_id == group_id, SpamLog.detected_at >= since)
                .group_by(SpamLog.detection_method)
            )
            return {
                "total": total.scalar(),
                "by_action": dict(by_action.all()),
                "by_method": dict(by_method.all()),
            }

    # ─── Spam Phrases ──────────────────────────────────────────────────────────

    async def get_spam_phrases(self, group_id: int) -> List[SpamPhrase]:
        async with self.session() as s:
            result = await s.execute(
                select(SpamPhrase)
                .where(
                    (SpamPhrase.is_global == True) |
                    (SpamPhrase.group_id == group_id)
                )
            )
            return result.scalars().all()

    async def add_spam_phrase(self, phrase: str, group_id: int = None,
                              is_global: bool = False, added_by: int = None,
                              is_regex: bool = False, weight: float = 1.0):
        async with self.session() as s:
            p = SpamPhrase(
                phrase=phrase, group_id=group_id, is_global=is_global,
                added_by=added_by, is_regex=is_regex, weight=weight,
            )
            s.add(p)
            await s.commit()

    async def increment_phrase_hit(self, phrase_id: int):
        async with self.session() as s:
            await s.execute(
                update(SpamPhrase)
                .where(SpamPhrase.id == phrase_id)
                .values(hit_count=SpamPhrase.hit_count + 1)
            )
            await s.commit()

    # ─── Training Data ─────────────────────────────────────────────────────────

    async def add_training_sample(self, text: str, is_spam: bool, source: str = "manual"):
        async with self.session() as s:
            sample = TrainingData(text=text, is_spam=is_spam, source=source)
            s.add(sample)
            await s.commit()

    async def get_untraining_samples(self, limit: int = 1000) -> List[TrainingData]:
        async with self.session() as s:
            result = await s.execute(
                select(TrainingData)
                .where(TrainingData.used_in_training == False)
                .limit(limit)
            )
            return result.scalars().all()

    async def mark_samples_trained(self, ids: List[int]):
        async with self.session() as s:
            await s.execute(
                update(TrainingData)
                .where(TrainingData.id.in_(ids))
                .values(used_in_training=True)
            )
            await s.commit()

    async def get_all_training_data(self) -> List[TrainingData]:
        async with self.session() as s:
            result = await s.execute(select(TrainingData))
            return result.scalars().all()

    # ─── Flood ─────────────────────────────────────────────────────────────────

    async def increment_flood(self, group_id: int, user_id: int, window: int) -> int:
        async with self.session() as s:
            result = await s.execute(
                select(FloodTracker)
                .where(FloodTracker.group_id == group_id, FloodTracker.user_id == user_id)
            )
            tracker = result.scalar_one_or_none()
            now = datetime.utcnow()
            if not tracker:
                tracker = FloodTracker(group_id=group_id, user_id=user_id, message_count=1, window_start=now)
                s.add(tracker)
            else:
                elapsed = (now - tracker.window_start).total_seconds()
                if elapsed > window:
                    tracker.message_count = 1
                    tracker.window_start = now
                else:
                    tracker.message_count += 1
            await s.commit()
            return tracker.message_count

    # ─── Raid ──────────────────────────────────────────────────────────────────

    async def increment_raid(self, group_id: int, window: int) -> int:
        async with self.session() as s:
            result = await s.execute(
                select(RaidTracker).where(RaidTracker.group_id == group_id)
            )
            tracker = result.scalar_one_or_none()
            now = datetime.utcnow()
            if not tracker:
                tracker = RaidTracker(group_id=group_id, join_count=1, window_start=now)
                s.add(tracker)
            else:
                elapsed = (now - tracker.window_start).total_seconds()
                if elapsed > window:
                    tracker.join_count = 1
                    tracker.window_start = now
                else:
                    tracker.join_count += 1
            await s.commit()
            return tracker.join_count

    # ─── Cleanup ───────────────────────────────────────────────────────────────

    async def cleanup_old_data(self, context=None):
        cutoff = datetime.utcnow() - timedelta(days=90)
        async with self.session() as s:
            await s.execute(delete(SpamLog).where(SpamLog.detected_at < cutoff))
            await s.execute(delete(TrainingData).where(
                TrainingData.added_at < cutoff,
                TrainingData.used_in_training == True,
            ))
            await s.commit()
        logger.info("Old data cleaned up")
