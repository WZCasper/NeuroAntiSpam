#!/usr/bin/env python3
"""
NeuroAntiSpam - Auto-update global spam phrases database.
Runs via GitHub Actions scheduled job.
"""

import json
import os
import sys
from pathlib import Path

# ── Built-in community spam phrases (always up to date) ──────────────────────

GLOBAL_SPAM_PHRASES = [
    # Russian spam
    {"phrase": r"заработ(ок|ать|ай) (от|до) \d+", "weight": 1.0, "is_regex": True},
    {"phrase": r"пассивн\w+ доход", "weight": 0.9, "is_regex": True},
    {"phrase": r"инвест\w+ (проект|фонд|платформ|программ)", "weight": 0.95, "is_regex": True},
    {"phrase": r"крипт\w+ (биржа|проект|монет)", "weight": 0.85, "is_regex": True},
    {"phrase": r"купить (закладк|товар|вещество)", "weight": 1.0, "is_regex": True},
    {"phrase": r"казино онлайн", "weight": 1.0, "is_regex": False},
    {"phrase": r"ставки на спорт", "weight": 0.9, "is_regex": False},
    {"phrase": r"онлифанс", "weight": 0.95, "is_regex": False},
    {"phrase": r"пиши (в лс|в личку|в дм|в директ)", "weight": 0.9, "is_regex": True},
    {"phrase": r"подпишись на (наш|мой) канал", "weight": 0.85, "is_regex": True},
    {"phrase": r"бесплатн\w+ крипт", "weight": 0.9, "is_regex": True},
    {"phrase": r"(работа|подработка) (из дома|онлайн|удалённо).{0,30}(без вложений|\d+ в день|\d+ в месяц)", "weight": 0.95, "is_regex": True},
    {"phrase": r"нарко(тик|вещество)|мефедрон|амфетамин|кокаин|героин", "weight": 1.0, "is_regex": True},
    {"phrase": r"\d+% в (день|неделю|месяц)", "weight": 0.85, "is_regex": True},
    {"phrase": r"только (сегодня|сейчас).{0,20}(скидк|акци|бесплатн)", "weight": 0.8, "is_regex": True},
    {"phrase": r"взлом (аккаунт|страниц)", "weight": 0.95, "is_regex": True},
    {"phrase": r"продаю (аккаунт|базу|слив)", "weight": 0.9, "is_regex": True},
    {"phrase": r"розыгрыш (айфон|денег|призов).{0,30}(подпишись|репост)", "weight": 0.9, "is_regex": True},

    # English spam
    {"phrase": r"earn \$?\d+ (per day|daily|a day)", "weight": 0.95, "is_regex": True},
    {"phrase": r"(passive income|financial freedom).{0,30}(join|click|dm)", "weight": 0.9, "is_regex": True},
    {"phrase": r"(crypto|bitcoin|btc).{0,30}(x\d+|guaranteed|profit)", "weight": 0.85, "is_regex": True},
    {"phrase": r"dm me for (details|info|opportunity)", "weight": 0.85, "is_regex": True},
    {"phrase": r"limited (time|offer|slots?)", "weight": 0.7, "is_regex": True},
    {"phrase": r"(click|tap).{0,15}link in (bio|description)", "weight": 0.85, "is_regex": True},
    {"phrase": r"18\+ (content|channel|group)", "weight": 0.9, "is_regex": True},
    {"phrase": r"onlyfans\.com", "weight": 1.0, "is_regex": False},
    {"phrase": r"investment (platform|fund|opportunity)", "weight": 0.85, "is_regex": True},
    {"phrase": r"(free|win).{0,20}(iphone|gift card|money)", "weight": 0.85, "is_regex": True},
    {"phrase": r"(buy|get).{0,15}(followers|subscribers|likes)", "weight": 0.95, "is_regex": True},

    # Links / Telegram spam
    {"phrase": r"t\.me/joinchat/", "weight": 0.85, "is_regex": True},
    {"phrase": r"t\.me/\+[A-Za-z0-9]{10,}", "weight": 0.85, "is_regex": True},
    {"phrase": r"@[a-z0-9_]{5,}bot\b", "weight": 0.6, "is_regex": True},
]

def main():
    out_path = Path("database/global_spam_phrases.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Write the updated phrases
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(GLOBAL_SPAM_PHRASES, f, ensure_ascii=False, indent=2)

    print(f"✅ Updated {len(GLOBAL_SPAM_PHRASES)} global spam phrases → {out_path}")

if __name__ == "__main__":
    main()
