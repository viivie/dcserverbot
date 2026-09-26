"""The /worship slash command."""

from __future__ import annotations

import asyncio
import logging
import time

from commands.context import CommandContext
from worship import EMBED_COLOR, EMBED_FOOTER, EMBED_TITLE, count_label, day_label, sanitize_display_name, worship_line

LOGGER = logging.getLogger("fumao-worship-bot")


def register_worship(tree, discord, app_commands, context: CommandContext) -> None:
    @tree.command(name="worship", description="向最偉大最可愛的芙帽姐姐大人獻上誠摯的敬意")
    @app_commands.guild_only()
    async def worship(interaction) -> None:
        user = interaction.user
        user_id = str(user.id)
        raw_name = getattr(user, "nick", None) or getattr(user, "global_name", None) or user.name
        display_name = sanitize_display_name(raw_name)
        receipt = await asyncio.to_thread(context.store.apply_worship, f"discord:{user_id}", display_name)
        if not receipt["counted"]:
            content = f"今天已經獻過敬意了。目前連續 {day_label(receipt['streak'])}，累計 {count_label(receipt['total'])}。台北時間 00:00 後再來。"
            await interaction.response.send_message(content, ephemeral=True)
            return

        await interaction.response.defer()
        target_id, avatar_url = await asyncio.to_thread(context.discord_api.resolve_target, str(interaction.guild_id))
        if target_id and interaction.guild:
            try:
                target_member = interaction.guild.get_member(int(target_id))
                if target_member is None:
                    target_member = await interaction.guild.fetch_member(int(target_id))
                if target_member is not None:
                    avatar_url = str(target_member.display_avatar.url)
                    await asyncio.to_thread(context.store.save_target, str(interaction.guild.id), str(target_member.id), avatar_url, int(time.time() * 1000))
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
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False, replied_user=False),
        )
