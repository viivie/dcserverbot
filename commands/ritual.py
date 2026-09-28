"""The /ritual gacha command and its weighted ritual results."""

from __future__ import annotations

import asyncio
import random
from typing import Any, TYPE_CHECKING

import discord
from discord import app_commands as discord_app_commands

from components_v2 import v2_view_from_embed

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
    outcome: str,
) -> Any:
    embed = discord_module.Embed(
        title="🔮 偉大的存在接受了信徒的請求，完成了神秘儀式 🔮",
        description=(
            f"{actor.mention} 請求了芙帽預測了「{target}」的下一場對局結果\n"
            "偉大的芙帽完成了神秘儀式，並揭示了命運的結果……"
        ),
        color=EMBED_COLOR,
    )
    embed.add_field(
        name="下一場結果",
        value=outcome,
        inline=False,
    )
    embed.add_field(
        name="預測對象",
        value=target,
        inline=False,
    )
    embed.set_footer(text="神秘儀式已完成｜偉大的芙帽已揭示命運")
    return embed


def _animation_embed(
    discord_module: Any,
    actor: Any,
    target: str,
    status: str,
    progress: str,
) -> Any:
    embed = discord_module.Embed(
        title="🔮 神秘儀式進行中 🔮",
        description=(
            f"{actor.mention} 請求了芙帽預測了「{target}」的下一場對局結果\n"
            "芙帽正在進行神秘儀式，並嘗試預測下一場的結果……"
        ),
        color=EMBED_COLOR,
    )
    embed.add_field(name="儀式狀態", value=status, inline=False)
    embed.add_field(name="進度", value=progress, inline=True)
    embed.set_footer(text="偉大的芙帽正在揭開命運的一角")
    return embed


def register_ritual(
    tree: Any,
    discord_module: Any,
    app_commands: Any,
    context: CommandContext,
) -> None:
    """Register the /ritual weighted draw command."""

    @tree.command(name="神秘儀式", description="進行神秘儀式，預測某人下一場的結果")
    @app_commands.guild_only()
    @app_commands.describe(
        target="輸入名字或稱號",
        mode="選擇儀式模式，預設為正常",
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="正常", value="普通"),
            app_commands.Choice(name="絕對的公平", value="公正"),
            app_commands.Choice(name="命運偏向了屠夫", value="屠夫變強"),
            app_commands.Choice(name="命運偏向了人類", value="人類變強"),
        ]
    )
    async def ritual(
        interaction: Any,
        target: str,
        mode: discord_app_commands.Choice[str] = None,
    ) -> None:
        target = " ".join(target.split())[:80] or "神秘對象"
        mode_name = mode.value if mode is not None else "普通"
        await interaction.response.defer()
        # Create the initial card first, then immediately edit it again so
        # Discord displays the edited marker before the visible animation.
        await interaction.edit_original_response(
            view=v2_view_from_embed(
                _animation_embed(
                    discord_module,
                    interaction.user,
                    target,
                    "🛐 正在向芙帽祈禱，請求她揭示命運……",
                    "▱▱▱▱▱▱",
                )
            ),
        )
        for status, progress, delay in (
            ("🛐 正在向芙帽祈禱，請求她揭示命運……", "▰▱▱▱▱▱", 1.8),
            ("🔮 芙帽正在喚醒沉睡的神性……", "▰▰▱▱▱▱", 1),
            ("🌌 芙帽嘗試召回流落於多重宇宙的命運之星……", "▰▰▰▱▱▱", 1.2),
            ("👁️‍🗨️ 偉大的芙帽正在窺視時空，並從中干涉因果……", "▰▰▰▰▱▱", 1.5),
            ("⚖️ 至高的存在嘗試裁定命運的分歧……", "▰▰▰▰▰▱", 1.8),
            ("🌠 偉大的芙帽正在揭開命運的一角……", "▰▰▰▰▰▰", 2),
        ):
            await interaction.edit_original_response(
                view=v2_view_from_embed(
                    _animation_embed(
                        discord_module,
                        interaction.user,
                        target,
                        status,
                        progress,
                    )
                ),
            )
            await asyncio.sleep(delay)

        outcome = draw_ritual(mode_name)
        await interaction.edit_original_response(
            view=v2_view_from_embed(
                _result_embed(
                    discord_module,
                    interaction.user,
                    target,
                    outcome,
                )
            ),
        )
