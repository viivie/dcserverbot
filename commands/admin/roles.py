"""Role-grant confirmation view."""

from __future__ import annotations

import discord

from components_v2 import v2_view_from_embed


class GiveRoleConfirmView(discord.ui.View):
    def __init__(
        self,
        recipient: discord.Member,
        roles: list[discord.Role] | tuple[discord.Role, ...],
    ) -> None:
        super().__init__(timeout=None)
        self.recipient = recipient
        self.roles = tuple(roles)
        self.message: discord.Message | None = None
        self.resolved = False

    @property
    def role_mentions(self) -> str:
        return "、".join(role.mention for role in self.roles)

    async def _grant_roles(self, reason: str) -> discord.Embed:
        try:
            await self.recipient.add_roles(*self.roles, reason=reason)
        except discord.Forbidden:
            return discord.Embed(
                title="❌ 身分組給予失敗",
                description="機器人沒有管理這些身分組的權限，或身分組階級高於機器人。",
                color=0xE74C3C,
            )
        except discord.HTTPException:
            return discord.Embed(
                title="❌ 身分組給予失敗",
                description="Discord API 暫時無法完成這次操作。",
                color=0xE74C3C,
            )
        return discord.Embed(
            title="✅ 已接受身分組",
            description=f"{self.recipient.mention} 已接受 {self.role_mentions}。",
            color=0x2ECC71,
        )

    async def _deny_other_user(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.recipient.id:
            return False
        await interaction.response.send_message("這不是給你的身分組喔😡", ephemeral=True)
        return True

    @discord.ui.button(label="接受給予", style=discord.ButtonStyle.success)
    async def accept_callback(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if await self._deny_other_user(interaction):
            return
        if self.resolved:
            await interaction.response.send_message("這個身分組請求已經處理過了。", ephemeral=True)
            return

        self.resolved = True
        try:
            await interaction.response.defer()
        except discord.NotFound:
            return
        embed = await self._grant_roles("User accepted an admin role grant request")

        try:
            await interaction.edit_original_response(view=v2_view_from_embed(embed))
        except discord.NotFound:
            pass
        self.stop()

    @discord.ui.button(label="拒絕", style=discord.ButtonStyle.danger)
    async def reject_callback(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if await self._deny_other_user(interaction):
            return
        if self.resolved:
            await interaction.response.send_message("這個身分組請求已經處理過了。", ephemeral=True)
            return

        self.resolved = True
        embed = discord.Embed(
            title="已拒絕身分組",
            description=f"{self.recipient.mention} 拒絕接受 {self.role_mentions}。",
            color=0x95A5A6,
        )
        await interaction.response.edit_message(view=v2_view_from_embed(embed))
        self.stop()

    async def admin_press(self, button_number: int) -> None:
        """Allow the trusted admin command to operate this confirmation card."""
        if self.resolved:
            raise ValueError("這個身分組請求已經處理過了。")
        if button_number == 1:
            embed = await self._grant_roles("Admin confirmed a role grant request")
        elif button_number == 2:
            embed = discord.Embed(
                title="已拒絕身分組",
                description=f"{self.recipient.mention} 拒絕接受 {self.role_mentions}。",
                color=0x95A5A6,
            )
        else:
            raise ValueError("目前身分組給予卡片只有第 1、2 顆按鈕")

        self.resolved = True
        if self.message is not None:
            await self.message.edit(view=v2_view_from_embed(embed))
        self.stop()
