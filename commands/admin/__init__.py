"""Trusted prefix commands for the bot administrator."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

import discord

from components_v2 import v2_view_from_embed
from commands.master import get_active_view, register_active_view
from commands.economy import CURRENCY_EMOJIS
from .cleanup import DeleteConfirmView
from .economy import money_log_view
from .bets import (
    get_bet_template,
    BetOpenView,
    resolve_bet_message,
    setup_bet_card,
    start_bet_message,
    stop_bet_message,
)
from .roles import GiveRoleConfirmView
from .sql import SqlConfirmView, is_read_only_sql, sql_result_embed


ADMIN_USER_ID = "1246096914634510417"
UTC_PLUS_8 = timezone(timedelta(hours=8), name="UTC+8")
ID_PATTERN = re.compile(r"^\d{17,20}$")
USER_MENTION_PATTERN = re.compile(r"^<@!?(\d{17,20})>$")
ROLE_MENTION_PATTERN = re.compile(r"^<@&(\d{17,20})>$")
BUTTON_PATTERN = re.compile(r"^\s*(\d+)\s+(\d+)\s*$", re.IGNORECASE)
GIVE_FORCE_WORDS = frozenset({"force", "forced", "強制", "直接"})
PERMISSION_COMMANDS = frozenset({"say", "button", "snipe", "react", "delete", "give", "give_role", "id", "response", "create-bet", "ban-bet", "start-bet", "stop-bet", "resolve-bet", "log"})
OWNER_ONLY_COMMANDS = frozenset({"grant", "revoke", "perms", "sql", "clear-pvp-cooldown"})
SNIPE_ALIASES = frozenset({"snipe", "deleted"})
MONEY_LOG_ALIASES = frozenset({"log", "money-log", "moneylog"})
STOP_BET_ALIASES = frozenset({"stop", "stop-bet"})
BAN_BET_ALIASES = frozenset({"ban-bet", "prohibit"})
CURRENCY_ALIASES = {
    "fumao": "fumao_coins",
    "fumaocoin": "fumao_coins",
    "fumao_coin": "fumao_coins",
    "芙帽幣": "fumao_coins",
    "coin": "fumao_coins",
    "crystal": "crystals",
    "crystals": "crystals",
    "水晶": "crystals",
    "grace": "grace",
    "神恩": "grace",
}

COMMAND_INFO = {
    "help": ("查看自己可以使用的管理員指令（以私人訊息傳送）。", "&help"),
    "say": ("讓機器人在目前頻道發送指定內容。", "&say 內容（或 & 文字）"),
    "button": ("替指定認主訊息執行按鈕操作。", "&button 訊息ID 按鈕編號"),
    "react": ("讓機器人對指定訊息加上一個或多個反應。", "&react 訊息ID 表情 [表情...]"),
    "delete": ("刪除目前頻道最近的指定數量訊息。", "&delete 數量（最多 100）"),
    "give": (
        "直接發放芙帽幣、水晶或神恩給指定使用者，也可發給所有已建立經濟帳戶的使用者。",
        "&give 使用者ID 貨幣種類 數量（全部：&give all 貨幣種類 數量）",
    ),
    "create-bet": (
        "以私人表單建立賭盤，可套用模板並選擇是否立即開放下注。",
        "&create-bet [模板編號] [需要之後 start-bet 的任意文字]",
    ),
    "ban-bet": (
        "禁止指定使用者下注賭盤中的指定選項。",
        "&ban-bet [賭盤訊息ID] @使用者... 選項[,選項...]（省略 ID 則使用目前頻道最新賭盤）",
    ),
    "resolve-bet": (
        "結算賭盤；可同時指定多個結果，使用 return 會退還所有押注。",
        "&resolve-bet 訊息ID 狀況[,狀況...]（退款：return）",
    ),
    "stop-bet": (
        "立即停止賭盤下注並停用原卡片上的所有下注按鈕。",
        "&stop [訊息ID]（省略則使用目前頻道最新賭盤）",
    ),
    "start-bet": (
        "開放尚未開始下注的賭盤。",
        "&start-bet [訊息ID]（省略則使用目前頻道最新賭盤）",
    ),
    "log": (
        "查看某人最近 3 天的貨幣變動紀錄。",
        "&log 使用者ID（也可使用 @使用者）",
    ),
    "give_role": (
        "給予一個或多個身分組；一般模式需要對方同意，force 模式直接給予。",
        "&give_Role 身分組ID[,身分組ID...] 人ID [備註]（強制：&give_Role force 身分組ID[,身分組ID...] 人ID [備註]）",
    ),
    "id": ("取得被提及的使用者或身分組 ID。", "&id @使用者或 @身分組"),
    "response": ("回覆目前頻道中的指定訊息。", "&response 訊息ID 回覆內容"),
    "sql": ("查詢或操作機器人的 SQLite 資料庫（原始管理員限定，預設私訊回傳）。", "&sql SQL語法（公開：&^sql SQL語法）"),
    "snipe": ("查看目前頻道最近被刪除的訊息，最多 10 則。", "&snipe [數量 1-10]"),
    "grant": ("授權某個使用者使用一個或多個指令。", "&grant 使用者ID 指令 [指令...]"),
    "revoke": ("撤銷某個使用者的一個或多個指令權限。", "&revoke 使用者ID 指令 [指令...]"),
    "perms": ("查看某個使用者目前被授權的指令。", "&perms 使用者ID"),
    "clear-pvp-cooldown": (
        "清除一個或多個使用者的 PvP 一般／強制冷卻。",
        "&clear-pvp-cooldown 使用者ID [使用者ID...]（全部：all）",
    ),
}


def _canonical_command(command: str) -> str:
    command = command.strip().lower().lstrip("&")
    if command in SNIPE_ALIASES:
        return "snipe"
    if command in MONEY_LOG_ALIASES:
        return "log"
    if command in STOP_BET_ALIASES:
        return "stop-bet"
    if command in BAN_BET_ALIASES:
        return "ban-bet"
    return command


def _parse_prefix(content: str) -> tuple[str, str, bool, bool] | None:
    content = content.strip()
    if content.startswith("&!"):
        raw_body = content[2:]
        silent = True
        public = False
    elif content.startswith("&^"):
        raw_body = content[2:]
        silent = False
        public = True
    elif content.startswith("&"):
        raw_body = content[1:]
        silent = False
        public = False
    else:
        return None

    shorthand = not raw_body or raw_body[:1].isspace()
    body = raw_body.lstrip()
    if not body:
        return ("say", "", silent, public) if not public else None

    parts = body.split(maxsplit=1)
    command = _canonical_command(parts[0])
    if command in COMMAND_INFO and (not public or command == "sql"):
        return command, parts[1] if len(parts) == 2 else "", silent, public

    # Shorthand: & 文字 / &! 文字 are both equivalent to say.
    return ("say", body, silent, public) if shorthand and not public else None


def _help_text(store: Any, user_id: str, is_owner: bool) -> str:
    if is_owner:
        commands = ["help", "say", "button", "react", "snipe", "delete", "give", "give_role", "create-bet", "ban-bet", "start-bet", "stop-bet", "resolve-bet", "log", "id", "response", "sql", "grant", "revoke", "perms", "clear-pvp-cooldown"]
    else:
        commands = ["help"] + [
            command for command in ("say", "button", "react", "snipe", "delete", "give", "give_role", "create-bet", "ban-bet", "start-bet", "stop-bet", "resolve-bet", "log", "id", "response")
            if (
                store.has_prefix_command(user_id, command)
                or command == "log"
                and store.has_prefix_command(user_id, "money-log")
                or command == "ban-bet"
                and store.has_prefix_command(user_id, "prohibit")
            )
        ]

    lines = ["管理員指令列表", ""]
    for command in commands:
        description, syntax = COMMAND_INFO[command]
        display_command = "give_Role" if command == "give_role" else command
        lines.extend((f"&{display_command}", description, f"語法：{syntax}", ""))

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
    if command == "log":
        return store.has_prefix_command(user_id, "log") or store.has_prefix_command(
            user_id, "money-log"
        )
    if command == "ban-bet":
        return store.has_prefix_command(user_id, "ban-bet") or store.has_prefix_command(
            user_id, "prohibit"
        )
    return store.has_prefix_command(user_id, command)


def _parse_give_arguments(
    arguments: str,
) -> tuple[bool, list[str], str, str] | None:
    """Parse role IDs, member ID, optional note, and the force flag.

    The member ID is the last ID in the initial ID sequence, which allows both
    ``role member`` and ``role1 role2 member`` forms. Comma-separated roles are
    also supported with ``role1,role2 member``.
    """
    values = arguments.split()
    if values and values[0].lower() in GIVE_FORCE_WORDS:
        force = True
        values.pop(0)
    else:
        force = False

    if len(values) < 2:
        return None

    if any(separator in values[0] for separator in (",", "+", ";")):
        role_ids = [
            role_id
            for role_id in re.split(r"[,;+]", values[0])
            if role_id
        ]
        if (
            not role_ids
            or any(not ID_PATTERN.fullmatch(role_id) for role_id in role_ids)
            or not ID_PATTERN.fullmatch(values[1])
        ):
            return None
        return force, list(dict.fromkeys(role_ids)), values[1], " ".join(values[2:])[:1000]

    leading_ids = []
    for value in values:
        if not ID_PATTERN.fullmatch(value):
            break
        leading_ids.append(value)

    if len(leading_ids) < 2:
        return None
    note = " ".join(values[len(leading_ids):])[:1000]
    return (
        force,
        list(dict.fromkeys(leading_ids[:-1])),
        leading_ids[-1],
        note,
    )


def _currency_name(value: str) -> str | None:
    return CURRENCY_ALIASES.get(value.strip().casefold())


def _parse_ban_bet_arguments(
    arguments: str,
) -> tuple[str | None, list[str], list[str]] | None:
    values = arguments.split()
    if not values:
        return None

    message_id = None
    if ID_PATTERN.fullmatch(values[0]):
        message_id = values.pop(0)
    user_ids: list[str] = []
    index = 0
    while index < len(values):
        match = USER_MENTION_PATTERN.fullmatch(values[index])
        if match is None:
            break
        user_ids.append(match.group(1))
        index += 1

    if not user_ids or index >= len(values):
        return None
    option_names = [
        option.strip()
        for option in re.split(r"[,，]+", " ".join(values[index:]))
        if option.strip()
    ]
    if not option_names:
        return None
    return message_id, list(dict.fromkeys(user_ids)), list(dict.fromkeys(option_names))


async def _send_sql_message(
    message: discord.Message,
    public: bool,
    **kwargs: Any,
) -> discord.Message | None:
    destination = message.channel if public else message.author
    try:
        return await destination.send(**kwargs)
    except discord.Forbidden:
        if not public:
            await message.channel.send(
                "無法傳送 SQL 私訊，請先開啟接收伺服器成員私訊。",
                allowed_mentions=discord.AllowedMentions.none(),
            )
        return None


async def handle_admin_message(message: discord.Message, store: Any) -> bool:
    """Handle one permitted prefix command and return whether it was handled."""
    if message.author.bot:
        return False

    parsed = _parse_prefix(message.content)
    if parsed is None:
        return False

    command, arguments, silent, public = parsed
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

        if command == "id":
            argument = arguments.strip()
            role_match = ROLE_MENTION_PATTERN.fullmatch(argument)
            user_match = USER_MENTION_PATTERN.fullmatch(argument)
            if role_match:
                target_type = "身分組"
                target_id = role_match.group(1)
            elif user_match:
                target_type = "使用者"
                target_id = user_match.group(1)
            else:
                await message.channel.send(
                    "用法：&id @使用者 或 &id @身分組",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return True

            await message.channel.send(
                f"{target_type} ID：`{target_id}`",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return True

        if command == "response":
            values = arguments.split(maxsplit=1)
            if (
                len(values) < 2
                or not ID_PATTERN.fullmatch(values[0])
                or not values[1].strip()
            ):
                await message.channel.send(
                    "用法：&response 訊息ID 回覆內容",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return True

            try:
                target_message = await message.channel.fetch_message(int(values[0]))
                await target_message.reply(
                    values[1].strip(),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.NotFound:
                await message.channel.send(
                    "找不到指定的訊息。",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.Forbidden:
                await message.channel.send(
                    "機器人沒有讀取或回覆這則訊息的權限。",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException:
                await message.channel.send(
                    "回覆訊息時發生錯誤。",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            return True

        if command == "create-bet":
            if message.guild is None:
                await message.author.send("賭盤只能在伺服器頻道建立。")
                return True
            values = arguments.split()
            template_id = None
            start_immediately = None
            if values:
                if not values[0].isdigit() or get_bet_template(int(values[0])) is None:
                    await message.channel.send(
                        "模板編號不存在。可用模板：1、2、3。",
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                    return True
                template_id = int(values[0])
            if len(values) > 2:
                await message.channel.send(
                    "用法：&create-bet [模板編號] [需要之後 start-bet 的任意文字]。",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return True
            if len(values) == 2:
                start_immediately = False
            await message.channel.send(
                view=setup_bet_card(
                    store,
                    message.channel,
                    str(message.guild.id),
                    template_id,
                    start_immediately,
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return True

        if command == "ban-bet":
            parsed_ban = _parse_ban_bet_arguments(arguments)
            if parsed_ban is None:
                await message.channel.send(
                    "用法：&ban-bet [賭盤訊息ID] @使用者... 選項[,選項...]",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return True
            bet_message_id, user_ids, option_names = parsed_ban
            if bet_message_id is None:
                bet_message_id = await _run_in_thread(
                    store.latest_bet_message_id,
                    str(message.channel.id),
                )
                if bet_message_id is None:
                    await message.channel.send(
                        "目前頻道找不到賭盤。",
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                    return True
            bet_details = await _run_in_thread(store.bet_details, bet_message_id)
            if bet_details is None:
                await message.channel.send(
                    "找不到這個賭盤。",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return True
            normalized_options = []
            for option_name in option_names:
                if option_name.isdigit():
                    option_index = int(option_name)
                    if not 1 <= option_index <= len(bet_details["options"]):
                        await message.channel.send(
                            f"賭盤選項編號 `{option_name}` 不存在。",
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
                        return True
                    option_name = bet_details["options"][option_index - 1][0]
                normalized_options.append(option_name)
            option_names = list(dict.fromkeys(normalized_options))
            try:
                added_count = await _run_in_thread(
                    store.prohibit_bet_options,
                    bet_message_id,
                    user_ids,
                    option_names,
                )
            except ValueError as error:
                await message.channel.send(
                    str(error),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return True

            embed = discord.Embed(
                title="🚫 賭盤下注限制已設定",
                description=(
                    f"賭盤訊息：`{bet_message_id}`\n"
                    f"使用者：{'、'.join(f'<@{user_id}>' for user_id in user_ids)}\n"
                    f"禁止選項：{'、'.join(option_names)}\n"
                    f"新增限制：**{added_count}** 項"
                ),
                color=0xE74C3C,
            )
            await message.channel.send(
                view=v2_view_from_embed(embed),
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False,
                    replied_user=False,
                ),
            )
            return True

        if command == "start-bet":
            message_id = arguments.strip()
            if not message_id:
                message_id = await _run_in_thread(
                    store.latest_bet_message_id,
                    str(message.channel.id),
                )
                if message_id is None:
                    await message.channel.send(
                        "目前頻道找不到賭盤。",
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                    return True
            elif not ID_PATTERN.fullmatch(message_id):
                await message.channel.send(
                    "用法：&start-bet [訊息ID]（省略則使用目前頻道最新賭盤）",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return True
            try:
                result_embed, result_view = await start_bet_message(message, store, message_id)
            except ValueError as error:
                await message.channel.send(
                    str(error),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return True
            result_embed.title = "▶️ 賭盤已開放下注"
            confirmation = await message.channel.send(
                view=v2_view_from_embed(result_embed, legacy_view=result_view),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            result_view.message = confirmation
            result_view.schedule_expiry()
            return True

        if command == "stop-bet":
            message_id = arguments.strip()
            if not message_id:
                message_id = await _run_in_thread(
                    store.latest_bet_message_id,
                    str(message.channel.id),
                )
                if message_id is None:
                    await message.channel.send(
                        "目前頻道找不到賭盤。",
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                    return True
            elif not ID_PATTERN.fullmatch(message_id):
                await message.channel.send(
                    "用法：&stop-bet [訊息ID]（省略則使用目前頻道最新賭盤）",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return True
            try:
                result_embed = await stop_bet_message(message, store, message_id)
            except ValueError as error:
                await message.channel.send(
                    str(error),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return True
            result_embed.title = "⏹️ 賭盤已停止下注"
            await message.channel.send(
                view=v2_view_from_embed(result_embed),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return True

        if command == "resolve-bet":
            values = arguments.split(maxsplit=1)
            if len(values) != 2 or not ID_PATTERN.fullmatch(values[0]) or not values[1].strip():
                await message.channel.send(
                    "用法：&resolve-bet 訊息ID 狀況[,狀況...]（退款請單獨使用 return）",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return True
            try:
                result_embed = await resolve_bet_message(
                    message,
                    store,
                    values[0],
                    values[1].strip(),
                )
            except ValueError as error:
                await message.channel.send(
                    str(error),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return True
            await message.channel.send(
                view=v2_view_from_embed(result_embed),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return True

        if command == "log":
            target = arguments.strip()
            mention_match = USER_MENTION_PATTERN.fullmatch(target)
            target_id = mention_match.group(1) if mention_match else target
            if not ID_PATTERN.fullmatch(target_id):
                await message.channel.send(
                    "用法：&log 使用者ID（也可使用 @使用者）",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return True

            logs = await _run_in_thread(store.economy_currency_logs, target_id)
            await message.channel.send(
                view=money_log_view(target_id, logs, str(message.author.id)),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return True

        if command == "sql":
            statement = arguments.strip()
            if not statement:
                await _send_sql_message(
                    message,
                    public,
                    content="用法：&sql SQL語法",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return True
            if len(statement) > 3000:
                await _send_sql_message(
                    message,
                    public,
                    content="SQL 語法不能超過 3000 個字元。",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return True

            if is_read_only_sql(statement):
                try:
                    result = await _run_in_thread(store.execute_sql, statement)
                    await _send_sql_message(
                        message,
                        public,
                        view=v2_view_from_embed(sql_result_embed(result)),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                except sqlite3.Error as error:
                    await _send_sql_message(
                        message,
                        public,
                        view=v2_view_from_embed(
                            discord.Embed(
                                title="❌ SQL 查詢失敗",
                                description=str(error)[:3600],
                                color=0xE74C3C,
                            )
                        ),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                return True

            preview = statement.replace("```", "` ` `")
            embed = discord.Embed(
                title="⚠️ 確認資料庫操作",
                description=(
                    "這個 SQL 可能會修改或刪除資料庫內容。\n"
                    "按下「確認執行」後才會執行，請先確認語法與影響範圍。"
                ),
                color=0xE74C3C,
            )
            embed.add_field(name="資料庫", value="`data/database.db`", inline=False)
            embed.add_field(name="SQL", value=f"```sql\n{preview}\n```", inline=False)
            view = SqlConfirmView(message.author.id, store, statement)
            confirmation = await _send_sql_message(
                message,
                public,
                view=v2_view_from_embed(embed, legacy_view=view),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            view.message = confirmation
            register_active_view(confirmation.id, view)
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
                view=v2_view_from_embed(embed, legacy_view=view),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            view.message = confirmation
            register_active_view(confirmation.id, view)
            return True

        if command == "give":
            values = arguments.split()
            all_users = bool(values and values[0].casefold() == "all")
            if len(values) != 3 or (not all_users and not ID_PATTERN.fullmatch(values[0])):
                await message.channel.send(
                    "用法：&give 使用者ID 貨幣種類 數量，或 &give all 貨幣種類 數量"
                )
                return True

            currency = _currency_name(values[1])
            if currency is None:
                await message.channel.send(
                    "貨幣種類只能是 FumaoCoin、Crystal 或 grace。"
                )
                return True
            try:
                amount = int(values[2].replace(",", ""))
            except ValueError:
                amount = 0
            if amount == 0 or abs(amount) > 9_000_000_000_000_000_000:
                await message.channel.send("數量必須介於 -9,000,000,000,000,000,000 到 9,000,000,000,000,000,000，且不可為 0。")
                return True

            labels = {
                "fumao_coins": ("芙帽幣", "FumaoCoin"),
                "crystals": ("水晶", "Crystal"),
                "grace": ("神恩", "grace"),
            }
            currency_label, emoji_name = labels[currency]
            emoji = CURRENCY_EMOJIS.get(emoji_name, f":{emoji_name}:")
            action_label = "給予" if amount > 0 else "扣除"
            display_amount = abs(amount)

            if all_users:
                try:
                    account_count = await _run_in_thread(
                        store.grant_economy_currency_all,
                        currency,
                        amount,
                    )
                except (OverflowError, ValueError):
                    await message.channel.send("發放貨幣失敗，請確認貨幣種類與數量。")
                    return True

                embed = discord.Embed(
                    title=f"✅ 全體貨幣{action_label}完成",
                    description=(
                        f"已{action_label} **{account_count}** 個經濟帳戶，每個帳戶 **{display_amount:,}** "
                        f"{currency_label} {emoji}。"
                    ),
                    color=0x2ECC71,
                )
                await message.channel.send(
                    view=v2_view_from_embed(embed),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return True

            try:
                account = await _run_in_thread(
                    store.grant_economy_currency,
                    values[0],
                    currency,
                    amount,
                )
            except (OverflowError, ValueError):
                await message.channel.send("發放貨幣失敗，請確認貨幣種類與數量。")
                return True

            changed_amount = abs(int(account.get("changed", amount)))
            embed = discord.Embed(
                title=f"✅ 貨幣{action_label}完成",
                description=(
                    f"已{action_label} <@{values[0]}> **{changed_amount:,}** {currency_label} {emoji}\n"
                    f"目前餘額：**{account[currency]:,}** {currency_label} {emoji}"
                ),
                color=0x2ECC71,
            )
            await message.channel.send(
                view=v2_view_from_embed(embed),
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False,
                    replied_user=False,
                ),
            )
            return True

        if command == "give_role":
            parsed_give = _parse_give_arguments(arguments)
            if parsed_give is None:
                await message.channel.send(
                    "用法：&give_Role 身分組ID[,身分組ID...] 人ID [備註]"
                )
                return True

            force, role_ids, member_id, note = parsed_give
            if force and not is_owner:
                await message.author.send("強制給予只能由原始管理員使用。")
                return True
            if message.guild is None:
                await message.channel.send("這個指令只能在伺服器頻道使用。")
                return True

            roles = []
            for role_id in role_ids:
                role = message.guild.get_role(int(role_id))
                if role is None:
                    await message.channel.send(f"找不到身分組 `{role_id}`。")
                    return True
                if role.is_default() or role.managed:
                    await message.channel.send(f"身分組 `{role_id}` 不能由機器人給予。")
                    return True
                if message.guild.me is not None and role >= message.guild.me.top_role:
                    await message.channel.send(
                        f"身分組 {role.mention} 的階級高於或等於機器人，無法給予。"
                    )
                    return True
                roles.append(role)

            member = message.guild.get_member(int(member_id))
            if member is None:
                try:
                    member = await message.guild.fetch_member(int(member_id))
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
                f"你被授予了 {'、'.join(role.mention for role in roles)}\n"
                "你是否接受這些身分組？"
            )

            if force:
                try:
                    await member.add_roles(
                        *roles,
                        reason="Admin force-granted role(s)",
                    )
                except discord.Forbidden:
                    embed = discord.Embed(
                        title="❌ 身分組強制給予失敗",
                        description="機器人沒有管理這些身分組的權限，或身分組階級高於機器人。",
                        color=0xE74C3C,
                    )
                except discord.HTTPException:
                    embed = discord.Embed(
                        title="❌ 身分組強制給予失敗",
                        description="Discord API 暫時無法完成這次操作。",
                        color=0xE74C3C,
                    )
                else:
                    result_description = (
                        f"已將 {'、'.join(role.mention for role in roles)} 給予 "
                        f"{member.mention}，不需要對方同意。"
                    )
                    if note:
                        quoted_note = "\n".join(f"> {line}" for line in note.splitlines())
                        result_description = f"{quoted_note}\n\n{result_description}"
                    embed = discord.Embed(
                        title="✅ 已強制給予身分組",
                        description=result_description,
                        color=0x2ECC71,
                    )
                await message.channel.send(
                    view=v2_view_from_embed(embed, content=member.mention),
                    allowed_mentions=discord.AllowedMentions(
                        users=True,
                        roles=True,
                        everyone=False,
                        replied_user=False,
                    ),
                )
                return True

            embed = discord.Embed(
                title="🎁 身分組給予確認",
                description=description,
                color=0xE7A0B4,
            )
            view = GiveRoleConfirmView(member, roles)
            confirmation = await message.channel.send(
                view=v2_view_from_embed(
                    embed,
                    content=member.mention,
                    legacy_view=view,
                ),
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=True,
                    everyone=False,
                    replied_user=False,
                ),
            )
            view.message = confirmation
            register_active_view(confirmation.id, view)
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

        if command == "clear-pvp-cooldown":
            values = [value for value in re.split(r"[,\s]+", arguments.strip()) if value]
            if not values:
                await message.channel.send(
                    "用法：&clear-pvp-cooldown 使用者ID [使用者ID...]（全部：all）",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return True

            if len(values) == 1 and values[0].casefold() == "all":
                cleared = await _run_in_thread(store.clear_pvp_cooldowns)
                await message.channel.send(
                    f"已清除所有 PvP 使用者的冷卻（共 **{cleared}** 個設定檔）。",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return True

            target_ids: list[str] = []
            for value in values:
                mention_match = USER_MENTION_PATTERN.fullmatch(value)
                target_id = mention_match.group(1) if mention_match else value
                if not ID_PATTERN.fullmatch(target_id):
                    await message.channel.send(
                        "使用者必須填寫 ID 或 @使用者；全部清除請使用 `all`。",
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                    return True
                target_ids.append(target_id)

            cleared = await _run_in_thread(
                store.clear_pvp_cooldowns,
                list(dict.fromkeys(target_ids)),
            )
            await message.channel.send(
                f"已清除指定使用者的 PvP 冷卻（共 **{cleared}** 個設定檔）。",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return True
    except discord.Forbidden:
        # A command can be read in a channel where the bot cannot send. Do not
        # let the failed error reply escape into on_message as an exception.
        try:
            await message.author.send(
                "機器人在目前頻道缺少發送訊息權限，請檢查頻道權限設定。"
            )
        except discord.HTTPException:
            pass
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
            + "。可授權：&say、&button、&react、&snipe、&delete、&give、&give_Role、&create-bet、&ban-bet、&start-bet、&stop、&resolve-bet、&log、&id、&response"
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
