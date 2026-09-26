"""Trusted prefix commands for the bot administrator."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import discord

from commands.master import get_active_view


ADMIN_USER_ID = "1246096914634510417"
ID_PATTERN = re.compile(r"^\d{17,20}$")
BUTTON_PATTERN = re.compile(r"^\s*(\d+)\s+(\d+)\s*$", re.IGNORECASE)
PERMISSION_COMMANDS = frozenset({"say", "button", "snipe"})
OWNER_ONLY_COMMANDS = frozenset({"grant", "revoke", "perms"})
SNIPE_ALIASES = frozenset({"snipe", "deleted"})

COMMAND_INFO = {
    "help": ("查看自己可以使用的管理員指令（以私人訊息傳送）。", "&help"),
    "say": ("讓機器人在目前頻道發送指定內容。", "&say 內容"),
    "button": ("替指定認主訊息執行按鈕操作。", "&button 訊息ID 按鈕編號"),
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
        body = content[2:].lstrip()
        silent = True
    elif content.startswith("&"):
        body = content[1:].lstrip()
        silent = False
    else:
        return None

    if not body:
        return None

    parts = body.split(maxsplit=1)
    return _canonical_command(parts[0]), parts[1] if len(parts) == 2 else "", silent


def _help_text(store: Any, user_id: str, is_owner: bool) -> str:
    if is_owner:
        commands = ["help", "say", "button", "snipe", "grant", "revoke", "perms"]
    else:
        commands = ["help"] + [
            command for command in ("say", "button", "snipe")
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
                ).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
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
            + "。可授權：&say、&button、&snipe"
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
