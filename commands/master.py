"""Commands for accepting, viewing, and administrating multiple masters."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import discord

if TYPE_CHECKING:
    from commands.context import CommandContext


EMBED_COLOR = 0xE7A0B4
EMBED_TITLE = "認主"
ACTIVE_VIEWS: dict[int, "WorshipView"] = {}


def register_active_view(message_id: int, view: "WorshipView") -> None:
    """Remember an active master request by its Discord message ID."""
    ACTIVE_VIEWS[message_id] = view


def get_active_view(message_id: int) -> "WorshipView | None":
    view = ACTIVE_VIEWS.get(message_id)
    if view is None:
        return None
    if view.is_finished():
        ACTIVE_VIEWS.pop(message_id, None)
        return None
    return view


class WorshipView(discord.ui.View):
    def __init__(
        self,
        actor: discord.Member,
        target: discord.Member,
        store: Any,
        guild_id: str,
        timeout_seconds: int,
    ):
        super().__init__(timeout=timeout_seconds)

        self.actor = actor
        self.target = target
        self.store = store
        self.guild_id = guild_id
        self.expires_at = time.monotonic() + timeout_seconds
        self.message: discord.Message | None = None
        self.resolved = False

    @property
    def expired(self) -> bool:
        return time.monotonic() >= self.expires_at

    async def _reply_to_request(self, content: str) -> None:
        if self.message is None:
            return

        await self.message.reply(
            content=content,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
                replied_user=False,
            ),
        )

    async def on_timeout(self) -> None:
        if self.resolved:
            return

        self.resolved = True
        await self._reply_to_request(
            f"{self.target.mention}錯過了一個認主請求QwQ"
        )

    async def _resolve(self, button_number: int) -> str:
        if self.expired:
            self.resolved = True
            self.stop()
            return f"{self.target.mention}錯過了一個認主請求QwQ"

        if button_number == 1:
            content = await self._accept()
        elif button_number == 2:
            content = f"噢不，{self.target.mention} 拒絕了 {self.actor.mention} 的認主請求！😭😭😭"
        else:
            raise ValueError("目前認主卡片只有第 1、2 顆按鈕")

        self.resolved = True
        self.stop()
        return content

    async def _accept(self) -> str:
        added = await asyncio.to_thread(
            self.store.add_master,
            self.guild_id,
            str(self.actor.id),
            str(self.target.id),
        )

        if added:
            return f"{self.target.mention} 接受了 {self.actor.mention} 的認主請求！"
        return f"{self.actor.mention} 已經認 {self.target.mention} 為主人了。"

    @discord.ui.button(
        label="接受",
        style=discord.ButtonStyle.success,
    )
    async def accept_button_callback(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if interaction.user.id != self.target.id:
            await interaction.response.send_message(
                content="這不是你的認主請求喔😡",
                ephemeral=True,
            )
            return

        content = await self._resolve(1)
        await interaction.response.defer()
        await self._reply_to_request(content)

    @discord.ui.button(
        label="拒絕",
        style=discord.ButtonStyle.danger,
    )
    async def reject_button_callback(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if interaction.user.id != self.target.id:
            await interaction.response.send_message(
                content="這不是你的認主請求喔😡",
                ephemeral=True,
            )
            return

        content = await self._resolve(2)
        await interaction.response.defer()
        await self._reply_to_request(content)

    async def admin_press(self, button_number: int) -> None:
        """Run a button action for the trusted admin prefix command."""
        content = await self._resolve(button_number)
        await self._reply_to_request(content)


def register_master(
    tree: Any,
    discord_module: Any,
    app_commands: Any,
    context: CommandContext,
) -> None:
    @tree.command(name="master", description="向特定成員提出認主請求")
    @app_commands.guild_only()
    @app_commands.describe(
        target="想認作主人的成員",
        timeout="認主請求有效時間（秒，預設 300 秒）",
    )
    async def master(
        interaction: Any,
        target: discord.Member,
        timeout: int = 300,
    ) -> None:
        actor = interaction.user

        if interaction.client.user is not None and target.id == interaction.client.user.id:
            await interaction.response.send_message(
                "芙帽是偉大的存在，所以不會接受凡俗的認主請求。",
                ephemeral=True,
            )
            return

        if actor.id == target.id:
            await interaction.response.send_message(
                "不能認自己當主人😡",
                ephemeral=True,
            )
            return

        if timeout < 1 or timeout > 86400:
            await interaction.response.send_message(
                "認主時間必須介於 1 到 86400 秒之間。",
                ephemeral=True,
            )
            return

        embed = discord_module.Embed(
            title=EMBED_TITLE,
            description=(
                f"{actor.mention} 想認 {target.mention} 為主人! ❤️\n"
                f"你願意接受 {actor.mention} 的認主請求嗎？"
            ),
            color=EMBED_COLOR,
        )

        view = WorshipView(
            actor,
            target,
            context.store,
            str(interaction.guild_id),
            timeout,
        )
        await interaction.response.send_message(
            embed=embed,
            view=view,
            allowed_mentions=discord_module.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
                replied_user=False,
            ),
        )

        message = await interaction.original_response()
        view.message = message
        register_active_view(message.id, view)



# check_master command

    @tree.command(name="check_master", description="查看自己目前的奴隸與主人")
    @app_commands.guild_only()
    async def check_master(interaction: Any) -> None:
        guild_id = str(interaction.guild_id)
        actor_id = str(interaction.user.id)
        master_ids = await asyncio.to_thread(
            context.store.list_masters,
            guild_id,
            actor_id,
        )
        slave_ids = await asyncio.to_thread(
            context.store.list_slaves,
            guild_id,
            actor_id,
        )

        slave_text = (
            "、".join(f"<@{slave_id}>" for slave_id in slave_ids)
            if slave_ids
            else "你還沒有奴隸喔"
        )
        master_text = (
            "、".join(f"<@{master_id}>" for master_id in master_ids)
            if master_ids
            else "你還沒有主人喔"
        )

        await interaction.response.send_message(
            f"你的奴隸有\n{slave_text}\n-------------\n你的主人有\n{master_text}",
            ephemeral=True,
            allowed_mentions=discord_module.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
                replied_user=False,
            ),
        )
