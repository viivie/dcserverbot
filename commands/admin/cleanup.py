"""Confirmation view for deleting recent messages."""

from __future__ import annotations

from typing import Any

import discord


class DeleteConfirmView(discord.ui.View):
    def __init__(self, requester_id: int, channel: Any, count: int) -> None:
        super().__init__(timeout=60)
        self.requester_id = requester_id
        self.channel = channel
        self.count = count
        self.message: discord.Message | None = None
        self.resolved = False

    async def _deny_other_user(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.requester_id:
            return False
        await interaction.response.send_message("這不是你發起的刪除確認喔😡", ephemeral=True)
        return True

    @discord.ui.button(label="確認刪除", style=discord.ButtonStyle.danger)
    async def confirm_callback(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if await self._deny_other_user(interaction):
            return
        if self.resolved:
            await interaction.response.send_message("這個刪除請求已經處理過了。", ephemeral=True)
            return

        self.resolved = True
        try:
            await interaction.response.defer()
        except discord.NotFound:
            return
        deleted_count = await self._delete_recent_messages()
        embed = discord.Embed(
            title="✅ 訊息刪除完成",
            description=(
                f"頻道：{getattr(self.channel, 'mention', self.channel)}\n"
                f"已刪除 **{deleted_count}** 則訊息。"
            ),
            color=0x2ECC71,
        )
        try:
            await interaction.edit_original_response(embed=embed, view=None)
        except discord.NotFound:
            pass
        self.stop()

    @discord.ui.button(label="取消", style=discord.ButtonStyle.secondary)
    async def cancel_callback(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if await self._deny_other_user(interaction):
            return
        if self.resolved:
            await interaction.response.send_message("這個刪除請求已經處理過了。", ephemeral=True)
            return

        self.resolved = True
        embed = discord.Embed(
            title="已取消刪除",
            description=f"頻道：{getattr(self.channel, 'mention', self.channel)}",
            color=0x95A5A6,
        )
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()

    async def on_timeout(self) -> None:
        if self.resolved or self.message is None:
            return
        self.resolved = True
        embed = discord.Embed(
            title="刪除確認已過期",
            description="請重新使用 `&delete 數量`。",
            color=0x95A5A6,
        )
        try:
            await self.message.edit(embed=embed, view=None)
        except discord.HTTPException:
            pass

    async def _delete_recent_messages(self) -> int:
        if self.message is None:
            return 0

        messages = []
        async for candidate in self.channel.history(limit=self.count + 1):
            if candidate.id == self.message.id:
                continue
            messages.append(candidate)
            if len(messages) >= self.count:
                break

        if not messages:
            return 0

        try:
            if len(messages) == 1:
                await messages[0].delete()
            else:
                await self.channel.delete_messages(messages, reason="admin delete command")
        except discord.HTTPException:
            deleted_count = 0
            for message in messages:
                try:
                    await message.delete()
                    deleted_count += 1
                except discord.HTTPException:
                    pass
            return deleted_count
        return len(messages)
