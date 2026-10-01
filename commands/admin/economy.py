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


class MoneyLogView(discord.ui.View):
    def __init__(
        self,
        user_id: str,
        logs: list[dict[str, Any]],
        requester_id: str,
        page: int = 0,
    ) -> None:
        super().__init__(timeout=300)
        self.user_id = str(user_id)
        self.logs = logs
        self.requester_id = str(requester_id)
        self.page = max(0, int(page))
        page_count = max(1, (len(logs) + 9) // 10)
        self.page = min(self.page, page_count - 1)

        if self.page > 0:
            previous = discord.ui.Button(
                label="上一頁",
                style=discord.ButtonStyle.primary,
                custom_id="money-log-prev",
            )
            previous.callback = self._page_callback(self.page - 1)
            self.add_item(previous)
        if self.page + 1 < page_count:
            following = discord.ui.Button(
                label="下一頁",
                style=discord.ButtonStyle.primary,
                custom_id="money-log-next",
            )
            following.callback = self._page_callback(self.page + 1)
            self.add_item(following)

    def _page_callback(self, page: int):
        async def callback(interaction: discord.Interaction) -> None:
            if str(interaction.user.id) != self.requester_id:
                await interaction.response.send_message(
                    "這不是你的貨幣紀錄介面。",
                    ephemeral=True,
                )
                return
            try:
                await interaction.response.edit_message(
                    view=money_log_view(
                        self.user_id,
                        self.logs,
                        self.requester_id,
                        page,
                    )
                )
            except (discord.NotFound, discord.HTTPException):
                return

        return callback


def money_log_view(
    user_id: str,
    logs: list[dict[str, Any]],
    requester_id: str = "",
    page: int = 0,
) -> Any:
    """Build the V2 card used by ``&log`` with ten-entry pagination."""
    page_count = max(1, (len(logs) + 9) // 10)
    page = max(0, min(int(page), page_count - 1))
    display_logs = logs[page * 10:(page + 1) * 10]
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

        embed.add_field(
            name=f"最近 {len(display_logs)} 筆紀錄",
            value="\n".join(lines)[:3600],
            inline=False,
        )

    embed.set_footer(text=f"第 {page + 1} / {page_count} 頁｜時間為 UTC+8｜正數為增加，負數為扣除")
    return v2_view_from_embed(
        embed,
        legacy_view=MoneyLogView(user_id, logs, requester_id, page)
        if requester_id
        else None,
    )
