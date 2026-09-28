"""Role-grant confirmation view."""

from __future__ import annotations

import discord


class GiveRoleConfirmView(discord.ui.View):
    def __init__(self, recipient: discord.Member, role: discord.Role) -> None:
        super().__init__(timeout=None)
        self.recipient = recipient
        self.role = role
        self.message: discord.Message | None = None
        self.resolved = False

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
        try:
            await self.recipient.add_roles(
                self.role,
                reason="User accepted an admin role grant request",
            )
        except discord.Forbidden:
            embed = discord.Embed(
                title="❌ 身分組給予失敗",
                description="機器人沒有管理這個身分組的權限，或身分組階級高於機器人。",
                color=0xE74C3C,
            )
        except discord.HTTPException:
            embed = discord.Embed(
                title="❌ 身分組給予失敗",
                description="Discord API 暫時無法完成這次操作。",
                color=0xE74C3C,
            )
        else:
            embed = discord.Embed(
                title="✅ 已接受身分組",
                description=f"{self.recipient.mention} 已接受 {self.role.mention}。",
                color=0x2ECC71,
            )

        try:
            await interaction.edit_original_response(embed=embed, view=None)
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
            description=f"{self.recipient.mention} 拒絕接受 {self.role.mention}。",
            color=0x95A5A6,
        )
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()
