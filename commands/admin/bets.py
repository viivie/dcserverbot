"""Bet creation, betting, and resolution helpers for prefix commands."""

from __future__ import annotations

import re
import time
from typing import Any

import discord

from components_v2 import v2_view_from_embed


FUMAO_COIN = "<:FumaoCoin:1554060935725973554>"
MAX_OPTIONS = 5
MAX_DURATION_SECONDS = 30 * 24 * 60 * 60
DURATION_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd])\s*$", re.IGNORECASE)


def _format_odds(value: float) -> str:
    return f"×{value:.2f}"


def _parse_duration(value: str) -> int:
    match = DURATION_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError("時間格式請使用例如 `30m`、`2h` 或 `1d`")
    number = float(match.group(1))
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    seconds = int(number * units[match.group(2).lower()])
    if seconds < 1 or seconds > MAX_DURATION_SECONDS:
        raise ValueError("下注時間必須介於 1 秒與 30 天之間")
    return seconds


def _parse_options(value: str) -> list[tuple[str, float]]:
    options: list[tuple[str, float]] = []
    for raw_option in re.split(r"[,\n\s]+", value.strip()):
        if not raw_option:
            continue
        if ":" not in raw_option and "：" not in raw_option:
            raise ValueError("狀況格式應為 `狀況:倍率`，例如 `4抓:2.5`")
        name, raw_odds = re.split(r"[:：]", raw_option, maxsplit=1)
        name = name.strip()
        if not name or name.casefold() == "return":
            raise ValueError("狀況名稱不可空白或使用 `return`")
        try:
            odds = float(raw_odds)
        except ValueError as error:
            raise ValueError(f"狀況 `{name}` 的倍率不是有效數字") from error
        if odds <= 0 or odds > 1_000_000:
            raise ValueError("倍率必須大於 0 且不可超過 1,000,000")
        if any(existing_name == name for existing_name, _ in options):
            raise ValueError(f"狀況 `{name}` 重複了")
        options.append((name[:40], odds))

    if not 2 <= len(options) <= MAX_OPTIONS:
        raise ValueError("賭盤必須設定 2 到 5 個狀況")
    return options


def _bet_embed(
    title: str,
    content: str,
    options: list[tuple[str, float]],
    expires_at: int,
    *,
    resolved: str | None = None,
) -> discord.Embed:
    if resolved is None:
        status = "🟢 開放下注"
    elif resolved.casefold() == "return":
        status = "↩️ 已退款"
    else:
        status = f"🏁 結果：{resolved}"
    embed = discord.Embed(
        title=f"🎲 {title}",
        description=(
            f"{content}\n\n"
            f"{status}\n"
            f"截止時間：<t:{expires_at // 1000}:F>"
        ),
        color=0xE7A0B4 if resolved is None else 0x95A5A6,
    )
    embed.add_field(
        name="下注狀況與倍率",
        value="\n".join(
            f"{index}. **{name}**　{_format_odds(odds)}"
            for index, (name, odds) in enumerate(options, start=1)
        ),
        inline=False,
    )
    embed.set_footer(text="按下狀況按鈕後，會以私人表單輸入下注金額。單位：芙帽幣")
    return embed


class BetCreateModal(discord.ui.Modal, title="建立賭盤"):
    duration = discord.ui.TextInput(
        label="下注持續時間",
        placeholder="例如：30m、2h、1d",
        max_length=20,
    )
    title_input = discord.ui.TextInput(
        label="賭盤標題",
        max_length=100,
    )
    content_input = discord.ui.TextInput(
        label="賭盤內容",
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )
    options_input = discord.ui.TextInput(
        label="狀況與倍率",
        placeholder="例如：4抓:2.5 3抓:3.0 平局:4.0",
        max_length=1000,
    )

    def __init__(self, store: Any, channel: Any, guild_id: str) -> None:
        super().__init__()
        self.store = store
        self.channel = channel
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            duration_seconds = _parse_duration(str(self.duration.value))
            title = " ".join(str(self.title_input.value).split())
            content = str(self.content_input.value).strip()
            options = _parse_options(str(self.options_input.value))
            if not title or not content:
                raise ValueError("賭盤標題與內容不可空白")
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return

        created_at = int(time.time() * 1000)
        expires_at = created_at + duration_seconds * 1000
        bet_view = BetOpenView(self.store, title, content, options, expires_at)
        try:
            message = await self.channel.send(
                view=v2_view_from_embed(
                    _bet_embed(title, content, options, expires_at),
                    legacy_view=bet_view,
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            bet_view.message_id = str(message.id)
            await self.store_create(
                str(message.id),
                created_at,
                expires_at,
                title,
                content,
                options,
            )
        except Exception:
            try:
                await message.delete()
            except (UnboundLocalError, discord.HTTPException):
                pass
            await interaction.response.send_message("建立賭盤失敗，請稍後再試。", ephemeral=True)
            return

        await interaction.response.send_message(
            f"賭盤已建立，訊息 ID：`{message.id}`",
            ephemeral=True,
        )

    async def store_create(
        self,
        message_id: str,
        created_at: int,
        expires_at: int,
        title: str,
        content: str,
        options: list[tuple[str, float]],
    ) -> None:
        import asyncio

        await asyncio.to_thread(
            self.store.create_bet,
            message_id,
            self.guild_id,
            str(self.channel.id),
            title,
            content,
            created_at,
            expires_at,
            options,
        )


class BetSetupView(discord.ui.View):
    def __init__(self, store: Any, channel: Any, guild_id: str) -> None:
        super().__init__(timeout=300)
        self.store = store
        self.channel = channel
        self.guild_id = guild_id

    @discord.ui.button(label="建立賭盤", style=discord.ButtonStyle.primary)
    async def create_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(
            BetCreateModal(self.store, self.channel, self.guild_id)
        )


class BetAmountModal(discord.ui.Modal, title="下注確認"):
    amount = discord.ui.TextInput(
        label="下注芙帽幣數量",
        placeholder="請輸入正整數，例如：500",
        max_length=20,
    )

    def __init__(self, store: Any, message_id: str, option_name: str) -> None:
        super().__init__()
        self.store = store
        self.message_id = message_id
        self.option_name = option_name

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            amount = int(str(self.amount.value).replace(",", ""))
            if amount < 1:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("下注數量必須是大於 0 的整數。", ephemeral=True)
            return

        import asyncio

        try:
            result = await asyncio.to_thread(
                self.store.place_bet,
                self.message_id,
                str(interaction.user.id),
                self.option_name,
                amount,
                int(time.time() * 1000),
            )
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return

        embed = discord.Embed(
            title="✅ 下注成功",
            description=(
                f"狀況：**{self.option_name}**\n"
                f"下注：**{amount:,}** {FUMAO_COIN} 芙帽幣\n"
                f"倍率：**{_format_odds(result['odds'])}**\n"
                f"剩餘餘額：**{result['balance']:,}** {FUMAO_COIN} 芙帽幣"
            ),
            color=0x2ECC71,
        )
        await interaction.response.send_message(
            view=v2_view_from_embed(embed),
            ephemeral=True,
        )


class BetOpenView(discord.ui.View):
    def __init__(
        self,
        store: Any,
        title: str,
        content: str,
        options: list[tuple[str, float]],
        expires_at: int,
    ) -> None:
        super().__init__(timeout=None)
        self.store = store
        self.title = title
        self.content = content
        self.options = options
        self.expires_at = expires_at
        self.message_id: str | None = None
        for option_name, odds in options:
            button = discord.ui.Button(
                label=f"{option_name} {_format_odds(odds)}",
                style=discord.ButtonStyle.primary,
            )
            button.callback = self._option_callback(option_name)
            self.add_item(button)

    def _option_callback(self, option_name: str):
        async def callback(interaction: discord.Interaction) -> None:
            if self.message_id is None:
                await interaction.response.send_message("賭盤尚未準備完成。", ephemeral=True)
                return
            if int(time.time() * 1000) >= self.expires_at:
                await interaction.response.send_message("這個賭盤已經截止下注。", ephemeral=True)
                return
            await interaction.response.send_modal(
                BetAmountModal(self.store, self.message_id, option_name)
            )

        return callback


def setup_bet_card(store: Any, channel: Any, guild_id: str) -> discord.ui.View:
    embed = discord.Embed(
        title="🎲 建立賭盤",
        description="按下下方按鈕後，會以私人表單填寫賭盤資料。",
        color=0xE7A0B4,
    )
    return v2_view_from_embed(
        embed,
        legacy_view=BetSetupView(store, channel, guild_id),
    )


async def resolve_bet_message(
    message: discord.Message,
    store: Any,
    message_id: str,
    outcome: str,
) -> discord.Embed:
    import asyncio

    result = await asyncio.to_thread(
        store.resolve_bet,
        message_id,
        outcome,
        int(time.time() * 1000),
    )
    bet = await asyncio.to_thread(store.bet_details, message_id)
    if bet is None:
        raise ValueError("找不到這個賭盤")

    resolved_embed = _bet_embed(
        bet["title"],
        bet["content"],
        bet["options"],
        bet["expires_at"],
        resolved=result["outcome"],
    )
    if result["outcome"].casefold() == "return":
        resolved_embed.add_field(
            name="結算結果",
            value=f"已退還 **{result['refunded']:,}** {FUMAO_COIN} 芙帽幣。",
            inline=False,
        )
    else:
        resolved_embed.add_field(
            name="結算結果",
            value=(
                f"中獎人數：**{result['winners']}**\n"
                f"派發獎金：**{result['paid']:,}** {FUMAO_COIN} 芙帽幣。"
            ),
            inline=False,
        )
    try:
        target = await message.channel.fetch_message(int(message_id))
        await target.edit(view=v2_view_from_embed(resolved_embed))
    except (discord.HTTPException, ValueError):
        pass
    return resolved_embed
