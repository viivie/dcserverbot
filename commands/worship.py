"""Worship rules, formatting helpers, and the /worship slash command."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import discord

from components_v2 import v2_view_from_embed
from config import TARGET_USER_ID

if TYPE_CHECKING:
    from commands.context import CommandContext

TAIPEI = timezone(timedelta(hours=8))
EMBED_COLOR = 0xE7A0B4
EMBED_TITLE = "✨ 虔誠的膜拜 ✨"
EMBED_FOOTER = "芙帽教徒招募中 | 每日 00:00 重置 (UTC+8)"
LOGGER = logging.getLogger("fumao-worship-bot")


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


async def resolve_worship_target_avatar(
    interaction: Any,
    context: CommandContext,
) -> tuple[str, str | None]:
    """Resolve the configured target through discord.py before REST fallback."""
    target_id = TARGET_USER_ID
    guild = getattr(interaction, "guild", None)
    if guild is not None:
        target = guild.get_member(int(target_id))
        if target is None:
            try:
                target = await guild.fetch_member(int(target_id))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                target = None
        if target is not None:
            return target_id, str(target.display_avatar.url)

    client = getattr(interaction, "client", None)
    if client is not None:
        try:
            target = await client.fetch_user(int(target_id))
        except (discord.NotFound, discord.HTTPException):
            target = None
        if target is not None:
            return target_id, str(target.display_avatar.url)

    return target_id, (
        await asyncio.to_thread(
            context.discord_api.resolve_target,
            str(getattr(interaction, "guild_id", None)),
        )
    )[1]


def register_worship(tree: Any, discord: Any, app_commands: Any, context: CommandContext) -> None:
    """Register the /worship command using the worship rules in this module."""

    @tree.command(name="worship", description="向芙帽姐姐大人獻上誠摯的敬意")
    @app_commands.guild_only()
    @app_commands.describe(tribute_percent="獻祭百分比，1 到 10，預設為 1")
    async def worship(interaction: Any, tribute_percent: int = 1) -> None:
        if not 1 <= tribute_percent <= 10:
            await interaction.response.send_message(
                "獻祭百分比必須介於 1 到 10。",
                ephemeral=True,
            )
            return

        user = interaction.user
        user_id = str(user.id)
        raw_name = getattr(user, "nick", None) or getattr(user, "global_name", None) or user.name
        display_name = sanitize_display_name(raw_name)
        receipt = await asyncio.to_thread(
            context.store.apply_worship,
            f"discord:{user_id}",
            display_name,
            tribute_percent,
        )
        if not receipt["counted"]:
            if receipt["reason"] == "insufficient_funds":
                content = (
                    f"你的芙帽幣不足以進行 {tribute_percent}% 獻祭。\n"
                    f"目前餘額：`{receipt['balance']:,}` 芙帽幣，最少需要扣除 `100` 芙帽幣。"
                )
            else:
                content = (
                    f"今天已經獻過敬意了。目前連續 {day_label(receipt['streak'])}，"
                    f"累計 {count_label(receipt['total'])}。台北時間 00:00 後再來。"
                )
            await interaction.response.send_message(content, ephemeral=True)
            return

        try:
            await interaction.response.defer()
        except discord.NotFound:
            # Discord interactions expire after a short window. This can
            # happen after a reconnect or when an old interaction is retried.
            return
        target_id, avatar_url = await resolve_worship_target_avatar(interaction, context)

        mentions = [target_id, user_id] if target_id else [user_id]
        embed = discord.Embed(title=EMBED_TITLE, description=worship_line(display_name), color=EMBED_COLOR)
        embed.add_field(name="全世界累計膜拜次數", value=count_label(receipt["total"]), inline=True)
        embed.add_field(name="當前連續天數", value=day_label(receipt["streak"]), inline=True)
        embed.add_field(
            name="本次獻祭",
            value="\n".join(
                [
                    f"比例：**{tribute_percent}%**",
                    f"扣除：**{receipt['tribute_amount']:,}** 芙帽幣",
                    *(
                        ["PvP 開啟加成：**×1.4**"]
                        if float(receipt.get("pvp_chance_multiplier", 1.0)) > 1.0
                        else []
                    ),
                ]
            ),
            inline=True,
        )
        embed.add_field(
            name="✨ 芙帽顯靈 ✨",
            value=(
                f"芙帽降下了恩賜，獲得 **{receipt['crystals_reward']}** 水晶！"
                if receipt["crystals_reward"]
                else "芙帽未被你的奉獻吸引到，或許下次可以獻上更多"
            ),
            inline=True,
        )
        embed.add_field(
            name="目前芙帽幣餘額",
            value=f"**{receipt['balance']:,}** 芙帽幣",
            inline=True,
        )
        embed.set_footer(text=EMBED_FOOTER)
        if avatar_url:
            embed.set_image(url=avatar_url)
        await interaction.edit_original_response(
            view=v2_view_from_embed(
                embed,
                content=" ".join(f"<@{value}>" for value in mentions),
            ),
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False, replied_user=False
            ),
        )
