"""
NeuroAntiSpam Configuration
All settings loaded from environment variables
"""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Config:
    # Telegram
    BOT_TOKEN: str = field(default_factory=lambda: os.environ["BOT_TOKEN"])
    BOT_USERNAME: str = field(default_factory=lambda: os.getenv("BOT_USERNAME", "NeuroAntiSpamBot"))

    # Database (SQLite by default, PostgreSQL in production)
    DATABASE_URL: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite+aiosqlite:///neuroantispam.db"))

    # AI / ML
    GEMINI_API_KEY: Optional[str] = field(default_factory=lambda: os.getenv("GEMINI_API_KEY"))
    USE_GEMINI: bool = field(default_factory=lambda: bool(os.getenv("GEMINI_API_KEY")))

    # Website
    WEBSITE_URL: str = field(default_factory=lambda: os.getenv("WEBSITE_URL", "https://neuroantispam.railway.app"))
    API_SECRET_KEY: str = field(default_factory=lambda: os.environ.get("API_SECRET_KEY", "change-me-in-production"))
    JWT_SECRET: str = field(default_factory=lambda: os.environ.get("JWT_SECRET", "change-me-in-production"))

    # GitHub (for shared spam database updates)
    GH_TOKEN: Optional[str] = field(default_factory=lambda: os.getenv("GH_TOKEN"))
    GH_REPO: str = field(default_factory=lambda: os.getenv("GH_REPO", "neuroantispam/spam-database"))

    # Spam detection defaults
    DEFAULT_SPAM_THRESHOLD: float = 0.75
    DEFAULT_MODE: str = "medium"  # soft / medium / hard
    MAX_WARNINGS: int = 3
    FLOOD_LIMIT: int = 5           # messages per window
    FLOOD_WINDOW: int = 10         # seconds
    NEW_USER_QUARANTINE_MSGS: int = 5
    CAPTCHA_TIMEOUT: int = 60      # seconds

    # Raid detection
    RAID_THRESHOLD: int = 10       # new members per minute
    RAID_WINDOW: int = 60          # seconds

    # Admin IDs (super admins who can manage all groups)
    SUPER_ADMINS: list = field(default_factory=lambda: [
        int(x) for x in os.getenv("SUPER_ADMINS", "").split(",") if x.strip()
    ])
