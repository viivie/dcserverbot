"""The economy check-in commands and sign-in level system."""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from commands.context import CommandContext


TAIPEI = timezone(timedelta(hours=8), name="UTC+8")
EMBED_COLOR = 0xE7A0B4
BASE_REWARD_MIN = 100
BASE_REWARD_MAX = 200
DAILY_BASE_REWARD = 1_000
QUICK_CHECKIN_GUILD_ID = 1512762043504267284
QUICK_CHECKIN_CHANNEL_ID = 1554087496898453514
ROBBERY_COOLDOWN_SECONDS = 1.0
CURRENCY_COOLDOWNS: dict[int, float] = {}
CURRENCY_EMOJIS = {
    "FumaoCoin": "<:FumaoCoin:1554060935725973554>",
    "YuzuCoin": "<:yuzucoin:1471758283403431947>",
    "Crystal": "<:Crystal:1554060934140403815>",
    "grace": "<:grace:1554060937244180542>",
}
CHECKIN_TITLE_EMOJI = "<:mura_excited:1429257164811407571>"
ROBBERY_ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "economy"


@dataclass(frozen=True)
class EconomyLevel:
    level: int
    coin_cost: int
    crystal_cost: int
    saved_hours: int
    hourly_multiplier: float
    daily_multiplier: float


# Values are copied from 芙帽教簽到等級系統換算表.xlsx. The sheet labels
# levels 21-30 as 8-17 days, so those saved-hour values are represented as
# 192-408 hours even though the displayed text in the sheet starts with 168.
LEVELS = (
    EconomyLevel(1, 0, 0, 1, 1.00, 1.00),
    EconomyLevel(2, 1_000, 0, 2, 1.02, 1.01),
    EconomyLevel(3, 1_200, 0, 3, 1.16, 1.08),
    EconomyLevel(4, 1_600, 0, 4, 1.54, 1.27),
    EconomyLevel(5, 2_500, 1, 5, 2.28, 1.64),
    EconomyLevel(6, 4_000, 2, 6, 3.50, 2.25),
    EconomyLevel(7, 6_900, 6, 8, 5.32, 3.16),
    EconomyLevel(8, 13_000, 11, 12, 7.86, 4.43),
    EconomyLevel(9, 24_000, 17, 18, 11.24, 6.12),
    EconomyLevel(10, 50_000, 26, 24, 15.58, 8.29),
    EconomyLevel(11, 110_000, 36, 36, 21.00, 11.00),
    EconomyLevel(12, 240_000, 49, 48, 27.62, 14.31),
    EconomyLevel(13, 540_000, 63, 72, 35.56, 18.28),
    EconomyLevel(14, 1_300_000, 79, 120, 44.94, 22.97),
    EconomyLevel(15, 3_300_000, 98, 168, 55.88, 28.44),
    EconomyLevel(16, 8_500_000, 120, 168, 68.50, 34.75),
    EconomyLevel(17, 23_000_000, 140, 168, 82.92, 41.96),
    EconomyLevel(18, 63_000_000, 170, 168, 99.26, 50.13),
    EconomyLevel(19, 180_000_000, 190, 168, 117.64, 59.32),
    EconomyLevel(20, 530_000_000, 220, 168, 138.18, 69.59),
    EconomyLevel(21, 1_600_000_000, 250, 192, 161.00, 81.00),
    EconomyLevel(22, 5_100_000_000, 290, 216, 186.22, 93.61),
    EconomyLevel(23, 17_000_000_000, 330, 240, 213.96, 107.48),
    EconomyLevel(24, 55_000_000_000, 360, 264, 244.34, 122.67),
    EconomyLevel(25, 190_000_000_000, 410, 288, 277.48, 139.24),
    EconomyLevel(26, 660_000_000_000, 450, 312, 313.50, 157.25),
    EconomyLevel(27, 2_400_000_000_000, 500, 336, 352.52, 176.76),
    EconomyLevel(28, 8_800_000_000_000, 540, 360, 394.66, 197.83),
    EconomyLevel(29, 33_000_000_000_000, 590, 384, 440.04, 220.52),
    EconomyLevel(30, 130_000_000_000_000, 650, 408, 488.78, 244.89),
)


def level_data(level: int) -> EconomyLevel:
    return LEVELS[max(1, min(int(level), len(LEVELS))) - 1]


def next_level(account: dict[str, Any]) -> EconomyLevel | None:
    current = int(account["level"])
    return LEVELS[current] if current < len(LEVELS) else None


def can_upgrade(account: dict[str, Any]) -> bool:
    target = next_level(account)
    return bool(
        target
        and int(account["fumao_coins"]) >= target.coin_cost
        and int(account["crystals"]) >= target.crystal_cost
    )


def _number(value: int | float) -> str:
    return f"{value:,}"


def _multiplier(value: float) -> str:
    return f"×{value:.2f}"


def _embed_divider(*values: str) -> str:
    width = max((len(value) for value in values), default=16) + 8
    return "─" * max(24, min(64, width))


def _currency_emoji(guild: discord.Guild | None, name: str) -> str:
    if name in CURRENCY_EMOJIS:
        return CURRENCY_EMOJIS[name]
    if guild is not None:
        for emoji in guild.emojis:
            if emoji.name == name:
                return str(emoji)
    return f":{name}:"


def _period_time(now: datetime) -> str:
    period = "上午" if now.hour < 12 else "下午"
    hour = now.hour % 12 or 12
    return f"{period} {hour:02d}:{now.minute:02d}"


def _balance_line(account: dict[str, Any], guild: discord.Guild | None) -> str:
    coin = _currency_emoji(guild, "YuzuCoin")
    return (
        f"當前餘額：{_number(account['fumao_coins'])} {coin} 柚子幣．"
        f"簽到等級：Lv.{account['level']}"
    )


def _set_user_thumbnail(embed: Any, user: Any) -> None:
    avatar = getattr(getattr(user, "display_avatar", None), "url", None)
    if avatar:
        embed.set_thumbnail(url=str(avatar))


def _robbery_embed(
    discord_module: Any,
    guild: discord.Guild | None,
    account: dict[str, Any],
    amount: int,
    success: bool,
) -> tuple[Any, discord.File | None]:
    coin = _currency_emoji(guild, "FumaoCoin")
    if success:
        title = "🎉 搶劫成功！"
        description = (
            "幸運的，芙帽剛好不在神殿🎉🎉\n"
            "你們成功進入了芙帽教的地下金庫\n"
            f"並偷取到了`{amount:,}` {coin} 芙帽幣"
        )
        asset_name = "robbery_success.jpg"
        color = 0x2ECC71
    else:
        title = "⚡ 搶劫失敗！"
        description = (
            "噢不，芙帽降臨了神殿......\n"
            "並發現了你們搶劫的罪刑QQ\n"
            "偉大的芙帽降下了神罰⚡⚡⚡\n\n"
            f"您失去了`{amount:,}` {coin} 芙帽幣"
        )
        asset_name = "robbery_failure.png"
        color = 0xE74C3C

    embed = discord_module.Embed(title=title, description=description, color=color)
    embed.add_field(
        name="目前餘額",
        value=(
            f"{_number(account['fumao_coins'])} {coin} 芙帽幣．"
            f"今天 {_period_time(datetime.now(TAIPEI))}"
        ),
        inline=False,
    )
    asset_path = ROBBERY_ASSET_DIR / asset_name
    if not asset_path.is_file():
        return embed, None
    file = discord.File(asset_path, filename=asset_name)
    embed.set_image(url=f"attachment://{asset_name}")
    return embed, file


def _upgrade_embed(
    discord_module: Any,
    account: dict[str, Any],
    guild: discord.Guild | None,
    *,
    confirm: bool = False,
) -> Any:
    current = level_data(account["level"])
    target = next_level(account)
    coin = _currency_emoji(guild, "FumaoCoin")
    crystal = _currency_emoji(guild, "Crystal")
    title = (
        f"{'⚠️ 確認升級至' if confirm else '🛒 升級至'} Lv.{target.level}"
        if target
        else "已達最高等級"
    )

    embed = discord_module.Embed(title=title, color=EMBED_COLOR)
    if target is None:
        embed.description = "你已經達到最高簽到等級。"
        return embed

    embed.add_field(
        name="目前等級",
        value=f"Lv.{current.level}",
        inline=True,
    )
    embed.add_field(
        name="目標等級",
        value=f"Lv.{target.level}",
        inline=True,
    )
    embed.add_field(
        name="升級費用",
        value=(
            f"{coin} 芙帽幣：**{_number(target.coin_cost)}**\n"
            f"{crystal} 水晶：**{_number(target.crystal_cost)}**"
        ),
        inline=True,
    )
    embed.add_field(
        name="目前餘額",
        value=(
            f"{coin} 芙帽幣：**{_number(account['fumao_coins'])}** "
            f"{'✅' if account['fumao_coins'] >= target.coin_cost else '❌'}\n"
            f"{crystal} 水晶：**{_number(account['crystals'])}** "
            f"{'✅' if account['crystals'] >= target.crystal_cost else '❌'}"
        ),
        inline=True,
    )
    embed.add_field(
        name="升級後效益",
        value=(
            f"保存小時數：{current.saved_hours}h ➜ **{target.saved_hours}h**\n"
            f"每小時倍率：{_multiplier(current.hourly_multiplier)} ➜ **{_multiplier(target.hourly_multiplier)}**\n"
            f"每日倍率：{_multiplier(current.daily_multiplier)} ➜ **{_multiplier(target.daily_multiplier)}**"
        ),
        inline=False,
    )
    if confirm:
        embed.set_footer(text="請確認是否要支付費用並升級簽到等級。")
    else:
        embed.set_footer(text="確認有足夠資源後，可按下方按鈕升級。")
    return embed


def _checkin_embed(
    discord_module: Any,
    user: Any,
    guild: discord.Guild | None,
    account: dict[str, Any],
    kind: str,
) -> Any:
    coin = _currency_emoji(guild, "YuzuCoin")
    if not account.get("claimed"):
        if kind == "daily":
            description = "今天已經完成每日簽到，明天再來吧。"
        else:
            next_at = account.get("next_hourly_at")
            next_text = "稍後再試"
            if next_at:
                next_text = _period_time(datetime.fromtimestamp(next_at / 1000, tz=TAIPEI))
            description = f"每小時簽到還沒到時間，請於 {next_text} 後再試。"
        embed = discord_module.Embed(
            title="🕘 簽到尚未刷新",
            description=f"{description}\n\n{_balance_line(account, guild)}",
            color=0x95A5A6,
        )
        _set_user_thumbnail(embed, user)
        return embed

    base_reward = int(account["base_reward"])
    reward = int(account["reward"])
    multiplier = float(account["multiplier"])
    if kind == "hourly":
        accumulated = int(account["accumulated_hours"])
        accumulated_reward = base_reward * accumulated
        calculation_lines = [
            f"累積 {accumulated} 小時獎勵　　{_number(accumulated_reward)} 柚子幣",
            f"每小時倍率　　　　{_multiplier(multiplier)}",
        ]
    else:
        calculation_lines = [f"每日倍率　　　　{_multiplier(multiplier)}"]

    divider = _embed_divider(
        f"獲得 {reward} 柚子幣",
        *calculation_lines,
        f"合計 {reward} 柚子幣",
    )
    balance = (
        f"當前餘額：{_number(account['fumao_coins'])} {coin} 柚子幣．"
        f"簽到等級：Lv.{account['level']}"
    )
    description = "\n".join(
        [
            divider,
            f"獲得 **{_number(reward)}** {coin} 柚子幣",
            "",
            *calculation_lines,
            divider,
            f"合計　　　　　　　**{_number(reward)}** {coin} 柚子幣",
            divider,
            balance,
        ]
    )
    embed = discord_module.Embed(
        title=f"{CHECKIN_TITLE_EMOJI} {'每小時' if kind == 'hourly' else '每日'}簽到成功",
        description=description,
        color=EMBED_COLOR,
    )
    _set_user_thumbnail(embed, user)
    embed.set_footer(text="UTC+8")
    return embed


async def _claim_daily(context: CommandContext, user_id: int, now: datetime) -> dict[str, Any]:
    account_before = await asyncio.to_thread(
        context.store.economy_account,
        str(user_id),
    )
    random_base_reward = random.randint(DAILY_BASE_REWARD, DAILY_BASE_REWARD * 2)
    return await asyncio.to_thread(
        context.store.claim_daily,
        str(user_id),
        now.date().isoformat(),
        random_base_reward,
        level_data(account_before["level"]).daily_multiplier,
    )


async def _claim_hourly(
    context: CommandContext,
    user_id: int,
) -> dict[str, Any]:
    account_before = await asyncio.to_thread(
        context.store.economy_account,
        str(user_id),
    )
    level = level_data(account_before["level"])
    return await asyncio.to_thread(
        context.store.claim_hourly,
        str(user_id),
        int(time.time() * 1000),
        random.randint(BASE_REWARD_MIN, BASE_REWARD_MAX),
        level.saved_hours,
        level.hourly_multiplier,
    )


def _quick_checkin_embed(
    discord_module: Any,
    user: Any,
    guild: discord.Guild | None,
    daily: dict[str, Any],
    hourly: dict[str, Any],
    current_account: dict[str, Any],
) -> Any:
    coin = _currency_emoji(guild, "YuzuCoin")
    embed = discord_module.Embed(title="⚡ 快速簽到", color=EMBED_COLOR)
    _set_user_thumbnail(embed, user)

    if daily.get("claimed"):
        daily_value = (
            f"獲得 **{_number(daily['reward'])}** {coin} 柚子幣\n"
            f"每日倍率　　　　{_multiplier(float(daily['multiplier']))}\n"
            f"合計　　　　　　　**{_number(daily['reward'])}** {coin} 柚子幣"
        )
        daily_name = "每日簽到　成功"
    else:
        daily_value = "今天的每日獎勵已領取。"
        daily_name = "每日簽到　已完成"
    embed.add_field(name=daily_name, value=daily_value, inline=False)

    if hourly.get("claimed"):
        accumulated = int(hourly["accumulated_hours"])
        accumulated_reward = int(hourly["base_reward"]) * accumulated
        hourly_value = (
            f"獲得 **{_number(hourly['reward'])}** {coin} 柚子幣\n"
            f"累積 {accumulated} 小時獎勵　　{_number(accumulated_reward)} 柚子幣\n"
            f"每小時倍率　　　　{_multiplier(float(hourly['multiplier']))}\n"
            f"合計　　　　　　　**{_number(hourly['reward'])}** {coin} 柚子幣"
        )
        hourly_name = "每小時簽到　成功"
    else:
        next_at = hourly.get("next_hourly_at")
        next_text = "稍後"
        if next_at:
            next_text = _period_time(datetime.fromtimestamp(next_at / 1000, tz=TAIPEI))
        hourly_value = f"每小時獎勵尚未刷新，請於 {next_text} 後再試。"
        hourly_name = "每小時簽到　尚未刷新"
    embed.add_field(name=hourly_name, value=hourly_value, inline=False)
    embed.add_field(
        name="\u200b",
        value=_embed_divider(daily_value, hourly_value),
        inline=False,
    )

    received = sum(
        int(result.get("reward", 0))
        for result in (daily, hourly)
        if result.get("claimed")
    )
    received_text = (
        f"本次獲得 **{_number(received)}** {coin} 柚子幣\n"
        if received
        else "本次沒有新的柚子幣獎勵\n"
    )
    embed.add_field(
        name="簽到結果",
        value=(
            f"{received_text}"
            f"當前餘額：**{_number(current_account['fumao_coins'])}** {coin} 柚子幣．"
            f"簽到等級：Lv.{current_account['level']}\n"
            f"今天 {_period_time(datetime.now(TAIPEI))}"
        ),
        inline=False,
    )
    embed.set_footer(text="請遵守遊戲規則，以免遭到芙帽的制裁。")
    return embed


async def handle_quick_checkin(message: discord.Message, context: CommandContext) -> bool:
    """Automatically perform both check-ins in the dedicated quick-checkin channel."""
    if (
        message.author.bot
        or message.guild is None
        or message.guild.id != QUICK_CHECKIN_GUILD_ID
        or message.channel.id != QUICK_CHECKIN_CHANNEL_ID
    ):
        return False

    now = datetime.now(TAIPEI)
    daily, hourly = await asyncio.gather(
        _claim_daily(context, message.author.id, now),
        _claim_hourly(context, message.author.id),
    )
    current_account = await asyncio.to_thread(
        context.store.economy_account,
        str(message.author.id),
    )
    await message.channel.send(
        embed=_quick_checkin_embed(
            discord,
            message.author,
            message.guild,
            daily,
            hourly,
            current_account,
        ),
        allowed_mentions=discord.AllowedMentions.none(),
    )
    return True


class UpgradeView(discord.ui.View):
    def __init__(
        self,
        context: CommandContext,
        user_id: int,
        guild: discord.Guild | None,
        checkin_embed: Any,
    ) -> None:
        super().__init__(timeout=300)
        self.context = context
        self.user_id = user_id
        self.guild = guild
        self.checkin_embed = checkin_embed
        self._set_upgrade_button()

    def _set_upgrade_button(self) -> None:
        self.clear_items()
        button = discord.ui.Button(label="升級簽到等級", style=discord.ButtonStyle.primary)
        button.callback = self._show_confirmation
        self.add_item(button)

    def _set_confirmation_buttons(self) -> None:
        self.clear_items()
        confirm_button = discord.ui.Button(label="確認升級", style=discord.ButtonStyle.success)
        cancel_button = discord.ui.Button(label="取消", style=discord.ButtonStyle.secondary)
        confirm_button.callback = self._confirm_upgrade
        cancel_button.callback = self._cancel_upgrade
        self.add_item(confirm_button)
        self.add_item(cancel_button)

    async def _deny_other_user(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return False
        await interaction.response.send_message("這不是你的簽到升級卡片喔😡", ephemeral=True)
        return True

    async def _show_confirmation(self, interaction: discord.Interaction) -> None:
        # The public check-in card may belong to someone else. The private
        # upgrade screen always belongs to the person who clicked the button.
        clicked_user_id = interaction.user.id
        account = await asyncio.to_thread(
            self.context.store.economy_account,
            str(clicked_user_id),
        )
        if not can_upgrade(account):
            await interaction.response.send_message(
                embed=_upgrade_embed(discord, account, self.guild, confirm=False),
                ephemeral=True,
            )
            return

        private_view = UpgradeView(
            self.context,
            clicked_user_id,
            interaction.guild,
            None,
        )
        private_view._set_confirmation_buttons()
        await interaction.response.send_message(
            embed=_upgrade_embed(discord, account, interaction.guild, confirm=True),
            view=private_view,
            ephemeral=True,
        )

    async def _confirm_upgrade(self, interaction: discord.Interaction) -> None:
        if await self._deny_other_user(interaction):
            return
        account = await asyncio.to_thread(self.context.store.economy_account, str(self.user_id))
        target = next_level(account)
        if target is None:
            await interaction.response.edit_message(
                embed=discord.Embed(title="已達最高等級", color=EMBED_COLOR), view=None
            )
            self.stop()
            return

        result = await asyncio.to_thread(
            self.context.store.upgrade_economy,
            str(self.user_id),
            target.level,
            target.coin_cost,
            target.crystal_cost,
        )
        if result.get("upgraded"):
            embed = discord.Embed(
                title=f"✅ 簽到等級升級成功：Lv.{result['level']}",
                description=(
                    f"保存小時數：{level_data(target.level - 1).saved_hours}h ➜ **{target.saved_hours}h**\n"
                    f"每小時倍率：{_multiplier(level_data(target.level - 1).hourly_multiplier)} ➜ **{_multiplier(target.hourly_multiplier)}**\n"
                    f"每日倍率：{_multiplier(level_data(target.level - 1).daily_multiplier)} ➜ **{_multiplier(target.daily_multiplier)}**\n\n"
                    f"{_balance_line(result, self.guild)}"
                ),
                color=0x2ECC71,
            )
        else:
            embed = discord.Embed(
                title="❌ 升級失敗",
                description="目前餘額不足，或這個升級已經被其他操作完成。",
                color=0xE74C3C,
            )
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()

    async def _cancel_upgrade(self, interaction: discord.Interaction) -> None:
        if await self._deny_other_user(interaction):
            return
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="已取消升級",
                description="這次沒有扣除任何資源。",
                color=0x95A5A6,
            ),
            view=None,
        )
        self.stop()


def _attach_upgrade_view(
    context: CommandContext,
    interaction: Any,
    embed: Any,
    account: dict[str, Any],
) -> UpgradeView | None:
    return UpgradeView(context, interaction.user.id, interaction.guild, embed)


def register_economy(
    tree: Any,
    discord_module: Any,
    app_commands: Any,
    context: CommandContext,
) -> None:
    """Register /經濟 and its check-in and balance subcommands."""
    economy = app_commands.Group(name="經濟", description="芙帽幣與簽到經濟系統")

    @economy.command(name="每日簽到", description="每日簽到並獲得芙帽幣")
    @app_commands.guild_only()
    async def daily_check_in(interaction: Any) -> None:
        now = datetime.now(TAIPEI)
        account = await _claim_daily(context, interaction.user.id, now)
        embed = _checkin_embed(discord_module, interaction.user, interaction.guild, account, "daily")
        view = _attach_upgrade_view(context, interaction, embed, account)
        if view is None:
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message(embed=embed, view=view)

    @economy.command(name="每小時簽到", description="每小時簽到並獲得芙帽幣")
    @app_commands.guild_only()
    async def hourly_check_in(interaction: Any) -> None:
        account = await _claim_hourly(context, interaction.user.id)
        embed = _checkin_embed(discord_module, interaction.user, interaction.guild, account, "hourly")
        view = _attach_upgrade_view(context, interaction, embed, account)
        if view is None:
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message(embed=embed, view=view)

    @economy.command(name="搶芙帽教聖殿", description="嘗試搶劫芙帽教聖殿")
    @app_commands.guild_only()
    async def rob_fumao_temple(interaction: Any) -> None:
        now_monotonic = time.monotonic()
        cooldown_until = CURRENCY_COOLDOWNS.get(interaction.user.id, 0.0)
        if cooldown_until > now_monotonic:
            remaining = cooldown_until - now_monotonic
            await interaction.response.send_message(
                f"你使用指令太頻繁了，請等待 **{remaining:.1f} 秒** 後再試。",
                ephemeral=True,
            )
            return
        CURRENCY_COOLDOWNS[interaction.user.id] = (
            now_monotonic + ROBBERY_COOLDOWN_SECONDS
        )

        current_account = await asyncio.to_thread(
            context.store.economy_account,
            str(interaction.user.id),
        )
        if current_account["fumao_coins"] < 500:
            await interaction.response.send_message(
                "芙帽教的守衛拒絕讓你進入，你嘗試賄賂守衛，但你太窮了沒錢賄賂，"
                "於是還沒搶劫就被趕出聖殿大門外了QQ"
            )
            return

        success = random.random() < 0.10
        requested_amount = (
            random.randint(1_000, 10_000)
            if success
            else random.randint(100, 500)
        )
        account = await asyncio.to_thread(
            context.store.change_economy_currency,
            str(interaction.user.id),
            "fumao_coins",
            requested_amount if success else -requested_amount,
        )
        amount = (
            int(account["changed"])
            if success
            else abs(int(account["changed"]))
        )
        embed, file = _robbery_embed(
            discord_module,
            interaction.guild,
            account,
            amount,
            success,
        )
        if file is None:
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message(embed=embed, file=file)

    @economy.command(name="餘額", description="查看芙帽幣、水晶與神恩餘額")
    @app_commands.guild_only()
    async def balance(interaction: Any) -> None:
        account = await asyncio.to_thread(
            context.store.economy_account,
            str(interaction.user.id),
        )
        now = datetime.now(TAIPEI)
        coin = _currency_emoji(interaction.guild, "FumaoCoin")
        crystal = _currency_emoji(interaction.guild, "Crystal")
        grace = _currency_emoji(interaction.guild, "grace")
        embed = discord_module.Embed(
            title="💰 當前餘額",
            description=(
                f"{interaction.user.mention}\n\n"
                f"> `{_number(account['fumao_coins'])}` 芙帽幣 {coin}\n"
                f"> `{_number(account['crystals'])}` 水晶 {crystal}\n"
                f"> `{_number(account['grace'])}` 神恩 {grace}\n\n"
                f"簽到等級：**Lv.{account['level']}**\n"
                f"查詢時間：**{_period_time(now)}**"
            ),
            color=EMBED_COLOR,
        )
        embed.set_footer(text="UTC+8")
        await interaction.response.send_message(embed=embed)

    tree.add_command(economy)
