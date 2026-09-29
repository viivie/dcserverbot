"""SQL command confirmation and result formatting."""

from __future__ import annotations

import asyncio
import re
import sqlite3
from typing import Any

import discord

from components_v2 import v2_view_from_embed


class SqlConfirmView(discord.ui.View):
    def __init__(self, requester_id: int, store: Any, statement: str) -> None:
        super().__init__(timeout=60)
        self.requester_id = requester_id
        self.store = store
        self.statement = statement
        self.message: discord.Message | None = None
        self.resolved = False

    async def _deny_other_user(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.requester_id:
            return False
        await interaction.response.send_message("這不是你發起的資料庫操作喔😡", ephemeral=True)
        return True

    @discord.ui.button(label="確認執行", style=discord.ButtonStyle.danger)
    async def confirm_callback(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if await self._deny_other_user(interaction):
            return
        if self.resolved:
            await interaction.response.send_message("這個資料庫操作已經處理過了。", ephemeral=True)
            return

        self.resolved = True
        try:
            await interaction.response.defer()
        except discord.NotFound:
            return
        try:
            result = await asyncio.to_thread(self.store.execute_sql, self.statement)
            embed = sql_result_embed(result)
        except sqlite3.Error as error:
            embed = discord.Embed(
                title="❌ SQL 執行失敗",
                description=str(error)[:3600],
                color=0xE74C3C,
            )
        try:
            await interaction.edit_original_response(view=v2_view_from_embed(embed))
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
            await interaction.response.send_message("這個資料庫操作已經處理過了。", ephemeral=True)
            return

        self.resolved = True
        embed = discord.Embed(
            title="已取消資料庫操作",
            description="沒有執行 SQL。",
            color=0x95A5A6,
        )
        await interaction.response.edit_message(view=v2_view_from_embed(embed))
        self.stop()

    async def on_timeout(self) -> None:
        if self.resolved or self.message is None:
            return
        self.resolved = True
        embed = discord.Embed(
            title="資料庫操作確認已過期",
            description="請重新使用 `&sql SQL語法`。",
            color=0x95A5A6,
        )
        try:
            await self.message.edit(view=v2_view_from_embed(embed))
        except discord.HTTPException:
            pass

    async def admin_press(self, button_number: int) -> None:
        """Run a SQL confirmation-card button through the admin command."""
        if self.resolved:
            raise ValueError("這個資料庫操作已經處理過了。")
        if button_number == 1:
            self.resolved = True
            try:
                result = await asyncio.to_thread(self.store.execute_sql, self.statement)
                embed = sql_result_embed(result)
            except sqlite3.Error as error:
                embed = discord.Embed(
                    title="❌ SQL 執行失敗",
                description=str(error)[:3600],
                    color=0xE74C3C,
                )
        elif button_number == 2:
            self.resolved = True
            embed = discord.Embed(
                title="已取消資料庫操作",
                description="沒有執行 SQL。",
                color=0x95A5A6,
            )
        else:
            raise ValueError("目前資料庫操作卡片只有第 1、2 顆按鈕")

        if self.message is not None:
            try:
                await self.message.edit(view=v2_view_from_embed(embed))
            except discord.NotFound:
                pass
        self.stop()


def is_read_only_sql(statement: str) -> bool:
    keyword = re.match(r"\s*([A-Za-z]+)", statement)
    return bool(keyword and keyword.group(1).upper() in {"SELECT", "EXPLAIN"})


def sql_result_embed(result: dict[str, Any]) -> discord.Embed:
    if result["type"] == "affected":
        rowcount = result["rowcount"]
        description = f"影響資料列：`{rowcount}`"
        if result["lastrowid"] is not None:
            description += f"\n最後新增 ID：`{result['lastrowid']}`"
        return discord.Embed(title="✅ SQL 執行完成", description=description, color=0x2ECC71)

    columns = result["columns"]
    rows = result["rows"]
    lines = ["欄位：" + " | ".join(columns)]
    for row in rows:
        lines.append(" | ".join("NULL" if value is None else str(value) for value in row))
    if result["has_more"]:
        lines.append("…（結果超過 50 筆，僅顯示前 50 筆）")
    # Components V2 adds the card title/field wrapper around this text.
    # Keep the description below Discord's 4000-character display limit.
    description = "\n".join(lines)[:3600] or "（查詢沒有結果）"
    return discord.Embed(title="✅ SQL 查詢結果", description=description, color=0x2ECC71)
