"""Compatibility routing for component buttons created before stable IDs."""

from __future__ import annotations

import asyncio
import re
from typing import Any, ClassVar

import discord

from commands.persistent import PersistentInteractionView


def _message_text(message: discord.Message) -> str:
    parts: list[str] = []

    def walk(component: Any) -> None:
        content = getattr(component, "content", None)
        if content:
            parts.append(str(content))
        for child in getattr(component, "children", ()) or ():
            walk(child)

    for component in getattr(message, "components", ()) or ():
        walk(component)
    return "\n".join(parts)


def _message_button_components(message: discord.Message) -> list[Any]:
    result: list[Any] = []

    def walk(component: Any) -> None:
        if getattr(component, "custom_id", None) is not None and (
            getattr(component, "label", None) is not None
            or getattr(component, "type", None) == discord.ComponentType.button
        ):
            result.append(component)
            return
        for child in getattr(component, "children", ()) or ():
            walk(child)

    for component in getattr(message, "components", ()) or ():
        walk(component)
    return result


class LegacyInteractionButtonItem(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"^[0-9a-f]{32}$",
):
    """Recover old UUID-based cards without creating a View per message."""

    store: ClassVar[Any] = None

    def __init__(self, item: discord.ui.Button) -> None:
        super().__init__(item)

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "LegacyInteractionButtonItem":
        return cls(item)

    async def callback(self, interaction: discord.Interaction) -> None:
        store = self.__class__.store
        message = interaction.message
        if store is None or message is None:
            await interaction.response.send_message(
                "這張卡片目前無法恢復，請重新建立互動。",
                ephemeral=True,
            )
            return

        message_id = str(message.id)
        bet = await asyncio.to_thread(store.bet_details, message_id)
        if bet is not None:
            await self._open_legacy_bet_modal(interaction, store, message, bet)
            return

        await self._resolve_legacy_confirmation(interaction, store, message)

    async def _open_legacy_bet_modal(
        self,
        interaction: discord.Interaction,
        store: Any,
        message: discord.Message,
        bet: dict[str, Any],
    ) -> None:
        from commands.admin.bets import _open_bet_modal

        buttons = _message_button_components(message)
        clicked_id = str(interaction.data.get("custom_id", ""))
        button_index = next(
            (
                index
                for index, button in enumerate(buttons)
                if str(getattr(button, "custom_id", "")) == clicked_id
            ),
            -1,
        )
        label = getattr(self.item, "label", None)
        option_name = next(
            (name for name, _ in bet["options"] if name == label),
            None,
        )
        if option_name is None and 0 <= button_index < len(bet["options"]):
            option_name = bet["options"][button_index][0]
        if option_name is None:
            await interaction.response.send_message("找不到這個下注選項。", ephemeral=True)
            return
        await _open_bet_modal(interaction, store, str(message.id), option_name)

    async def _resolve_legacy_confirmation(
        self,
        interaction: discord.Interaction,
        store: Any,
        message: discord.Message,
    ) -> None:
        text = _message_text(message)
        mentions = list(dict.fromkeys(re.findall(r"<@!?([0-9]{17,20})>", text)))
        role_ids = list(dict.fromkeys(re.findall(r"<@&([0-9]{17,20})>", text)))
        label = str(getattr(self.item, "label", "") or "")

        if "身分組" in text and mentions:
            kind = "role-grant"
            actor_id = None
            target_id = mentions[0]
            payload = {"role_ids": role_ids}
            accept_label = "接受給予"
        elif "解除契約" in text and len(mentions) >= 2:
            kind = "release"
            actor_id, target_id = mentions[0], mentions[1]
            payload = {}
            accept_label = "同意解除"
        elif "認主" in text and len(mentions) >= 2:
            kind = "master"
            actor_id, target_id = mentions[0], mentions[1]
            payload = {}
            accept_label = "接受"
        else:
            await interaction.response.send_message(
                "這張舊卡片沒有可恢復的互動資料，請重新建立。",
                ephemeral=True,
            )
            return

        if label != accept_label and not label.startswith("拒絕"):
            await interaction.response.send_message("找不到這個舊卡片按鈕。", ephemeral=True)
            return
        if str(interaction.user.id) != str(target_id):
            await interaction.response.send_message("這不是給你的互動請求喔😡", ephemeral=True)
            return

        try:
            await interaction.response.defer()
        except discord.NotFound:
            return

        handler = PersistentInteractionView(store)
        card = {
            "kind": kind,
            "guild_id": str(message.guild.id) if message.guild else "",
            "actor_id": actor_id,
            "target_id": target_id,
            "payload": payload,
        }
        action = "accept" if label == accept_label else "reject"
        if kind == "master":
            result = await handler._resolve_master(card, action, interaction)
        elif kind == "release":
            result = await handler._resolve_release(card, action)
        else:
            result = await handler._resolve_role_grant(card, action, interaction)
        await handler._edit_card(interaction, result[0], result[1], result[2])
