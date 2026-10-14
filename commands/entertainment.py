"""Entertainment lottery commands."""

from __future__ import annotations

import random
import time
from typing import Any, TYPE_CHECKING

import discord

from components_v2 import v2_view_from_embed

if TYPE_CHECKING:
    from commands.context import CommandContext


HUNTER_TALENTS = ["封窗", "一刀", "張狂", "底牌", "無"]
SURVIVOR_TALENTS = ["大心臟", "雙彈", "飛輪", "搏命", "無"]
SURVIVORS = [
    "幸運兒", "醫生", "律師", "慈善家", "園丁", "魔術師", "冒險家",
    "傭兵", "空軍", "機械師", "前鋒", "盲女", "祭司", "調香師",
    "牛仔", "舞女", "先知", "入殮師", "勘探員", "咒術師", "野人",
    "雜技演員", "大副", "調酒師", "郵差", "守墓人", "囚徒",
    "昆蟲學者", "畫家", "擊球手", "玩具商", "心理學家", "病患",
    "小說家", "小女孩", "哭泣小丑", "教授", "古董商", "作曲家",
    "記者", "飛行家", "拉拉隊員", "木偶師", "火災調查員", "法羅女士",
    "騎士", "氣象學家", "弓箭手", "逃脫大師", "幻燈師", "鬥牛士",
    "默劇藝人", "神童",
]
HUNTERS = [
    "廠長", "小丑", "鹿頭", "傑克", "蜘蛛", "紅蝶", "黃衣之主",
    "宿傘之魂", "攝影師", "瘋眼", "夢之女巫", "愛哭鬼", "孽蜥",
    "紅夫人", "26號守衛", "使徒", "小提琴家", "雕刻家", "博士",
    "破輪", "漁女", "蠟像師", "噩夢", "記錄員", "隱士", "守夜人",
    "歌劇演員", "愚人金", "時空之影", "跛腳羊", "喧囂", "雜貨商",
    "檯球手", "女王蜂", "牙醫", "心獸",
]
TRAITS = [
    "聆聽", "失常", "興奮", "巡視者", "傳送", "窺視者", "閃現", "移形",
]
MAPS = [
    "軍工廠", "聖心醫院", "紅教堂", "永眠鎮", "唐人街",
    "不歸林", "湖景村", "月亮河公園", "里奧的回憶",
]


def draw_match() -> dict[str, Any]:
    """Draw one random match using the supplied entertainment rules."""
    return {
        "map": random.choice(MAPS),
        "hunter": random.choice(HUNTERS),
        "hunter_talents": random.sample(HUNTER_TALENTS, 2),
        "trait": random.choice(TRAITS),
        "survivors": [
            {
                "name": name,
                "talents": random.sample(SURVIVOR_TALENTS, 2),
            }
            for name in random.sample(SURVIVORS, 4)
        ],
    }


def _match_embed(discord_module: Any, actor: Any, result: dict[str, Any]) -> Any:
    hunter_talents = "、".join(result["hunter_talents"])
    survivor_lines = [
        f"**{item['name']}**｜天賦：{ '、'.join(item['talents']) }"
        for item in result["survivors"]
    ]
    embed = discord_module.Embed(
        title="🎮 傻杯對局抽籤",
        description=f"{actor.mention} 抽出了一場隨機對局！",
        color=0x5865F2,
    )
    embed.add_field(name="🗺️ 地圖", value=result["map"], inline=False)
    embed.add_field(
        name="👁️ 監管者",
        value=(
            f"**{result['hunter']}**\n"
            f"天賦：{hunter_talents}\n"
            f"特質：{result['trait']}"
        ),
        inline=False,
    )
    embed.add_field(
        name="👥 求生者",
        value="\n".join(survivor_lines),
        inline=False,
    )
    embed.set_footer(text="娛樂抽籤｜每次執行都會重新抽取")
    return embed


def _registration_embed(discord_module: Any, view: "RegistrationView") -> Any:
    lines = [
        f"目前報名：**{len(view.registrants)}** 人",
        f"剩餘時間：**{view.timeout_seconds} 秒**",
        "點擊下方按鈕填寫你不想打的位置。",
    ]
    if view.registrants:
        roster = [
            f"{user.mention}｜不想打：{avoid or '無'}"
            for user, avoid in view.registrants.values()
        ]
        lines.extend(["", "\n".join(roster)])
    embed = discord_module.Embed(
        title="🎲 對局報名",
        description="\n".join(lines),
        color=0x5865F2,
    )
    embed.set_footer(text="時限結束後將隨機分配監管者與求生者位置")
    return embed


def _draw_registered_match(
    registrants: dict[int, tuple[Any, str]],
) -> tuple[Any, list[Any]] | None:
    participants = list(registrants.values())
    hunter_candidates = [item for item in participants if item[1] != "監管"]
    if not hunter_candidates:
        return None

    valid_hunters = []
    for hunter in hunter_candidates:
        survivors = [
            item for item in participants
            if item is not hunter and item[1] != "求生"
        ]
        if len(survivors) >= 4:
            valid_hunters.append((hunter, survivors))
    if not valid_hunters:
        return None

    hunter, survivors = random.choice(valid_hunters)
    return hunter[0], [item[0] for item in random.sample(survivors, 4)]


def _registration_result_embed(
    discord_module: Any,
    view: "RegistrationView",
) -> Any:
    result = _draw_registered_match(view.registrants)
    if result is None:
        description = (
            f"共 {len(view.registrants)} 人報名，但沒有符合條件的完整對局。\n"
            "至少需要 1 名可擔任監管者的玩家與 4 名可擔任求生者的玩家。"
        )
    else:
        hunter, survivors = result
        description = (
            f"監管者：{hunter.mention}\n\n"
            "求生者\n"
            + "\n".join(
                f"{index} 號位：{user.mention}"
                for index, user in enumerate(survivors, 1)
            )
        )
    embed = discord_module.Embed(
        title="🎲 對局分配完成",
        description=description,
        color=0x2ECC71 if result is not None else 0xE67E22,
    )
    embed.set_footer(text=f"共 {len(view.registrants)} 人報名｜報名已截止")
    return embed


class RegistrationView(discord.ui.View):
    def __init__(self, timeout_seconds: int) -> None:
        super().__init__(timeout=max(10, int(timeout_seconds)))
        self.timeout_seconds = max(10, int(timeout_seconds))
        self.registrants: dict[int, tuple[Any, str]] = {}
        self.message: Any = None
        self.closed = False
        self.created_at = time.monotonic()

        button = discord.ui.Button(
            label="點我報名",
            style=discord.ButtonStyle.primary,
            custom_id="entertainment-register",
        )
        button.callback = self._register_callback
        self.add_item(button)

    async def _register_callback(self, interaction: discord.Interaction) -> None:
        if self.closed:
            await interaction.response.send_message("報名已截止。", ephemeral=True)
            return
        await interaction.response.send_modal(RegistrationModal(self))

    async def refresh_message(self) -> None:
        if self.message is None or self.closed:
            return
        try:
            await self.message.edit(
                view=v2_view_from_embed(
                    _registration_embed(discord, self),
                    legacy_view=self,
                )
            )
        except (discord.NotFound, discord.HTTPException):
            return

    async def on_timeout(self) -> None:
        await self.finish()

    async def finish(self) -> bool:
        if self.closed:
            return False
        self.closed = True
        self.clear_items()
        if self.message is not None:
            ACTIVE_REGISTRATIONS.pop(int(self.message.id), None)
        if self.message is None:
            return True
        try:
            await self.message.edit(
                view=v2_view_from_embed(_registration_result_embed(discord, self))
            )
        except (discord.NotFound, discord.HTTPException):
            pass
        self.stop()
        return True


class RegistrationModal(discord.ui.Modal, title="對局報名"):
    avoid_input = discord.ui.TextInput(
        label="不想打的位置",
        placeholder="1＝監管、2＝求生，或留空",
        required=False,
        max_length=2,
    )

    def __init__(self, registration_view: RegistrationView) -> None:
        super().__init__()
        self.registration_view = registration_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        view = self.registration_view
        if view.closed:
            await interaction.response.send_message("報名已截止。", ephemeral=True)
            return
        if interaction.user.id in view.registrants:
            await interaction.response.send_message("你已提交過了。", ephemeral=True)
            return

        avoid = str(self.avoid_input.value or "").strip()
        avoid_mapping = {"1": "監管", "2": "求生"}
        if avoid not in {"", *avoid_mapping}:
            await interaction.response.send_message(
                "只能填 1（監管）、2（求生）或留空。",
                ephemeral=True,
            )
            return

        avoid = avoid_mapping.get(avoid, "")
        view.registrants[interaction.user.id] = (interaction.user, avoid)
        await interaction.response.send_message(
            f"報名成功！不想打：{avoid or '無'}",
            ephemeral=True,
        )
        await view.refresh_message()


ACTIVE_REGISTRATIONS: dict[int, RegistrationView] = {}


def register_active_registration(view: RegistrationView) -> None:
    if view.message is not None:
        ACTIVE_REGISTRATIONS[int(view.message.id)] = view


async def stop_active_registration(
    channel_id: str,
    message_id: str | None = None,
) -> bool:
    candidates = [
        view
        for view in ACTIVE_REGISTRATIONS.values()
        if view.message is not None
        and str(view.message.channel.id) == str(channel_id)
        and not view.closed
    ]
    if message_id:
        candidates = [
            view for view in candidates
            if str(view.message.id) == str(message_id)
        ]
    if not candidates:
        return False
    target = max(candidates, key=lambda view: view.created_at)
    return await target.finish()


def register_entertainment(
    tree: Any,
    discord_module: Any,
    app_commands: Any,
    context: CommandContext,
) -> None:
    entertainment = app_commands.Group(name="娛樂", description="各種娛樂功能")

    @entertainment.command(name="傻杯", description="隨機抽出一場傻杯對局")
    @app_commands.guild_only()
    async def silly_match(interaction: Any) -> None:
        result = draw_match()
        await interaction.response.send_message(
            view=v2_view_from_embed(
                _match_embed(discord_module, interaction.user, result)
            )
        )

    @entertainment.command(name="報名", description="建立一場限時對局報名")
    @app_commands.guild_only()
    @app_commands.describe(timeout_seconds="報名持續秒數，預設 60 秒")
    async def register_match(interaction: Any, timeout_seconds: int = 60) -> None:
        if not 10 <= timeout_seconds <= 3600:
            await interaction.response.send_message(
                "報名時限必須介於 10 到 3600 秒。",
                ephemeral=True,
            )
            return

        registration_view = RegistrationView(timeout_seconds)
        await interaction.response.send_message(
            view=v2_view_from_embed(
                _registration_embed(discord_module, registration_view),
                legacy_view=registration_view,
            )
        )
        registration_view.message = await interaction.original_response()
        register_active_registration(registration_view)

    tree.add_command(entertainment)
