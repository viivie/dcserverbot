"""Trusted prefix commands for the bot administrator."""

from __future__ import annotations

import re

import discord

from commands.master import get_active_view


ADMIN_USER_ID = "1246096914634510417"
BUTTON_PATTERN = re.compile(r"^&button\s+(\d+)\s+(\d+)\s*$", re.IGNORECASE)
ADMIN_HELP = (
    "\u7ba1\u7406\u54e1\u6307\u4ee4\u5217\u8868\n\n"
    "&help\n"
    "\u986f\u793a\u9019\u4efd\u7ba1\u7406\u54e1\u6307\u4ee4\u8aaa\u660e\uff08\u672c\u8a0a\u606f\u4ee5\u79c1\u4eba\u8a0a\u606f\u50b3\u9001\uff09\u3002\n"
    "\u8a9e\u6cd5\uff1a&help\n\n"
    "&say\n"
    "\u8b93\u6a5f\u5668\u4eba\u5728\u76ee\u524d\u983b\u9053\u767c\u9001\u6307\u5b9a\u5167\u5bb9\u3002\n"
    "\u8a9e\u6cd5\uff1a&say \u5167\u5bb9\n\n"
    "&button\n"
    "\u66ff\u6307\u5b9a\u8a8d\u4e3b\u8a0a\u606f\u57f7\u884c\u6309\u9215\u64cd\u4f5c\u3002\n"
    "\u8a9e\u6cd5\uff1a&button \u8a0a\u606fID \u6309\u9215\u7de8\u865f\n"
    "\u6309\u9215\u7de8\u865f\uff1a1 = \u63a5\u53d7\uff0c2 = \u62d2\u7d55\n"
)


async def handle_admin_message(message: discord.Message) -> bool:
    """Handle one message and return whether it was an admin command."""
    if message.author.bot or str(message.author.id) != ADMIN_USER_ID:
        return False

    content = message.content.strip()

    if content.lower() == "&help":
        await message.author.send(ADMIN_HELP)
        return True

    if content.lower() == "&say" or content.lower().startswith("&say "):
        text = content[4:].lstrip()
        if not text:
            await message.channel.send("用法：`&say 內容`")
            return True

        await message.channel.send(
            text,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return True

    match = BUTTON_PATTERN.fullmatch(content)
    if match:
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

        return True

    return False
