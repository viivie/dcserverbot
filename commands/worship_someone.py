"""The /worship_someone slash command."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord

if TYPE_CHECKING:
    from commands.context import CommandContext


EMBED_COLOR = 0xE7A0B4
EMBED_TITLE = "✨ 虔誠的膜拜 ✨"
EMBED_FOOTER = "向特定的人獻上誠摯的敬意"


def register_worship_someone(
    tree: Any,
    discord_module: Any,
    app_commands: Any,
    context: CommandContext,
) -> None:
    """Register /worship_someone without reading or writing worship data."""

    @tree.command(
        name="worship_someone",
        description="向特定人士獻上誠摯的敬意",
    )
    @app_commands.guild_only()
    @app_commands.describe(target="要膜拜的對象")
    async def worship_someone(
        interaction: Any,
        target: discord.Member,
    ) -> None:
        actor = interaction.user
        embed = discord_module.Embed(
            title=EMBED_TITLE,
            description=(
                f"{actor.mention} 向 {target.mention} "
                "獻上了誠摯的敬意！"
            ),
            color=EMBED_COLOR,
        )
        embed.set_image(url=str(target.display_avatar.url))
        embed.set_footer(text=EMBED_FOOTER)

        await interaction.response.send_message(
            embed=embed,
            allowed_mentions=discord_module.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
                replied_user=False,
            ),
        )
