"""Entertainment lottery commands."""

from __future__ import annotations

import random
from typing import Any, TYPE_CHECKING

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
    "默劇藝人",
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

    tree.add_command(entertainment)
