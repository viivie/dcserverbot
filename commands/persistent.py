"""Shared persistent handlers for long-lived Discord component cards."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import discord

from components_v2 import v2_view_from_embed


class PersistentInteractionView(discord.ui.View):
    """Resolve long-lived cards from ``interaction.message.id`` and SQLite."""

    def __init__(self, store: Any) -> None:
        super().__init__(timeout=None)
        self.store = store
        buttons = (
            ("master:accept", "接受", discord.ButtonStyle.success),
            ("master:reject", "拒絕", discord.ButtonStyle.danger),
            ("release:accept", "同意解除", discord.ButtonStyle.success),
            ("release:reject", "拒絕解除", discord.ButtonStyle.danger),
            ("role-grant:accept", "接受給予", discord.ButtonStyle.success),
            ("role-grant:reject", "拒絕", discord.ButtonStyle.danger),
        )
        for custom_id, label, style in buttons:
            button = discord.ui.Button(label=label, style=style, custom_id=custom_id)
            button.callback = self._make_callback(custom_id)
            self.add_item(button)

    def _make_callback(self, custom_id: str):
        async def callback(interaction: discord.Interaction) -> None:
            await self._handle(custom_id, interaction)

        return callback

    async def _handle(self, custom_id: str, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.defer()
        except discord.NotFound:
            return

        message = interaction.message
        if message is None:
            await interaction.followup.send("找不到這張互動卡片。", ephemeral=True)
            return

        card = await asyncio.to_thread(self.store.interaction_card, str(message.id))
        if card is None:
            await interaction.followup.send(
                "這張卡片沒有可恢復的資料，請重新建立互動。",
                ephemeral=True,
            )
            return

        kind, action = custom_id.split(":", 1)
        if card["kind"] != kind:
            await interaction.followup.send("這個按鈕不屬於目前的互動。", ephemeral=True)
            return
        if str(interaction.user.id) != str(card["target_id"]):
            await interaction.followup.send("這不是給你的互動請求喔😡", ephemeral=True)
            return

        now_ms = int(time.time() * 1000)
        if card["resolved_at"] is not None:
            await interaction.followup.send("這個互動請求已經處理過了。", ephemeral=True)
            return
        if card["expires_at"] is not None and now_ms >= int(card["expires_at"]):
            await asyncio.to_thread(self.store.resolve_interaction_card, str(message.id), now_ms)
            await self._edit_card(interaction, "互動已過期", "這個互動請求已經過期了。", 0x95A5A6)
            return

        claimed = await asyncio.to_thread(
            self.store.resolve_interaction_card,
            str(message.id),
            now_ms,
        )
        if not claimed:
            await interaction.followup.send("這個互動請求已經處理過了。", ephemeral=True)
            return

        if kind == "master":
            result = await self._resolve_master(card, action)
        elif kind == "release":
            result = await self._resolve_release(card, action)
        else:
            result = await self._resolve_role_grant(card, action, interaction)
        await self._edit_card(interaction, *result)

    async def _resolve_master(
        self,
        card: dict[str, Any],
        action: str,
    ) -> tuple[str, str, int]:
        actor = f"<@{card['actor_id']}>"
        target = f"<@{card['target_id']}>"
        if action == "accept":
            added = await asyncio.to_thread(
                self.store.add_master,
                card["guild_id"],
                str(card["actor_id"]),
                str(card["target_id"]),
            )
            description = (
                f"{target} 接受了 {actor} 的認主請求！"
                if added
                else f"{actor} 已經認 {target} 為主人了。"
            )
            return "認主完成", description, 0x2ECC71
        return "已拒絕認主", f"噢不，{target} 拒絕了 {actor} 的認主請求！😭😭😭", 0x95A5A6

    async def _resolve_release(
        self,
        card: dict[str, Any],
        action: str,
    ) -> tuple[str, str, int]:
        actor = f"<@{card['actor_id']}>"
        target = f"<@{card['target_id']}>"
        if action == "accept":
            removed = await asyncio.to_thread(
                self.store.remove_master,
                card["guild_id"],
                str(card["actor_id"]),
                str(card["target_id"]),
            )
            if not removed:
                removed = await asyncio.to_thread(
                    self.store.remove_master,
                    card["guild_id"],
                    str(card["target_id"]),
                    str(card["actor_id"]),
                )
            description = (
                f"{actor} 與 {target} 的主奴契約已解除。"
                if removed
                else "這段主奴契約已不存在，可能已經被解除。"
            )
            return "解除契約完成", description, 0x2ECC71
        return "已拒絕解除契約", f"{target} 拒絕了解除 {actor} 的主奴契約申請。", 0x95A5A6

    async def _resolve_role_grant(
        self,
        card: dict[str, Any],
        action: str,
        interaction: discord.Interaction,
    ) -> tuple[str, str, int]:
        member = interaction.guild.get_member(int(card["target_id"])) if interaction.guild else None
        if member is None and interaction.guild is not None:
            try:
                member = await interaction.guild.fetch_member(int(card["target_id"]))
            except discord.HTTPException:
                member = None
        role_ids = [int(role_id) for role_id in card["payload"].get("role_ids", [])]
        roles = [interaction.guild.get_role(role_id) for role_id in role_ids] if interaction.guild else []
        roles = [role for role in roles if role is not None]
        role_mentions = "、".join(role.mention for role in roles) or "指定身分組"
        if action == "reject":
            return "已拒絕身分組", f"<@{card['target_id']}> 拒絕接受 {role_mentions}。", 0x95A5A6
        if member is None or len(roles) != len(role_ids):
            return "❌ 身分組給予失敗", "找不到成員或身分組，請確認伺服器資料仍存在。", 0xE74C3C
        try:
            await member.add_roles(*roles, reason="User accepted an admin role grant request")
        except discord.Forbidden:
            return "❌ 身分組給予失敗", "機器人沒有管理這些身分組的權限，或身分組階級高於機器人。", 0xE74C3C
        except discord.HTTPException:
            return "❌ 身分組給予失敗", "Discord API 暫時無法完成這次操作。", 0xE74C3C
        return "✅ 已接受身分組", f"{member.mention} 已接受 {role_mentions}。", 0x2ECC71

    async def _edit_card(
        self,
        interaction: discord.Interaction,
        title: str,
        description: str,
        color: int,
    ) -> None:
        try:
            await interaction.edit_original_response(
                view=v2_view_from_embed(
                    discord.Embed(title=title, description=description, color=color)
                )
            )
        except discord.HTTPException:
            pass


def register_persistent_handlers(client: Any, store: Any) -> None:
    """Register shared persistent views and legacy routing during setup_hook."""
    from commands.admin.bets import register_persistent_bet_handlers
    from commands.legacy_components import LegacyInteractionButtonItem

    client.add_view(PersistentInteractionView(store))
    register_persistent_bet_handlers(client, store)
    LegacyInteractionButtonItem.store = store
    client.add_dynamic_items(LegacyInteractionButtonItem)
