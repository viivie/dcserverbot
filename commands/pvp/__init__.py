"""PvP commands, interfaces, and artifact domains."""

from __future__ import annotations

import asyncio
import random
import time
from typing import Any, TYPE_CHECKING

import discord

from components_v2 import v2_view_from_embed

from .config import ARTIFACT_CONFIG, PVP_CONFIG, artifact_color, artifact_domain, direct_upgrade_config, pvp_rules
from .engine import calculate_damage, drop_count, generate_artifact
from .store import PvpStore

if TYPE_CHECKING:
    from commands.context import CommandContext


COLOR = 0x8B5CF6
TAIPEI_LABEL = "UTC+8"


def _number(value: int | float) -> str:
    return f"{value:,.0f}"


def _percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def _error_embed(message: str) -> discord.Embed:
    return discord.Embed(title="⚠️ PvP", description=message, color=0xD9534F)


def _profile_embed(profile: dict[str, Any], title: str = "⚔️ PvP 狀態") -> discord.Embed:
    enabled = "🟢 已開啟" if profile.get("enabled") else "⚪ 未開啟"
    description = [
        f"狀態：**{enabled}**",
        f"目前芙帽幣：**{_number(profile.get('fumao_coins', 0))}**",
    ]
    if profile.get("baseline_coins"):
        remaining = max(0, int(profile["loss_cap"]) - int(profile["lost_coins"]))
        description.extend([
            f"PvP 基準金額：**{_number(profile['baseline_coins'])}**",
            f"損失上限：**{_number(profile['loss_cap'])}**",
            f"已損失：**{_number(profile['lost_coins'])}**　剩餘可損失：**{_number(remaining)}**",
        ])
    embed = discord.Embed(title=title, description="\n".join(description), color=COLOR)
    embed.add_field(
        name="直接升級屬性",
        value=(
            f"ATK `{profile.get('direct_atk', 0):g}`　DEF `{profile.get('direct_def', 0):g}`\n"
            f"ATK% `{_percent(profile.get('direct_atk_percent', 0))}`　DEF% `{_percent(profile.get('direct_def_percent', 0))}`\n"
            f"HP `{profile.get('direct_hp', 0):g}`　HP% `{_percent(profile.get('direct_hp_percent', 0))}`\n"
            f"暴擊率 `{_percent(profile.get('direct_crit_rate', 0))}`　爆傷 `{_percent(profile.get('direct_crit_damage', 0))}`"
        ),
        inline=False,
    )
    embed.set_footer(text=TAIPEI_LABEL)
    return embed


class UpgradeView(discord.ui.View):
    def __init__(self, pvp: PvpStore, user_id: str, *, timeout: float = 300) -> None:
        super().__init__(timeout=timeout)
        self.pvp = pvp
        self.user_id = str(user_id)
        upgrade = direct_upgrade_config()
        labels = {
            "atk": "ATK +", "def": "DEF +", "atk_percent": "ATK% +", "def_percent": "DEF% +",
            "hp": "HP +", "hp_percent": "HP% +", "crit_rate": "暴擊率 +", "crit_damage": "爆傷 +",
        }
        for stat, label in labels.items():
            button = discord.ui.Button(label=label, style=discord.ButtonStyle.primary, custom_id=f"pvp-upgrade-{stat}")
            button.callback = self._callback_for(stat, upgrade)
            self.add_item(button)

    def _callback_for(self, stat: str, upgrade: dict[str, Any]):
        async def callback(interaction: discord.Interaction) -> None:
            if str(interaction.user.id) != self.user_id:
                await interaction.response.send_message("這不是你的 PvP 升級介面。", ephemeral=True)
                return
            await interaction.response.defer()
            now = int(time.time() * 1000)
            try:
                result = await asyncio.to_thread(
                    self.pvp.upgrade_stat,
                    self.user_id,
                    stat,
                    float(upgrade["amounts"][stat]),
                    int(upgrade["coin_cost"]),
                    float(upgrade["caps"]["crit_rate"]),
                    float(upgrade["caps"]["crit_damage"]),
                    now,
                )
                profile = await asyncio.to_thread(self.pvp.profile, self.user_id, now)
                embed = _profile_embed(profile, "⚔️ PvP 升級介面")
                embed.description = (embed.description or "") + f"\n\n每次升級消耗 **{_number(upgrade['coin_cost'])}** 芙帽幣。"
                if result.get("error") == "insufficient_funds":
                    embed.description += "\n\n⚠️ 芙帽幣不足，無法升級。"
                elif result.get("error") == "at_cap":
                    embed.description += "\n\n⚠️ 這個屬性已達直接升級上限。"
                await interaction.edit_original_response(view=v2_view_from_embed(embed, legacy_view=self))
            except (discord.NotFound, discord.HTTPException):
                return

        return callback


class ArtifactView(discord.ui.View):
    def __init__(self, pvp: PvpStore, user_id: str, artifacts: list[dict[str, Any]], *, timeout: float = 300) -> None:
        super().__init__(timeout=timeout)
        self.pvp = pvp
        self.user_id = str(user_id)
        for artifact in artifacts[:8]:
            artifact_id = int(artifact["id"])
            equip = discord.ui.Button(
                label=f"裝備 #{artifact_id}",
                style=discord.ButtonStyle.success if artifact["equipped"] else discord.ButtonStyle.secondary,
                custom_id=f"pvp-equip-{artifact_id}",
            )
            equip.callback = self._equip_callback(artifact_id)
            self.add_item(equip)
            color = artifact_color(str(artifact["color"]))
            if int(artifact["level"]) < int(color["max_level"]):
                upgrade = discord.ui.Button(label=f"強化 #{artifact_id}", style=discord.ButtonStyle.primary, custom_id=f"pvp-art-up-{artifact_id}")
                upgrade.callback = self._upgrade_callback(artifact)
                self.add_item(upgrade)
            salvage = discord.ui.Button(label=f"分解 #{artifact_id}", style=discord.ButtonStyle.danger, custom_id=f"pvp-salvage-{artifact_id}")
            salvage.callback = self._salvage_callback(artifact_id)
            self.add_item(salvage)

    async def _refresh(self, interaction: discord.Interaction, title: str = "🧿 聖遺物") -> None:
        artifacts = await asyncio.to_thread(self.pvp.artifacts, self.user_id)
        embed = _artifacts_embed(artifacts, title)
        await interaction.edit_original_response(view=v2_view_from_embed(embed, legacy_view=ArtifactView(self.pvp, self.user_id, artifacts)))

    def _equip_callback(self, artifact_id: int):
        async def callback(interaction: discord.Interaction) -> None:
            if str(interaction.user.id) != self.user_id:
                await interaction.response.send_message("這不是你的聖遺物介面。", ephemeral=True)
                return
            await interaction.response.defer()
            try:
                await asyncio.to_thread(self.pvp.equip_artifact, self.user_id, artifact_id)
                await self._refresh(interaction)
            except (ValueError, discord.NotFound, discord.HTTPException) as error:
                if isinstance(error, ValueError):
                    await interaction.followup.send(str(error), ephemeral=True)

        return callback

    def _upgrade_callback(self, artifact: dict[str, Any]):
        async def callback(interaction: discord.Interaction) -> None:
            if str(interaction.user.id) != self.user_id:
                await interaction.response.send_message("這不是你的聖遺物介面。", ephemeral=True)
                return
            await interaction.response.defer()
            color = str(artifact["color"])
            level = int(artifact["level"])
            costs = PVP_CONFIG["artifact_upgrade_costs"].get(color, [])
            if level >= len(costs):
                await interaction.followup.send("這件聖遺物已達等級上限。", ephemeral=True)
                return
            roll_stat = None
            roll_amount = 0.0
            if level + 1 in (4, 8, 12, 16, 20):
                candidates = list(artifact.get("sub_stats", {}))
                if candidates:
                    roll_stat = random.choice(candidates)
                    from .engine import _sub_value
                    roll_amount = _sub_value(roll_stat, color)
            try:
                await asyncio.to_thread(
                    self.pvp.upgrade_artifact,
                    self.user_id, int(artifact["id"]), int(artifact_color(color)["max_level"]),
                    int(costs[level]), roll_stat, roll_amount, int(time.time() * 1000),
                )
                await self._refresh(interaction, "🧿 聖遺物強化完成")
            except (ValueError, discord.NotFound, discord.HTTPException) as error:
                if isinstance(error, ValueError):
                    await interaction.followup.send(str(error), ephemeral=True)

        return callback

    def _salvage_callback(self, artifact_id: int):
        async def callback(interaction: discord.Interaction) -> None:
            if str(interaction.user.id) != self.user_id:
                await interaction.response.send_message("這不是你的聖遺物介面。", ephemeral=True)
                return
            await interaction.response.defer()
            try:
                refund = await asyncio.to_thread(self.pvp.salvage_artifact, self.user_id, artifact_id, int(time.time() * 1000))
                await self._refresh(interaction, f"🧿 聖遺物已分解，返還 {_number(refund)} 芙帽幣")
            except (ValueError, discord.NotFound, discord.HTTPException) as error:
                if isinstance(error, ValueError):
                    await interaction.followup.send(str(error), ephemeral=True)

        return callback


class DomainView(discord.ui.View):
    def __init__(self, pvp: PvpStore, user_id: str, domain: dict[str, Any], level: int, *, timeout: float = 300) -> None:
        super().__init__(timeout=timeout)
        self.pvp = pvp
        self.user_id = str(user_id)
        self.domain = domain
        for difficulty in PVP_CONFIG.get("domain_difficulties", [4, 8, 10, 12, 15]):
            button = discord.ui.Button(
                label=f"Lv.{difficulty}",
                style=discord.ButtonStyle.primary,
                disabled=int(level) < int(difficulty),
                custom_id=f"pvp-domain-{domain.get('id', 'domain')}-{difficulty}",
            )
            button.callback = self._run_callback(int(difficulty))
            self.add_item(button)

    def _run_callback(self, difficulty: int):
        async def callback(interaction: discord.Interaction) -> None:
            if str(interaction.user.id) != self.user_id:
                await interaction.response.send_message("這不是你的秘境介面。", ephemeral=True)
                return
            await interaction.response.defer()
            created: list[dict[str, Any]] = []
            set_ids = self.domain.get("set_ids", [""]) or [""]
            for color in ("green", "blue", "purple", "yellow"):
                count = drop_count(self.domain, color, difficulty)
                for _ in range(count):
                    artifact = generate_artifact(color, random.choice(set_ids))
                    await asyncio.to_thread(self.pvp.add_artifact, self.user_id, artifact, int(time.time() * 1000))
                    created.append(artifact)
            if created:
                lines = [f"{artifact_color(item['color'])['label']} {item['slot']}（{item['main_stat']}）" for item in created]
                description = "成功取得：\n" + "\n".join(lines)
            else:
                description = "這次沒有取得聖遺物。"
            embed = discord.Embed(title=f"🏛️ {self.domain.get('name', '秘境')} Lv.{difficulty}", description=description, color=COLOR)
            await interaction.edit_original_response(view=v2_view_from_embed(embed))

        return callback


class DomainSelectView(discord.ui.View):
    def __init__(self, pvp: PvpStore, user_id: str, domains: list[dict[str, Any]], level: int, *, timeout: float = 300) -> None:
        super().__init__(timeout=timeout)
        self.pvp = pvp
        self.user_id = str(user_id)
        self.level = int(level)
        for domain in domains[:25]:
            button = discord.ui.Button(
                label=str(domain.get("name", domain.get("id", "秘境")))[:80],
                style=discord.ButtonStyle.primary,
                custom_id=f"pvp-domain-select-{domain.get('id', 'domain')}",
            )
            button.callback = self._select_callback(domain)
            self.add_item(button)

    def _select_callback(self, domain: dict[str, Any]):
        async def callback(interaction: discord.Interaction) -> None:
            if str(interaction.user.id) != self.user_id:
                await interaction.response.send_message("這不是你的秘境介面。", ephemeral=True)
                return
            await interaction.response.defer()
            embed = discord.Embed(
                title=f"🏛️ {domain.get('name', '秘境')}",
                description="選擇已解鎖的難度。難度會依照你的等級在 4、8、10、12、15 解鎖。",
                color=COLOR,
            )
            await interaction.edit_original_response(
                view=v2_view_from_embed(
                    embed,
                    legacy_view=DomainView(self.pvp, self.user_id, domain, self.level),
                )
            )

        return callback


def _artifacts_embed(artifacts: list[dict[str, Any]], title: str = "🧿 聖遺物") -> discord.Embed:
    equipped = [item for item in artifacts if item.get("equipped")]
    lines = ["已裝備："]
    if equipped:
        lines.extend(
            f"{artifact_color(item['color'])['label']} {item['slot']} Lv.{item['level']}　{item['main_stat']} {item['main_value']:g}"
            for item in equipped
        )
    else:
        lines.append("尚未裝備聖遺物。")
    lines.append(f"\n背包：**{len(artifacts)}** / 5 個裝備欄位（可持有數量不限）")
    for item in artifacts[:8]:
        lines.append(
            f"#{item['id']} {artifact_color(item['color'])['label']} {item['slot']} Lv.{item['level']}"
            f"　副詞條 {len(item.get('sub_stats', {}))} 條"
        )
    embed = discord.Embed(title=title, description="\n".join(lines), color=COLOR)
    embed.set_footer(text="升級成本與詞條規則可在 commands/pvp/json 修改")
    return embed


def register_pvp(tree: Any, discord_module: Any, app_commands: Any, context: CommandContext) -> None:
    pvp = app_commands.Group(name="pvp", description="PvP、聖遺物與秘境")
    store = PvpStore(context.store)

    @pvp.command(name="狀態", description="開啟或關閉 PvP")
    @app_commands.guild_only()
    @app_commands.describe(enabled="是否開啟 PvP")
    async def pvp_status(interaction: Any, enabled: bool) -> None:
        result = await asyncio.to_thread(
            store.toggle,
            str(interaction.user.id), bool(enabled), int(time.time() * 1000),
            int(pvp_rules()["minimum_open_coins"]),
            int(PVP_CONFIG["cooldowns"]["toggle_hours"] * 60 * 60 * 1000),
        )
        error = result.get("error")
        if error:
            messages = {
                "already_enabled": "PvP 已經是開啟狀態。",
                "already_disabled": "PvP 已經是關閉狀態。",
                "insufficient_funds": f"開啟 PvP 至少需要 {_number(result.get('required', 10000))} 芙帽幣。",
                "toggle_cooldown": f"開關冷卻中，還要等待 {_number(result.get('remaining_ms', 0) / 1000)} 秒。",
                "forced_cooldown": f"PvP 強制冷卻中，還要等待 {_number(result.get('remaining_ms', 0) / 1000)} 秒。",
            }
            await interaction.response.send_message(view=v2_view_from_embed(_error_embed(messages.get(error, "目前無法變更 PvP 狀態。"))), ephemeral=True)
            return
        profile = await asyncio.to_thread(store.profile, str(interaction.user.id))
        await interaction.response.send_message(view=v2_view_from_embed(_profile_embed(profile)), ephemeral=True)

    @pvp.command(name="攻擊", description="攻擊一名已開啟 PvP 的玩家")
    @app_commands.guild_only()
    @app_commands.describe(target="要攻擊的玩家")
    async def pvp_attack(interaction: Any, target: discord.Member) -> None:
        if target.id == interaction.user.id:
            await interaction.response.send_message("不能攻擊自己。", ephemeral=True)
            return
        if target.bot:
            await interaction.response.send_message("不能攻擊機器人。", ephemeral=True)
            return
        attacker_id = str(interaction.user.id)
        defender_id = str(target.id)
        try:
            attacker_profile = await asyncio.to_thread(store.profile, attacker_id)
            artifacts = await asyncio.to_thread(store.artifacts, attacker_id)
            damage = calculate_damage(attacker_profile, artifacts)
            defender_profile = await asyncio.to_thread(store.profile, defender_id)
            prize_pool = max(int(defender_profile["fumao_coins"]), int(defender_profile["baseline_coins"])) * float(pvp_rules()["prize_pool_rate"])
            theft = max(1, int(prize_pool * float(damage["r"])))
            result = await asyncio.to_thread(
                store.resolve_attack, attacker_id, defender_id, theft, int(time.time() * 1000),
                {"damage": damage["damage"], "r": damage["r"], "critical": damage["critical"], "k_atk": damage["k_atk"], "k_def": damage["k_def"]},
            )
        except ValueError as error:
            await interaction.response.send_message(view=v2_view_from_embed(_error_embed(str(error))), ephemeral=True)
            return
        critical_line = "💥 暴擊！\n" if damage["critical"] else ""
        embed = discord.Embed(
            title="⚔️ PvP 攻擊結果",
            description=(
                f"{interaction.user.mention} 攻擊了 {target.mention}\n"
                f"造成傷害：**{damage['damage']:.2f}**（r = **{damage['r']:.4f}**）\n"
                + critical_line
                + f"偷取芙帽幣：**{_number(result['amount'])}**\n"
                f"對方剩餘：**{_number(result['defender_balance'])}**"
            ),
            color=0xC0392B,
        )
        if result["closed"]:
            embed.set_footer(text="防守方已達到損失上限，PvP 已強制關閉。")
        await interaction.response.send_message(view=v2_view_from_embed(embed))

    @pvp.command(name="升級", description="開啟 PvP 直接升級介面")
    @app_commands.guild_only()
    async def pvp_upgrade(interaction: Any) -> None:
        profile = await asyncio.to_thread(store.profile, str(interaction.user.id))
        embed = _profile_embed(profile, "⚔️ PvP 升級介面")
        embed.description = (embed.description or "") + f"\n\n每次升級消耗 **{_number(direct_upgrade_config()['coin_cost'])}** 芙帽幣。"
        await interaction.response.send_message(
            view=v2_view_from_embed(embed, legacy_view=UpgradeView(store, str(interaction.user.id))),
            ephemeral=True,
        )

    @pvp.command(name="聖遺物", description="查看與管理 PvP 聖遺物")
    @app_commands.guild_only()
    async def pvp_artifacts(interaction: Any) -> None:
        artifacts = await asyncio.to_thread(store.artifacts, str(interaction.user.id))
        await interaction.response.send_message(
            view=v2_view_from_embed(
                _artifacts_embed(artifacts),
                legacy_view=ArtifactView(store, str(interaction.user.id), artifacts),
            ),
            ephemeral=True,
        )

    @pvp.command(name="秘境", description="選擇秘境難度並取得聖遺物")
    @app_commands.guild_only()
    async def pvp_domain(interaction: Any) -> None:
        domains = [item for item in ARTIFACT_CONFIG.get("domains", []) if isinstance(item, dict)]
        domain = domains[0] if domains else None
        if not domains:
            await interaction.response.send_message(view=v2_view_from_embed(_error_embed("尚未設定任何秘境，請先編輯 commands/pvp/json/artifacts.json。")), ephemeral=True)
            return
        profile = await asyncio.to_thread(store.profile, str(interaction.user.id))
        if len(domains) > 1:
            embed = discord.Embed(title="🏛️ 選擇秘境", description="請選擇要挑戰的秘境。", color=COLOR)
            await interaction.response.send_message(
                view=v2_view_from_embed(
                    embed,
                    legacy_view=DomainSelectView(store, str(interaction.user.id), domains, int(profile.get("level", 1))),
                ),
                ephemeral=True,
            )
            return
        embed = discord.Embed(
            title=f"🏛️ {domain.get('name', '秘境')}",
            description="選擇已解鎖的難度。難度會依照你的等級在 4、8、10、12、15 解鎖。",
            color=COLOR,
        )
        await interaction.response.send_message(
            view=v2_view_from_embed(
                embed,
                legacy_view=DomainView(store, str(interaction.user.id), domain, int(profile.get("level", 1))),
            ),
            ephemeral=True,
        )

    tree.add_command(pvp)
