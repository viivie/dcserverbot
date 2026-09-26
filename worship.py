"""Worship-specific rules and text formatting."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

TAIPEI = timezone(timedelta(hours=8))
EMBED_COLOR = 0xE7A0B4
EMBED_TITLE = "✨ 虔誠的膜拜 ✨"
EMBED_FOOTER = "芙帽教徒招募中 | 每日 00:00 重置 (UTC+8)"


def taipei_today() -> str:
    return datetime.now(TAIPEI).date().isoformat()


def previous_date(day: str) -> str:
    return (date.fromisoformat(day) - timedelta(days=1)).isoformat()


def next_streak(last_date: str | None, streak: int, today: str) -> tuple[int, bool]:
    if last_date == today:
        return max(streak, 1), False
    if last_date == previous_date(today):
        return streak + 1, True
    return 1, True


def visible_streak(last_date: str | None, streak: int, today: str) -> int:
    return streak if last_date in (today, previous_date(today)) else 0


def sanitize_display_name(raw: str) -> str:
    cleaned = re.sub(r"[\r\n\t]", " ", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:32] or "旅人"


def count_label(value: int) -> str:
    return f"{value:,} 次"


def day_label(value: int) -> str:
    return f"{value:,} 天"


def worship_line(display_name: str) -> str:
    return f"{sanitize_display_name(display_name)} 向最偉大最可愛的芙帽姐姐獻上了誠摯的敬意！"
