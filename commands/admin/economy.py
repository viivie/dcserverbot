"""Administrative views for economy audit information."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import discord

from commands.economy import CURRENCY_EMOJIS
from components_v2 import v2_view_from_embed


UTC_PLUS_8 = timezone(timedelta(hours=8), name="UTC+8")
CURRENCY_LABELS = {
    "fumao_coins": "芙帽幣",
    "crystals": "水晶",
    "grace": "神恩",
}
CURRENCY_EMOJIS_BY_STORAGE_KEY = {
    "fumao_coins": CURRENCY_EMOJIS["FumaoCoin"],
    "crystals": CURRENCY_EMOJIS["Crystal"],
    "grace": CURRENCY_EMOJIS["grace"],
}


def money_log_view(user_id: str, logs: list[dict[str, Any]]) -> Any:
    """Build the private V2 card used by ``&money-log``."""
    embed = discord.Embed(
        title="💰 貨幣變動紀錄",
        description=(
            f"使用者：<@{user_id}>\n"
            "以下是最近 3 天的貨幣變動；超過 3 天的紀錄會自動刪除。"
        ),
        color=0xE7A0B4,
    )

    if not logs:
        embed.add_field(name="紀錄", value="目前沒有獲取紀錄。", inline=False)
    else:
        display_logs = logs[:10]
        lines: list[str] = []
        for item in display_logs:
            timestamp = datetime.fromtimestamp(
                int(item["created_at"]) / 1000,
                tz=timezone.utc,
            ).astimezone(UTC_PLUS_8)
            currency = str(item["currency"])
            label = CURRENCY_LABELS.get(currency, currency)
            emoji = CURRENCY_EMOJIS_BY_STORAGE_KEY.get(currency, "")
            amount = int(item["amount"])
            sign = "+" if amount > 0 else ""
            lines.append(
                f"`{timestamp:%m/%d %H:%M:%S}`｜{item['source']}｜"
                f"{sign}{amount:,} {emoji} {label}"
            )

        if len(logs) > len(display_logs):
            lines.append(f"…（還有 {len(logs) - len(display_logs)} 筆紀錄，請縮小查詢範圍或稍後再查）")
        embed.add_field(
            name=f"最近 {len(display_logs)} 筆紀錄",
            value="\n".join(lines)[:3600],
            inline=False,
        )

    embed.set_footer(text="時間為 UTC+8｜正數為增加，負數為扣除")
    return v2_view_from_embed(embed)
