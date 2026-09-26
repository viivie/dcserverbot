"""Trusted prefix commands for the bot administrator."""

from __future__ import annotations

import re

import discord

from commands.master import get_active_view


ADMIN_USER_ID = "1246096914634510417"
BUTTON_PATTERN = re.compile(r"^&button\s+(\d+)\s+(\d+)\s*$", re.IGNORECASE)


async def handle_admin_message(message: discord.Message) -> bool:
    """Handle one message and return whether it was an admin command."""
    if message.author.bot or str(message.author.id) != ADMIN_USER_ID:
        return False

    content = message.content.strip()

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
            await message.channel.send("找不到這個訊息的有效按鈕。")
            return True

        try:
            await view.admin_press(button_number)
        except ValueError as error:
            await message.channel.send(str(error))
            return True

        return True

    return False
