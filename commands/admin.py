"""Trusted prefix commands for the bot administrator."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

import discord

from commands.master import get_active_view


ADMIN_USER_ID = "1246096914634510417"
UTC_PLUS_8 = timezone(timedelta(hours=8), name="UTC+8")
ID_PATTERN = re.compile(r"^\d{17,20}$")
BUTTON_PATTERN = re.compile(r"^\s*(\d+)\s+(\d+)\s*$", re.IGNORECASE)
PERMISSION_COMMANDS = frozenset({"say", "button", "snipe", "react", "delete", "give"})
OWNER_ONLY_COMMANDS = frozenset({"grant", "revoke", "perms"})
SNIPE_ALIASES = frozenset({"snipe", "deleted"})

COMMAND_INFO = {
    "help": ("查看自己可以使用的管理員指令（以私人訊息傳送）。", "&help"),
    "say": ("讓機器人在目前頻道發送指定內容。", "&say 內容（或 & 文字）"),
    "button": ("替指定認主訊息執行按鈕操作。", "&button 訊息ID 按鈕編號"),
    "react": ("讓機器人對指定訊息加上一個或多個反應。", "&react 訊息ID 表情 [表情...]"),
    "delete": ("刪除目前頻道最近的指定數量訊息。", "&delete 數量（最多 100）"),
    "give": ("要求使用者確認是否接受指定身分組。", "&give 身分組ID 人ID [備註]"),
    "snipe": ("查看目前頻道最近被刪除的訊息，最多 10 則。", "&snipe [數量 1-10]"),
    "grant": ("授權某個使用者使用一個或多個指令。", "&grant 使用者ID 指令 [指令...]"),
    "revoke": ("撤銷某個使用者的一個或多個指令權限。", "&revoke 使用者ID 指令 [指令...]"),
    "perms": ("查看某個使用者目前被授權的指令。", "&perms 使用者ID"),
}


def _canonical_command(command: str) -> str:
    command = command.strip().lower().lstrip("&")
    return "snipe" if command in SNIPE_ALIASES else command


def _parse_prefix(content: str) -> tuple[str, str, bool] | None:
    content = content.strip()
    if content.startswith("&!"):
        raw_body = content[2:]
        silent = True
    elif content.startswith("&"):
        raw_body = content[1:]
        silent = False
    else:
        return None

    shorthand = not raw_body or raw_body[:1].isspace()
    body = raw_body.lstrip()
    if not body:
        return "say", "", silent

    parts = body.split(maxsplit=1)
    command = _canonical_command(parts[0])
    if command in COMMAND_INFO:
        return command, parts[1] if len(parts) == 2 else "", silent

    # Shorthand: & 文字 / &! 文字 are both equivalent to say.
    return ("say", body, silent) if shorthand else None


def _help_text(store: Any, user_id: str, is_owner: bool) -> str:
    if is_owner:
        commands = ["help", "say", "button", "react", "snipe", "delete", "give", "grant", "revoke", "perms"]
    else:
        commands = ["help"] + [
            command for command in ("say", "button", "react", "snipe", "delete", "give")
            if store.has_prefix_command(user_id, command)
        ]

    lines = ["管理員指令列表", ""]
    for command in commands:
        description, syntax = COMMAND_INFO[command]
        lines.extend((f"&{command}", description, f"語法：{syntax}", ""))

    if not is_owner:
        lines.extend(("可用的按鈕編號：1 = 接受，2 = 拒絕", ""))
    return "\n".join(lines).rstrip()


def _has_permission(store: Any, user_id: str, command: str) -> bool:
    if user_id == ADMIN_USER_ID:
        return True
    if command == "help":
        return bool(store.list_prefix_commands(user_id))
    if command in OWNER_ONLY_COMMANDS:
        return False
    return store.has_prefix_command(user_id, command)


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
        await interaction.response.send_message(
            "這不是你發起的刪除確認喔😡",
            ephemeral=True,
        )
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
        deleted_count = await self._delete_recent_messages()
        embed = discord.Embed(
            title="✅ 訊息刪除完成",
            description=(
                f"頻道：{getattr(self.channel, 'mention', self.channel)}\n"
                f"已刪除 **{deleted_count}** 則訊息。"
            ),
            color=0x2ECC71,
        )
        await interaction.response.edit_message(embed=embed, view=None)
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
        await interaction.response.send_message(
            "這不是給你的身分組喔😡",
            ephemeral=True,
        )
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

        await interaction.response.edit_message(embed=embed, view=None)
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

async def handle_admin_message(message: discord.Message, store: Any) -> bool:
    """Handle one permitted prefix command and return whether it was handled."""
    if message.author.bot:
        return False

    parsed = _parse_prefix(message.content)
    if parsed is None:
        return False

    command, arguments, silent = parsed
    if command not in COMMAND_INFO:
        return False

    user_id = str(message.author.id)
    is_owner = user_id == ADMIN_USER_ID
    if not _has_permission(store, user_id, command):
        return False

    try:
        if command == "help":
            await message.author.send(_help_text(store, user_id, is_owner))
            return True

        if command == "say":
            text = arguments.strip()
            if not text:
                await message.channel.send("用法：&say 內容")
                return True
            await message.channel.send(
                text,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return True

        if command == "button":
            match = BUTTON_PATTERN.fullmatch(arguments)
            if not match:
                await message.channel.send("用法：&button 訊息ID 按鈕編號")
                return True

            message_id = int(match.group(1))
            button_number = int(match.group(2))
            view = get_active_view(message_id)
            if view is None:
                await message.author.send("找不到這個訊息的有效按鈕。")
                return True

            try:
                await view.admin_press(button_number)
            except ValueError as error:
                await message.channel.send(str(error))
            return True

        if command == "react":
            values = arguments.split()
            if len(values) < 2 or not values[0].isdigit():
                await message.channel.send("用法：&react 訊息ID 表情 [表情...]")
                return True

            target_message_id = int(values[0])
            emojis = values[1:]
            try:
                target_message = await message.channel.fetch_message(target_message_id)
                for emoji in emojis:
                    await target_message.add_reaction(emoji)
            except discord.NotFound:
                await message.channel.send("找不到指定的訊息。")
                return True
            except discord.Forbidden:
                await message.channel.send("機器人沒有讀取訊息或新增反應的權限。")
                return True
            except discord.HTTPException as error:
                await message.channel.send(f"新增反應失敗：{error}")
                return True

            await message.channel.send(
                f"已對訊息 {target_message_id} 加上反應：{' '.join(emojis)}",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return True

        if command == "delete":
            if not arguments.strip().isdigit():
                await message.channel.send("用法：&delete 數量（最多 100）")
                return True

            count = int(arguments.strip())
            if count < 1 or count > 100:
                await message.channel.send("刪除數量必須介於 1 到 100。")
                return True

            embed = discord.Embed(
                title="⚠️ 確認刪除訊息",
                description=(
                    f"頻道：{getattr(message.channel, 'mention', message.channel)}\n"
                    f"將刪除最近的 **{count}** 則訊息。\n\n"
                    "確認後無法復原，是否繼續？"
                ),
                color=0xE74C3C,
            )
            view = DeleteConfirmView(message.author.id, message.channel, count)
            confirmation = await message.channel.send(
                embed=embed,
                view=view,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            view.message = confirmation
            return True

        if command == "give":
            values = arguments.split(maxsplit=2)
            if (
                len(values) < 2
                or not ID_PATTERN.fullmatch(values[0])
                or not ID_PATTERN.fullmatch(values[1])
            ):
                await message.channel.send("用法：&give 身分組ID 人ID [備註]")
                return True

            role_id = int(values[0])
            member_id = int(values[1])
            note = values[2].strip()[:1000] if len(values) == 3 else ""
            if message.guild is None:
                await message.channel.send("這個指令只能在伺服器頻道使用。")
                return True

            role = message.guild.get_role(role_id)
            if role is None:
                await message.channel.send("找不到指定的身分組。")
                return True
            if role.is_default() or role.managed:
                await message.channel.send("這個身分組不能由機器人給予。")
                return True
            if message.guild.me is not None and role >= message.guild.me.top_role:
                await message.channel.send("這個身分組的階級高於或等於機器人，無法給予。")
                return True

            member = message.guild.get_member(member_id)
            if member is None:
                try:
                    member = await message.guild.fetch_member(member_id)
                except discord.NotFound:
                    await message.channel.send("找不到指定的使用者。")
                    return True
                except discord.HTTPException:
                    await message.channel.send("查詢使用者時發生錯誤。")
                    return True

            description = ""
            if note:
                quoted_note = "\n".join(f"> {line}" for line in note.splitlines())
                description += f"{quoted_note}\n\n"
            description += (
                f"你被授予了 {role.mention}\n"
                "你是否接受這個身分組？"
            )

            embed = discord.Embed(
                title="🎁 身分組給予確認",
                description=description,
                color=0xE7A0B4,
            )
            view = GiveRoleConfirmView(member, role)
            confirmation = await message.channel.send(
                content=member.mention,
                embed=embed,
                view=view,
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=True,
                    everyone=False,
                    replied_user=False,
                ),
            )
            view.message = confirmation
            return True

        if command == "snipe":
            try:
                limit = int(arguments.strip()) if arguments.strip() else 10
            except ValueError:
                await message.channel.send("用法：&snipe [數量 1-10]")
                return True

            if limit < 1 or limit > 10:
                await message.channel.send("&snipe 的數量必須介於 1 到 10。")
                return True

            deleted_messages = await _get_latest_deleted_messages(message, store, limit)
            if not deleted_messages:
                await message.channel.send("目前頻道沒有記錄到被刪除的訊息。")
                return True

            output_parts = []
            for index, deleted in enumerate(deleted_messages, start=1):
                content = deleted["content"] or "（無文字內容）"
                content = " ".join(content.split())
                if len(content) > 140:
                    content = content[:140] + "…"
                sent_at = datetime.fromtimestamp(
                    int(deleted["created_at"] or deleted["deleted_at"]) / 1000,
                    tz=timezone.utc,
                ).astimezone(UTC_PLUS_8).strftime("%Y-%m-%d %H:%M:%S %Z")
                attachment_mark = " [含附件]" if deleted["attachments"] else ""
                output_parts.append(
                    f"{index}. {sent_at}｜{deleted['author_name']}｜{content}{attachment_mark}"
                )
            output = "最近被刪除的訊息（傳送時間）\n" + "\n".join(output_parts)
            await message.channel.send(
                output[:1990],
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return True

        if command in {"grant", "revoke", "perms"}:
            await _handle_permission_command(message, store, command, arguments)
            return True
    finally:
        if silent:
            try:
                await message.delete()
            except discord.HTTPException:
                pass

    return False


async def _get_latest_deleted_messages(
    message: discord.Message,
    store: Any,
    limit: int,
) -> list[dict[str, Any]]:
    if message.guild is None:
        return []
    return await _run_in_thread(
        store.latest_deleted_messages,
        str(message.channel.id),
        limit,
    )


async def _handle_permission_command(
    message: discord.Message,
    store: Any,
    command: str,
    arguments: str,
) -> None:
    values = [value for value in re.split(r"[,\s]+", arguments.strip()) if value]

    if command == "perms":
        if len(values) != 1 or not ID_PATTERN.fullmatch(values[0]):
            await message.author.send("用法：&perms 使用者ID")
            return
        target_id = values[0]
        commands = store.list_prefix_commands(target_id)
        text = "、".join(f"&{name}" for name in commands) if commands else "目前沒有授權指令"
        await message.author.send(f"使用者 {target_id} 的權限：{text}")
        return

    if len(values) < 2 or not ID_PATTERN.fullmatch(values[0]):
        await message.author.send(
            f"用法：&{command} 使用者ID 指令 [指令...]"
        )
        return

    target_id = values[0]
    requested = [_canonical_command(value) for value in values[1:]]
    if command == "revoke" and requested == ["all"]:
        store.clear_prefix_commands(target_id)
        await message.author.send(f"已撤銷使用者 {target_id} 的所有可用指令。")
        return

    invalid = sorted(set(requested) - PERMISSION_COMMANDS)
    if invalid:
        await message.author.send(
            "不可授權的指令："
            + "、".join(f"&{name}" for name in invalid)
            + "。可授權：&say、&button、&react、&snipe、&delete、&give"
        )
        return

    changed = []
    for requested_command in dict.fromkeys(requested):
        if command == "grant":
            if store.grant_prefix_command(target_id, requested_command):
                changed.append(requested_command)
        elif store.revoke_prefix_command(target_id, requested_command):
            changed.append(requested_command)

    action = "授權" if command == "grant" else "撤銷"
    result = "、".join(f"&{name}" for name in changed) if changed else "沒有變更"
    await message.author.send(f"已{action}使用者 {target_id}：{result}")


async def _run_in_thread(function: Any, *args: Any) -> Any:
    import asyncio

    return await asyncio.to_thread(function, *args)
