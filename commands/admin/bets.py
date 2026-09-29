"""Bet creation, betting, and resolution helpers for prefix commands."""

from __future__ import annotations

import re
import time
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import discord

from components_v2 import v2_view_from_embed


BET_CURRENCIES = {
    "fumao_coins": ("FumaoCoin", "芙帽幣", "<:FumaoCoin:1554060935725973554>"),
    "crystals": ("Crystal", "水晶", "<:Crystal:1554060934140403815>"),
    "grace": ("grace", "神恩", "<:grace:1554060937244180542>"),
}
MAX_OPTIONS = 5
MAX_DURATION_SECONDS = 30 * 24 * 60 * 60
BET_TEMPLATES = {
    1: {
        "name": "自訂賭盤",
        "content": "來猜猜這局的結果是??",
        "options": [("多抓", 2.0), ("多跑", 2.0), ("平局", 2.0)],
    },
    2: {
        "name": "勝負預測",
        "content": "來猜猜下一場的結果吧！",
        "options": [("勝利", 2.0), ("失敗", 2.0), ("平局", 2.0)],
    },
    3: {
        "name": "二選一賭盤",
        "content": "選出你認為會發生的結果。",
        "options": [("會", 2.0), ("不會", 2.0)],
    },
}
DURATION_PATTERN = re.compile(
    r"^(?:\d+(?:\.\d+)?\s*[smhd]\s*)+$",
    re.IGNORECASE,
)
DURATION_PART_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*([smhd])", re.IGNORECASE)
UTC_PLUS_8 = timezone(timedelta(hours=8), name="UTC+8")


def _format_odds(value: float) -> str:
    return f"×{value:.2f}"


def _format_deadline(timestamp_ms: int) -> str:
    deadline = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).astimezone(UTC_PLUS_8)
    return deadline.strftime("%Y-%m-%d %H:%M:%S UTC+8")


def _currency_display(currency: str) -> tuple[str, str]:
    info = BET_CURRENCIES.get(currency)
    if info is None:
        return currency, f":{currency}:"
    return info[1], info[2]


def _format_currency_totals(totals: dict[str, int]) -> str:
    lines = []
    for currency in ("fumao_coins", "crystals", "grace"):
        amount = int(totals.get(currency, 0))
        if amount == 0:
            continue
        label, emoji = _currency_display(currency)
        lines.append(f"**{amount:,}** {emoji} {label}")
    return "\n".join(lines) if lines else "無貨幣變動"


def _parse_duration(value: str) -> int:
    normalized = value.strip()
    if DURATION_PATTERN.fullmatch(normalized) is None:
        raise ValueError("時間格式請使用例如 `10s`、`1m30s`、`2h` 或 `1d`")
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    parts = list(DURATION_PART_PATTERN.finditer(normalized))
    matched_text = "".join("".join(part.group(0).split()) for part in parts)
    if not parts or matched_text != "".join(normalized.split()):
        raise ValueError("時間格式請使用例如 `10s`、`1m30s`、`2h` 或 `1d`")
    seen_units: set[str] = set()
    seconds = 0.0
    for part in parts:
        unit = part.group(2).lower()
        if unit in seen_units:
            raise ValueError("同一個時間單位只能出現一次，例如請使用 `2m`，不要使用 `1m60s`")
        seen_units.add(unit)
        seconds += float(part.group(1)) * units[unit]
    seconds = int(seconds)
    if seconds < 1 or seconds > MAX_DURATION_SECONDS:
        raise ValueError("下注時間必須介於 1 秒與 30 天之間")
    return seconds


def _parse_options(value: str) -> list[tuple[str, float]]:
    options: list[tuple[str, float]] = []
    for raw_option in re.split(r"[,\n]+", value.strip()):
        if not raw_option:
            continue
        if ":" not in raw_option and "：" not in raw_option:
            raise ValueError("狀況格式應為 `狀況:倍率`，多個狀況請用逗號分隔，例如 `aaa:2,bbb:2`")
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


def get_bet_template(template_id: int) -> dict[str, Any] | None:
    template = BET_TEMPLATES.get(int(template_id))
    if template is None:
        return None
    return {
        "name": str(template["name"]),
        "content": str(template["content"]),
        "options": list(template["options"]),
    }


def _parse_start_mode(value: str, default: bool = True) -> bool:
    normalized = value.strip().casefold()
    if not normalized:
        return default
    if normalized in {"t", "true", "y", "yes", "1", "立即", "立即開始"}:
        return True
    if normalized in {"f", "false", "n", "no", "0", "手動", "稍後", "需start-bet"}:
        return False
    raise ValueError("開放下注參數請輸入 `t`（建立後立即開放）或 `f`（等待 &start-bet）")


def _bet_embed(
    title: str,
    content: str,
    options: list[tuple[str, float]],
    expires_at: int,
    *,
    resolved: str | None = None,
    closed: bool = False,
    started: bool = True,
) -> discord.Embed:
    if resolved is None:
        if closed:
            status = "⏹️ 已停止下注"
        elif started:
            status = "🟢 開放下注"
        else:
            status = "⏸️ 尚未開放下注"
    elif resolved.casefold() == "return":
        status = "↩️ 已退款"
    else:
        status = f"🏁 結果：{resolved}"
    description_parts = []
    if content:
        description_parts.append(content)
    description_parts.append(
        f"{status}\n"
        f"截止時間：{_format_deadline(expires_at)}"
    )
    embed = discord.Embed(
        title=f"🎲 {title}",
        description="\n\n".join(description_parts),
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
    embed.set_footer(
        text=(
            "按下狀況按鈕後，在私人表單輸入芙帽幣下注金額"
            if started and not closed
            else "管理員可使用 &start-bet 訊息ID 開放下注"
            if not started and not closed
            else "此賭盤已停止下注"
        )
    )
    return embed


class BetCreateModal(discord.ui.Modal, title="建立賭盤"):
    duration = discord.ui.TextInput(
        label="下注持續時間",
        placeholder="例如：10s、1m30s、2h、1d",
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
        required=False,
    )
    options_input = discord.ui.TextInput(
        label="狀況與倍率",
        placeholder="例如：aaa:2,bbb:2",
        max_length=1000,
    )

    def __init__(
        self,
        store: Any,
        channel: Any,
        guild_id: str,
        template_id: int | None = None,
        start_immediately: bool | None = None,
    ) -> None:
        super().__init__()
        self.store = store
        self.channel = channel
        self.guild_id = guild_id
        self.template_id = template_id
        self.start_immediately = start_immediately
        template = get_bet_template(template_id) if template_id is not None else None
        if template is not None:
            if template_id == 1:
                self.duration.default = "5m"
            self.title_input.default = template["name"]
            self.content_input.default = template["content"]
            self.options_input.default = ",".join(
                f"{name}:{odds:g}" for name, odds in template["options"]
            )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            duration_seconds = _parse_duration(str(self.duration.value))
            start_immediately = self.start_immediately if self.start_immediately is not None else True
            title = " ".join(str(self.title_input.value).split())
            content = str(self.content_input.value).strip()
            options = _parse_options(str(self.options_input.value))
            if not title:
                raise ValueError("賭盤標題不可空白")
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return

        created_at = int(time.time() * 1000)
        expires_at = created_at + duration_seconds * 1000
        started_at = created_at if start_immediately else None
        bet_view = BetOpenView(
            self.store,
            title,
            content,
            options,
            expires_at,
            started=start_immediately,
        )
        try:
            message = await self.channel.send(
                view=v2_view_from_embed(
                    _bet_embed(
                        title,
                        content,
                        options,
                        expires_at,
                        started=start_immediately,
                    ),
                    legacy_view=bet_view,
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            bet_view.message_id = str(message.id)
            bet_view.message = message
            await self.store_create(
                str(message.id),
                created_at,
                expires_at,
                started_at,
                title,
                content,
                options,
            )
            bet_view.schedule_expiry()
        except Exception:
            try:
                await message.delete()
            except (UnboundLocalError, discord.HTTPException):
                pass
            await interaction.response.send_message("建立賭盤失敗，請稍後再試。", ephemeral=True)
            return

        await interaction.response.send_message(
            (
                f"賭盤已建立並開放下注，訊息 ID：`{message.id}`"
                if start_immediately
                else f"賭盤已建立但尚未開放下注，訊息 ID：`{message.id}`\n"
                f"請使用 `&start-bet {message.id}` 開放下注。"
            ),
            ephemeral=True,
        )

    async def store_create(
        self,
        message_id: str,
        created_at: int,
        expires_at: int,
        started_at: int | None,
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
            started_at,
            options,
        )


class BetSetupView(discord.ui.View):
    def __init__(
        self,
        store: Any,
        channel: Any,
        guild_id: str,
        template_id: int | None = None,
        start_immediately: bool | None = None,
    ) -> None:
        super().__init__(timeout=300)
        self.store = store
        self.channel = channel
        self.guild_id = guild_id
        self.template_id = template_id
        self.start_immediately = start_immediately

    @discord.ui.button(label="建立賭盤", style=discord.ButtonStyle.primary)
    async def create_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(
            BetCreateModal(
                self.store,
                self.channel,
                self.guild_id,
                self.template_id,
                self.start_immediately,
            )
        )


class BetSpendConfirmView(discord.ui.View):
    def __init__(self, user_id: str, on_confirm: Any) -> None:
        super().__init__(timeout=300)
        self.user_id = str(user_id)
        self.on_confirm = on_confirm

        confirm = discord.ui.Button(label="確認下注", style=discord.ButtonStyle.danger)
        confirm.callback = self._confirm
        self.add_item(confirm)
        cancel = discord.ui.Button(label="取消", style=discord.ButtonStyle.secondary)
        cancel.callback = self._cancel
        self.add_item(cancel)

    async def _confirm(self, interaction: discord.Interaction) -> None:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("這不是你的下注確認介面。", ephemeral=True)
            return
        try:
            await interaction.response.defer()
            await self.on_confirm(interaction)
        except (discord.NotFound, discord.HTTPException):
            return
        finally:
            self.stop()

    async def _cancel(self, interaction: discord.Interaction) -> None:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("這不是你的下注確認介面。", ephemeral=True)
            return
        try:
            await interaction.response.edit_message(
                view=v2_view_from_embed(
                    discord.Embed(
                        title="已取消下注",
                        description="這次沒有扣除芙帽幣。",
                        color=0x95A5A6,
                    )
                )
            )
        except (discord.NotFound, discord.HTTPException):
            return
        self.stop()


class BetAmountModal(discord.ui.Modal, title="下注確認"):
    amount = discord.ui.TextInput(
        label="下注數量（芙帽幣）",
        placeholder="請輸入正整數，例如：500",
        max_length=20,
    )

    def __init__(
        self,
        store: Any,
        message_id: str,
        option_name: str,
        account: dict[str, Any],
    ) -> None:
        super().__init__()
        self.store = store
        self.message_id = message_id
        self.option_name = option_name
        self.account = account
        self.amount.placeholder = f"目前餘額：{int(account['fumao_coins']):,}，例如：500"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            amount = int(str(self.amount.value).replace(",", ""))
            if amount < 1:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("下注數量必須是大於 0 的整數。", ephemeral=True)
            return

        import asyncio

        preview = await asyncio.to_thread(
            self.store.pvp_spending_preview,
            str(interaction.user.id),
            amount,
        )
        if preview.get("will_force_close"):
            warning = discord.Embed(
                title="⚠️ 確認下注",
                description=(
                    f"這次將下注 **{amount:,}** 芙帽幣。\n"
                    f"下注後餘額：**{preview['after']:,}** 芙帽幣\n"
                    f"PvP 強制關閉門檻：**{preview['threshold']:,.0f}** 芙帽幣\n\n"
                    "下注後會低於 PvP 強制關閉門檻，PvP 將被關閉並進入 24 小時冷卻。\n"
                    "確定仍要下注嗎？"
                ),
                color=0xE67E22,
            )
            await interaction.response.send_message(
                view=v2_view_from_embed(
                    warning,
                    legacy_view=BetSpendConfirmView(
                        str(interaction.user.id),
                        lambda confirmed: self._place_bet(confirmed, amount),
                    ),
                ),
                ephemeral=True,
            )
            return

        await self._place_bet(interaction, amount)

    async def _place_bet(self, interaction: discord.Interaction, amount: int) -> None:
        import asyncio

        try:
            result = await asyncio.to_thread(
                self.store.place_bet,
                self.message_id,
                str(interaction.user.id),
                self.option_name,
                "fumao_coins",
                amount,
                int(time.time() * 1000),
            )
        except ValueError as error:
            if interaction.response.is_done():
                await interaction.followup.send(str(error), ephemeral=True)
            else:
                await interaction.response.send_message(str(error), ephemeral=True)
            return

        embed = discord.Embed(
            title="✅ 下注成功",
            description=(
                f"狀況：**{self.option_name}**\n"
                f"下注：**{amount:,}** {_currency_display('fumao_coins')[1]} 芙帽幣\n"
                f"倍率：**{_format_odds(result['odds'])}**\n"
                f"剩餘餘額：**{result['balance']:,}** {_currency_display('fumao_coins')[1]} 芙帽幣"
            ),
            color=0x2ECC71,
        )
        if interaction.response.is_done():
            await interaction.edit_original_response(view=v2_view_from_embed(embed))
        else:
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
        *,
        started: bool = True,
    ) -> None:
        super().__init__(timeout=None)
        self.store = store
        self.title = title
        self.content = content
        self.options = options
        self.expires_at = expires_at
        self.started = started
        self.message_id: str | None = None
        self.message: discord.Message | None = None
        self.closed = False
        self.expiry_task: asyncio.Task[None] | None = None
        for option_name, odds in (options if started else []):
            button = discord.ui.Button(
                label=option_name,
                style=discord.ButtonStyle.primary,
            )
            button.callback = self._option_callback(option_name)
            self.add_item(button)

    def schedule_expiry(self) -> None:
        if self.expiry_task is None:
            self.expiry_task = asyncio.create_task(self._close_when_expired())

    async def _close_when_expired(self) -> None:
        delay = max(0.0, (self.expires_at - int(time.time() * 1000)) / 1000)
        await asyncio.sleep(delay)
        await self.close()

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.store is not None and self.message_id is not None:
            try:
                result = await asyncio.to_thread(
                    self.store.stop_bet,
                    self.message_id,
                    int(time.time() * 1000),
                )
            except ValueError:
                return
            if result.get("resolved_outcome") is not None:
                self.stop()
                return
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(
                    view=v2_view_from_embed(
                        _bet_embed(
                            self.title,
                            self.content,
                            self.options,
                            self.expires_at,
                            closed=True,
                            started=self.started,
                        ),
                        legacy_view=self,
                    )
                )
            except discord.HTTPException:
                pass
        self.stop()

    def _option_callback(self, option_name: str):
        async def callback(interaction: discord.Interaction) -> None:
            if self.message_id is None:
                await interaction.response.send_message("賭盤尚未準備完成。", ephemeral=True)
                return
            if int(time.time() * 1000) >= self.expires_at:
                await interaction.response.send_message("這個賭盤已經截止下注。", ephemeral=True)
                await self.close()
                return
            account = await asyncio.to_thread(
                self.store.economy_account,
                str(interaction.user.id),
            )
            await interaction.response.send_modal(
                BetAmountModal(self.store, self.message_id, option_name, account)
            )

        return callback


async def stop_bet_message(
    message: discord.Message,
    store: Any,
    message_id: str,
) -> discord.Embed:
    import asyncio

    bet = await asyncio.to_thread(store.bet_details, message_id)
    if bet is None:
        raise ValueError("找不到這個賭盤")
    if bet["resolved_outcome"] is not None:
        raise ValueError("這個賭盤已經結算，無法停止下注")

    try:
        target = await message.channel.fetch_message(int(message_id))
    except (discord.HTTPException, ValueError) as error:
        raise ValueError("找不到賭盤訊息，請確認訊息 ID 位於目前頻道。") from error

    bet_view = BetOpenView(
        store,
        bet["title"],
        bet["content"],
        bet["options"],
        bet["expires_at"],
        started=bet["started_at"] is not None,
    )
    bet_view.message_id = str(message_id)
    bet_view.message = target
    await bet_view.close()
    return _bet_embed(
        bet["title"],
        bet["content"],
        bet["options"],
        bet["expires_at"],
        closed=True,
        started=bet["started_at"] is not None,
    )


async def start_bet_message(
    message: discord.Message,
    store: Any,
    message_id: str,
) -> tuple[discord.Embed, BetOpenView]:
    bet = await asyncio.to_thread(store.bet_details, message_id)
    if bet is None:
        raise ValueError("找不到這個賭盤")
    if bet["resolved_outcome"] is not None:
        raise ValueError("這個賭盤已經結算，無法開始下注")
    if bet["closed_at"] is not None:
        raise ValueError("這個賭盤已經停止下注，無法開始")
    if bet["started_at"] is not None:
        raise ValueError("這個賭盤已經開始下注")
    if int(time.time() * 1000) >= bet["expires_at"]:
        raise ValueError("這個賭盤已經超過截止時間，無法開始下注")

    try:
        target = await message.channel.fetch_message(int(message_id))
    except (discord.HTTPException, ValueError) as error:
        raise ValueError("找不到賭盤訊息，請確認訊息 ID 位於目前頻道。") from error

    started_at = int(time.time() * 1000)
    await asyncio.to_thread(store.start_bet, message_id, started_at)
    bet_view = BetOpenView(
        store,
        bet["title"],
        bet["content"],
        bet["options"],
        bet["expires_at"],
        started=True,
    )
    bet_view.message_id = str(message_id)
    bet_view.message = target
    embed = _bet_embed(
        bet["title"],
        bet["content"],
        bet["options"],
        bet["expires_at"],
        started=True,
    )
    await target.edit(view=v2_view_from_embed(embed, legacy_view=bet_view))
    bet_view.schedule_expiry()
    return embed, bet_view


def setup_bet_card(
    store: Any,
    channel: Any,
    guild_id: str,
    template_id: int | None = None,
    start_immediately: bool | None = None,
) -> discord.ui.View:
    templates_text = "\n可用模板：1 自訂賭盤、2 勝負預測、3 二選一賭盤。"
    template_text = ""
    if template_id is not None:
        template = get_bet_template(template_id)
        if template is not None:
            template_text = f"\n目前模板：**{template_id}. {template['name']}**"
    start_text = ""
    if start_immediately is not None:
        start_text = "\n建立後：**立即開放下注**" if start_immediately else "\n建立後：**等待 &start-bet**"
    embed = discord.Embed(
        title="🎲 建立賭盤",
        description=(
            f"按下下方按鈕後，會以私人表單填寫賭盤資料。"
            f"{templates_text}{template_text}{start_text}"
        ),
        color=0xE7A0B4,
    )
    return v2_view_from_embed(
        embed,
        legacy_view=BetSetupView(
            store,
            channel,
            guild_id,
            template_id,
            start_immediately,
        ),
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
        resolved=(
            result["outcome"]
            if result["outcome"].casefold() == "return"
            else result["outcome"].replace(",", "、")
        ),
    )
    if result["outcome"].casefold() == "return":
        totals = _format_currency_totals(result["refunded_by_currency"])
        resolved_embed.add_field(
            name="結算結果",
            value=f"已退還：\n{totals}",
            inline=False,
        )
    else:
        totals = _format_currency_totals(result["paid_by_currency"])
        resolved_embed.add_field(
            name="結算結果",
            value=(
                f"中獎人數：**{result['winners']}**\n"
                f"派發獎金：\n{totals}"
            ),
            inline=False,
        )
    try:
        target = await message.channel.fetch_message(int(message_id))
        await target.edit(view=v2_view_from_embed(resolved_embed))
    except (discord.HTTPException, ValueError):
        pass
    return resolved_embed
