"""Worship rules, formatting helpers, and the /worship slash command."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

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


def register_worship(tree: Any, discord: Any, app_commands: Any, context: CommandContext) -> None:
    """Register the /worship command using the worship rules in this module."""

    @tree.command(name="worship", description="向最偉大最可愛的芙帽姐姐大人獻上誠摯的敬意")
    @app_commands.guild_only()
    async def worship(interaction: Any) -> None:
        user = interaction.user
        user_id = str(user.id)
        raw_name = getattr(user, "nick", None) or getattr(user, "global_name", None) or user.name
        display_name = sanitize_display_name(raw_name)
        receipt = await asyncio.to_thread(context.store.apply_worship, f"discord:{user_id}", display_name)
        if not receipt["counted"]:
            content = (
                f"今天已經獻過敬意了。目前連續 {day_label(receipt['streak'])}，"
                f"累計 {count_label(receipt['total'])}。台北時間 00:00 後再來。"
            )
            await interaction.response.send_message(content, ephemeral=True)
            return

        await interaction.response.defer()
        target_id, avatar_url = await asyncio.to_thread(
            context.discord_api.resolve_target, str(interaction.guild_id)
        )
        if target_id and interaction.guild:
            try:
                target_member = interaction.guild.get_member(int(target_id))
                if target_member is None:
                    target_member = await interaction.guild.fetch_member(int(target_id))
                if target_member is not None:
                    avatar_url = str(target_member.display_avatar.url)
                    await asyncio.to_thread(
                        context.store.save_target,
                        str(interaction.guild.id),
                        str(target_member.id),
                        avatar_url,
                        int(time.time() * 1000),
                    )
            except (discord.HTTPException, ValueError) as error:
                LOGGER.warning("could not fetch target avatar: %s", error)

        mentions = [target_id, user_id] if target_id else [user_id]
        embed = discord.Embed(title=EMBED_TITLE, description=worship_line(display_name), color=EMBED_COLOR)
        embed.add_field(name="累計膜拜次數", value=count_label(receipt["total"]), inline=True)
        embed.add_field(name="當前連續天數", value=day_label(receipt["streak"]), inline=True)
        embed.set_footer(text=EMBED_FOOTER)
        if avatar_url:
            embed.set_image(url=avatar_url)
        await interaction.edit_original_response(
            content=" ".join(f"<@{value}>" for value in mentions),
            embed=embed,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False, replied_user=False
            ),
        )
