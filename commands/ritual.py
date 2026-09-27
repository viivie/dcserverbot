"""The /ritual gacha command and its weighted ritual results."""

from __future__ import annotations

import asyncio
import random
from typing import Any, TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from commands.context import CommandContext


EMBED_COLOR = 0xE7A0B4


OUTCOMES = ("4抓", "3抓", "平局", "3跑", "4跑")
SITUATION_TABLE = (
    ("普通", (25, 15, 35, 20, 5)),
    ("公正", (20, 20, 20, 20, 20)),
    ("屠夫變強", (35, 20, 30, 10, 5)),
    ("人類變強", (15, 10, 30, 25, 20)),
)


def draw_ritual(mode: str) -> str:
    """Draw one next-match outcome using the selected situation's weights."""
    for situation, weights in SITUATION_TABLE:
        if situation == mode:
            return random.choices(OUTCOMES, weights=weights, k=1)[0]
    raise ValueError(f"未知的儀式模式：{mode}")


def _result_embed(
    discord_module: Any,
    actor: Any,
    target: str,
    mode: str,
    outcome: str,
) -> Any:
    embed = discord_module.Embed(
        title="🔮 神秘儀式預測結果 🔮",
        description=(
            f"{actor.mention} 為「{target}」進行神秘儀式，\n"
            "預測下一場的結果。"
        ),
        color=EMBED_COLOR,
    )
    embed.add_field(
        name="預測情況",
        value=mode,
        inline=True,
    )
    embed.add_field(
        name="下一場結果",
        value=outcome,
        inline=False,
    )
    embed.set_footer(text="願芙帽的祝福與你同在")
    return embed


def _animation_embed(
    discord_module: Any,
    actor: Any,
    target: str,
    mode: str,
    status: str,
    progress: str,
) -> Any:
    embed = discord_module.Embed(
        title="🔮 神秘儀式進行中 🔮",
        description=(
            f"{actor.mention} 正在為「{target}」\n"
            "進行神秘儀式，預測下一場的結果……"
        ),
        color=EMBED_COLOR,
    )
    embed.add_field(name="儀式狀態", value=status, inline=False)
    embed.add_field(name="儀式模式", value=mode, inline=True)
    embed.add_field(name="進度", value=progress, inline=True)
    embed.set_footer(text="請稍候，請稍候，偉大的芙帽正在揭開命運的一角")
    return embed


def register_ritual(
    tree: Any,
    discord_module: Any,
    app_commands: Any,
    context: CommandContext,
) -> None:
    """Register the /ritual weighted draw command."""

    @tree.command(name="ritual", description="進行神秘儀式，預測某人下一場的結果")
    @app_commands.guild_only()
    @app_commands.describe(
        target="輸入名字或稱號",
        mode="選擇儀式模式",
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="普通", value="普通"),
            app_commands.Choice(name="公正", value="公正"),
            app_commands.Choice(name="屠夫變強", value="屠夫變強"),
            app_commands.Choice(name="人類變強", value="人類變強"),
        ]
    )
    async def ritual(
        interaction: Any,
        target: str,
        mode: app_commands.Choice[str],
    ) -> None:
        target = " ".join(target.split())[:80] or "神秘對象"
        mode_name = mode.value
        await interaction.response.defer()
        for status, progress, delay in (
            ("請稍候，請稍候，偉大的芙帽正在喚醒沉睡的神性……", "▰▱▱▱▱", 0.45),
            ("請稍候，請稍候，至高的芙帽正在召回散落的星辰……", "▰▰▱▱▱", 0.55),
            ("請稍候，請稍候，偉大的芙帽正在窺視時空的因果……", "▰▰▰▱▱", 0.55),
            ("請稍候，請稍候，至高的存在正在裁定命運的分歧……", "▰▰▰▰▱", 0.65),
            ("請稍候，請稍候，偉大的芙帽正在揭開命運的一角……", "▰▰▰▰▰", 0.7),
        ):
            await interaction.edit_original_response(
                content=None,
                embed=_animation_embed(
                    discord_module,
                    interaction.user,
                    target,
                    mode_name,
                    status,
                    progress,
                ),
            )
            await asyncio.sleep(delay)

        outcome = draw_ritual(mode_name)
        await interaction.edit_original_response(
            content=None,
            embed=_result_embed(
                discord_module,
                interaction.user,
                target,
                mode_name,
                outcome,
            ),
        )
