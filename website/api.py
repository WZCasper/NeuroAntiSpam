"""
NeuroAntiSpam - FastAPI Backend
REST API + WebSocket + Telegram Login Widget OAuth
"""

import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional, List

import jwt
from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select, update

logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────

BOT_TOKEN = os.environ["BOT_TOKEN"]
BOT_TOKEN_HASH = hashlib.sha256(BOT_TOKEN.encode()).digest()
JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-in-production")
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///neuroantispam.db")
FRONTEND_URL = os.environ.get("WEBSITE_URL", "http://localhost:3000")

# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(title="NeuroAntiSpam API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:3000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Database ───────────────────────────────────────────────────────────────────

engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session


# ── WebSocket Manager ──────────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active: dict[int, list[WebSocket]] = {}  # group_id → [ws]

    async def connect(self, ws: WebSocket, group_id: int):
        await ws.accept()
        self.active.setdefault(group_id, []).append(ws)

    def disconnect(self, ws: WebSocket, group_id: int):
        conns = self.active.get(group_id, [])
        if ws in conns:
            conns.remove(ws)

    async def broadcast(self, group_id: int, data: dict):
        for ws in self.active.get(group_id, []):
            try:
                await ws.send_json(data)
            except Exception:
                pass


manager = ConnectionManager()

# ── Schemas ────────────────────────────────────────────────────────────────────

class TelegramAuthData(BaseModel):
    id: int
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None
    photo_url: Optional[str] = None
    auth_date: int
    hash: str


class GroupSettings(BaseModel):
    mode: Optional[str] = None
    spam_threshold: Optional[float] = None
    captcha_enabled: Optional[bool] = None
    captcha_timeout: Optional[int] = None
    flood_enabled: Optional[bool] = None
    flood_limit: Optional[int] = None
    flood_window: Optional[int] = None
    antilink_enabled: Optional[bool] = None
    antilink_new_only: Optional[bool] = None
    new_user_quarantine: Optional[bool] = None
    quarantine_msgs: Optional[int] = None
    shadowban_enabled: Optional[bool] = None
    raid_protection: Optional[bool] = None
    raid_threshold: Optional[int] = None
    language_filter: Optional[str] = None
    welcome_enabled: Optional[bool] = None
    welcome_message: Optional[str] = None
    notify_admin: Optional[bool] = None
    auto_delete_spam: Optional[bool] = None
    max_warnings: Optional[int] = None
    night_mode_enabled: Optional[bool] = None
    night_mode_start: Optional[int] = None
    night_mode_end: Optional[int] = None


class SpamPhraseCreate(BaseModel):
    phrase: str
    is_regex: bool = False
    weight: float = 1.0


# ── Auth ───────────────────────────────────────────────────────────────────────

def verify_telegram_auth(data: TelegramAuthData) -> bool:
    """Verify Telegram Login Widget data signature."""
    check_hash = data.hash
    data_dict = data.dict(exclude={"hash"})
    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(data_dict.items()) if v is not None
    )
    computed = hmac.new(BOT_TOKEN_HASH, data_check_string.encode(), hashlib.sha256).hexdigest()
    if computed != check_hash:
        return False
    # Check auth_date not older than 24 hours
    if time.time() - data.auth_date > 86400:
        return False
    return True


def create_jwt(user_id: int, username: str) -> str:
    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": datetime.utcnow() + timedelta(days=7),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def get_current_user(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = auth[7:]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return {"user_id": int(payload["sub"]), "username": payload.get("username", "")}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


@app.post("/api/auth/telegram")
async def telegram_auth(data: TelegramAuthData):
    """Telegram Login Widget callback — verify and issue JWT."""
    if not verify_telegram_auth(data):
        raise HTTPException(status_code=403, detail="Invalid Telegram auth data")
    token = create_jwt(data.id, data.username or data.first_name)
    return {
        "token": token,
        "user": {
            "id": data.id,
            "name": f"{data.first_name} {data.last_name or ''}".strip(),
            "username": data.username,
            "photo_url": data.photo_url,
        },
    }


@app.get("/api/groups")
async def get_my_groups(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return groups where the current user is an admin."""
    from database.db import Group
    # In production, cross-check with Telegram API to get real admin groups
    # Here we return all groups from DB where the bot is active
    result = await db.execute(select(Group).where(Group.is_active == True))
    groups = result.scalars().all()
    return [
        {
            "id": g.id,
            "title": g.title,
            "username": g.username,
            "settings": g.settings,
        }
        for g in groups
    ]


@app.get("/api/groups/{group_id}/settings")
async def get_settings(
    group_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from database.db import Group
    group = await db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    return group.settings


@app.patch("/api/groups/{group_id}/settings")
async def update_settings(
    group_id: int,
    settings: GroupSettings,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from database.db import Group
    group = await db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    current = dict(group.settings or {})
    patch = {k: v for k, v in settings.dict().items() if v is not None}
    current.update(patch)

    await db.execute(
        update(Group).where(Group.id == group_id).values(settings=current)
    )
    await db.commit()

    # Broadcast to WebSocket clients watching this group
    await manager.broadcast(group_id, {"event": "settings_updated", "settings": current})

    return {"ok": True, "settings": current}


@app.get("/api/groups/{group_id}/stats")
async def get_stats(
    group_id: int,
    days: int = 7,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from database.db import SpamLog
    from sqlalchemy import func
    since = datetime.utcnow() - timedelta(days=days)

    total_q = await db.execute(
        select(func.count(SpamLog.id))
        .where(SpamLog.group_id == group_id, SpamLog.detected_at >= since)
    )
    by_action_q = await db.execute(
        select(SpamLog.action_taken, func.count(SpamLog.id))
        .where(SpamLog.group_id == group_id, SpamLog.detected_at >= since)
        .group_by(SpamLog.action_taken)
    )
    by_method_q = await db.execute(
        select(SpamLog.detection_method, func.count(SpamLog.id))
        .where(SpamLog.group_id == group_id, SpamLog.detected_at >= since)
        .group_by(SpamLog.detection_method)
    )
    by_day_q = await db.execute(
        select(
            func.date(SpamLog.detected_at).label("day"),
            func.count(SpamLog.id).label("count")
        )
        .where(SpamLog.group_id == group_id, SpamLog.detected_at >= since)
        .group_by(func.date(SpamLog.detected_at))
        .order_by(func.date(SpamLog.detected_at))
    )

    return {
        "total": total_q.scalar(),
        "by_action": dict(by_action_q.all()),
        "by_method": dict(by_method_q.all()),
        "by_day": [{"day": str(row.day), "count": row.count} for row in by_day_q],
    }


@app.get("/api/groups/{group_id}/spam-log")
async def get_spam_log(
    group_id: int,
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from database.db import SpamLog
    result = await db.execute(
        select(SpamLog)
        .where(SpamLog.group_id == group_id)
        .order_by(SpamLog.detected_at.desc())
        .limit(limit)
    )
    logs = result.scalars().all()
    return [
        {
            "id": l.id,
            "user_id": l.user_id,
            "username": l.username,
            "message": l.message_text[:200],
            "score": round(l.spam_score, 2),
            "method": l.detection_method,
            "action": l.action_taken,
            "detected_at": l.detected_at.isoformat(),
        }
        for l in logs
    ]


@app.get("/api/groups/{group_id}/phrases")
async def get_phrases(
    group_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from database.db import SpamPhrase
    result = await db.execute(
        select(SpamPhrase)
        .where(SpamPhrase.group_id == group_id)
        .order_by(SpamPhrase.added_at.desc())
    )
    phrases = result.scalars().all()
    return [
        {
            "id": p.id,
            "phrase": p.phrase,
            "is_regex": p.is_regex,
            "weight": p.weight,
            "hit_count": p.hit_count,
            "added_at": p.added_at.isoformat(),
        }
        for p in phrases
    ]


@app.post("/api/groups/{group_id}/phrases")
async def add_phrase(
    group_id: int,
    data: SpamPhraseCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from database.db import SpamPhrase
    phrase = SpamPhrase(
        group_id=group_id,
        phrase=data.phrase,
        is_regex=data.is_regex,
        weight=data.weight,
        added_by=current_user["user_id"],
    )
    db.add(phrase)
    await db.commit()
    return {"ok": True, "id": phrase.id}


@app.delete("/api/groups/{group_id}/phrases/{phrase_id}")
async def delete_phrase(
    group_id: int,
    phrase_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from database.db import SpamPhrase
    from sqlalchemy import delete as sql_delete
    await db.execute(
        sql_delete(SpamPhrase)
        .where(SpamPhrase.id == phrase_id, SpamPhrase.group_id == group_id)
    )
    await db.commit()
    return {"ok": True}


@app.get("/api/groups/{group_id}/members")
async def get_members(
    group_id: int,
    search: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from database.db import GroupMember
    q = select(GroupMember).where(GroupMember.group_id == group_id)
    if search:
        q = q.where(GroupMember.username.ilike(f"%{search}%"))
    q = q.order_by(GroupMember.last_seen.desc()).limit(100)
    result = await db.execute(q)
    members = result.scalars().all()
    return [
        {
            "user_id": m.user_id,
            "username": m.username,
            "full_name": m.full_name,
            "warnings": m.warnings,
            "message_count": m.message_count,
            "is_whitelisted": m.is_whitelisted,
            "is_blacklisted": m.is_blacklisted,
            "is_muted": m.is_muted,
            "is_shadowbanned": m.is_shadowbanned,
            "joined_at": m.joined_at.isoformat(),
            "last_seen": m.last_seen.isoformat(),
        }
        for m in members
    ]


# ── WebSocket ──────────────────────────────────────────────────────────────────

@app.websocket("/ws/{group_id}")
async def websocket_endpoint(websocket: WebSocket, group_id: int, token: str = ""):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except Exception:
        await websocket.close(code=4001)
        return

    await manager.connect(websocket, group_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, group_id)


# ── Startup ────────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    from database.db import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("API server started")
