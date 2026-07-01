"""
NeuroAntiSpam - GitHub Data Sync
Writes bot state (groups, settings, stats) to the GitHub repo
so the static GitHub Pages site can read it.
Runs as a scheduled job every 5 minutes inside GitHub Actions.
"""

import asyncio
import base64
import json
import logging
import os
from datetime import datetime, timedelta

import aiohttp

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


class GitHubSync:
    def __init__(self, token: str, repo: str):
        """
        token: GitHub token with contents:write scope (from GH_TOKEN secret)
        repo:  "WZCasper/NeuroAntiSpam"
        """
        self.token = token
        self.repo = repo
        self.headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _get_file_sha(self, session: aiohttp.ClientSession, path: str) -> str | None:
        """Get current SHA of a file (needed for updates)."""
        url = f"{GITHUB_API}/repos/{self.repo}/contents/{path}"
        async with session.get(url, headers=self.headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("sha")
            return None

    async def write_file(self, session: aiohttp.ClientSession, path: str, content: dict | list, message: str = "🤖 Auto-sync [skip ci]"):
        """Write/update a JSON file in the repository."""
        url = f"{GITHUB_API}/repos/{self.repo}/contents/{path}"
        json_bytes = json.dumps(content, ensure_ascii=False, indent=2).encode()
        b64_content = base64.b64encode(json_bytes).decode()

        sha = await self._get_file_sha(session, path)

        payload = {
            "message": message,
            "content": b64_content,
            "branch": "main",
        }
        if sha:
            payload["sha"] = sha

        async with session.put(url, headers=self.headers, json=payload) as resp:
            if resp.status not in (200, 201):
                text = await resp.text()
                logger.error(f"GitHub write failed for {path}: {resp.status} {text[:200]}")
                return False
            return True

    async def read_file(self, session: aiohttp.ClientSession, path: str) -> dict | list | None:
        """Read a JSON file from the repository."""
        url = f"{GITHUB_API}/repos/{self.repo}/contents/{path}"
        async with session.get(url, headers=self.headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                content = base64.b64decode(data["content"]).decode()
                return json.loads(content)
            return None

    async def sync_groups(self, db) -> bool:
        """Write all group settings + basic info to data/groups.json"""
        from sqlalchemy import select
        from database.db import Group, GroupMember

        async with db.session() as s:
            result = await s.execute(select(Group).where(Group.is_active == True))
            groups = result.scalars().all()

            groups_data = []
            for g in groups:
                # Count members
                members_result = await s.execute(
                    select(GroupMember).where(GroupMember.group_id == g.id)
                )
                member_count = len(members_result.scalars().all())

                groups_data.append({
                    "id": g.id,
                    "title": g.title,
                    "username": g.username,
                    "settings": g.settings or {},
                    "member_count": member_count,
                    "added_at": g.added_at.isoformat() if g.added_at else None,
                })

        async with aiohttp.ClientSession() as session:
            return await self.write_file(session, "data/groups.json", groups_data)

    async def sync_stats(self, db) -> bool:
        """Write last 7 days stats for all groups to data/stats.json"""
        from sqlalchemy import select, func
        from database.db import SpamLog, Group

        since = datetime.utcnow() - timedelta(days=7)
        stats_data = {}

        async with db.session() as s:
            groups_result = await s.execute(
                select(Group).where(Group.is_active == True)
            )
            groups = groups_result.scalars().all()

            for g in groups:
                total_q = await s.execute(
                    select(func.count(SpamLog.id))
                    .where(SpamLog.group_id == g.id, SpamLog.detected_at >= since)
                )
                by_action_q = await s.execute(
                    select(SpamLog.action_taken, func.count(SpamLog.id))
                    .where(SpamLog.group_id == g.id, SpamLog.detected_at >= since)
                    .group_by(SpamLog.action_taken)
                )
                by_method_q = await s.execute(
                    select(SpamLog.detection_method, func.count(SpamLog.id))
                    .where(SpamLog.group_id == g.id, SpamLog.detected_at >= since)
                    .group_by(SpamLog.detection_method)
                )
                by_day_q = await s.execute(
                    select(
                        func.date(SpamLog.detected_at).label("day"),
                        func.count(SpamLog.id).label("count")
                    )
                    .where(SpamLog.group_id == g.id, SpamLog.detected_at >= since)
                    .group_by(func.date(SpamLog.detected_at))
                    .order_by(func.date(SpamLog.detected_at))
                )

                # Recent spam log (last 20 events)
                recent_q = await s.execute(
                    select(SpamLog)
                    .where(SpamLog.group_id == g.id)
                    .order_by(SpamLog.detected_at.desc())
                    .limit(20)
                )
                recent = recent_q.scalars().all()

                stats_data[str(g.id)] = {
                    "total": total_q.scalar() or 0,
                    "by_action": dict(by_action_q.all()),
                    "by_method": dict(by_method_q.all()),
                    "by_day": [
                        {"day": str(row.day), "count": row.count}
                        for row in by_day_q
                    ],
                    "recent": [
                        {
                            "user_id": l.user_id,
                            "username": l.username,
                            "message": (l.message_text or "")[:120],
                            "score": round(l.spam_score, 2),
                            "method": l.detection_method,
                            "action": l.action_taken,
                            "detected_at": l.detected_at.isoformat(),
                        }
                        for l in recent
                    ],
                    "updated_at": datetime.utcnow().isoformat(),
                }

        async with aiohttp.ClientSession() as session:
            return await self.write_file(session, "data/stats.json", stats_data)

    async def sync_all(self, db, context=None):
        """Sync everything. Called as a scheduled job every 5 minutes."""
        logger.info("Starting GitHub sync...")
        ok1 = await self.sync_groups(db)
        ok2 = await self.sync_stats(db)
        if ok1 and ok2:
            logger.info("GitHub sync complete ✅")
        else:
            logger.warning("GitHub sync partially failed")
