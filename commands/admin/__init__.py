"""Trusted prefix commands for the bot administrator."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

import discord

from commands.master import get_active_view, register_active_view
from commands.economy import CURRENCY_EMOJIS
from .cleanup import DeleteConfirmView
from .roles import GiveRoleConfirmView
from .sql import SqlConfirmView, is_read_only_sql, sql_result_embed


ADMIN_USER_ID = "1246096914634510417"
UTC_PLUS_8 = timezone(timedelta(hours=8), name="UTC+8")
ID_PATTERN = re.compile(r"^\d{17,20}$")
USER_MENTION_PATTERN = re.compile(r"^<@!?(\d{17,20})>$")
ROLE_MENTION_PATTERN = re.compile(r"^<@&(\d{17,20})>$")
BUTTON_PATTERN = re.compile(r"^\s*(\d+)\s+(\d+)\s*$", re.IGNORECASE)
GIVE_FORCE_WORDS = frozenset({"force", "forced", "強制", "直接"})
PERMISSION_COMMANDS = frozenset({"say", "button", "snipe", "react", "delete", "give", "give_role", "id", "response"})
OWNER_ONLY_COMMANDS = frozenset({"grant", "revoke", "perms", "sql"})
SNIPE_ALIASES = frozenset({"snipe", "deleted"})
CURRENCY_ALIASES = {
    "fumao": "fumao_coins",
    "fumaocoin": "fumao_coins",
    "fumao_coin": "fumao_coins",
    "芙帽幣": "fumao_coins",
    "芙帽币": "fumao_coins",
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
        "直接發放芙帽幣、水晶或神恩給指定使用者。",
        "&give 使用者ID 貨幣種類 數量",
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
}


def _canonical_command(command: str) -> str:
    command = command.strip().lower().lstrip("&")
    return "snipe" if command in SNIPE_ALIASES else command


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
        commands = ["help", "say", "button", "react", "snipe", "delete", "give", "give_role", "id", "response", "sql", "grant", "revoke", "perms"]
    else:
        commands = ["help"] + [
            command for command in ("say", "button", "react", "snipe", "delete", "give", "give_role", "id", "response")
            if store.has_prefix_command(user_id, command)
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
                        embed=sql_result_embed(result),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                except sqlite3.Error as error:
                    await _send_sql_message(
                        message,
                        public,
                        embed=discord.Embed(
                            title="❌ SQL 查詢失敗",
                            description=str(error)[:4000],
                            color=0xE74C3C,
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
                embed=embed,
                view=view,
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
                embed=embed,
                view=view,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            view.message = confirmation
            register_active_view(confirmation.id, view)
            return True

        if command == "give":
            values = arguments.split()
            if len(values) != 3 or not ID_PATTERN.fullmatch(values[0]):
                await message.channel.send("用法：&give 使用者ID 貨幣種類 數量")
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
            if amount < 1 or amount > 9_000_000_000_000_000_000:
                await message.channel.send("發放數量必須介於 1 到 9,000,000,000,000,000,000。")
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

            labels = {
                "fumao_coins": ("芙帽幣", "FumaoCoin"),
                "crystals": ("水晶", "Crystal"),
                "grace": ("神恩", "grace"),
            }
            currency_label, emoji_name = labels[currency]
            emoji = CURRENCY_EMOJIS.get(emoji_name, f":{emoji_name}:")
            embed = discord.Embed(
                title="✅ 貨幣發放完成",
                description=(
                    f"已給予 <@{values[0]}> **{amount:,}** {currency_label} {emoji}\n"
                    f"目前餘額：**{account[currency]:,}** {currency_label} {emoji}"
                ),
                color=0x2ECC71,
            )
            await message.channel.send(
                embed=embed,
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
                    content=member.mention,
                    embed=embed,
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
            + "。可授權：&say、&button、&react、&snipe、&delete、&give、&give_Role、&id、&response"
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
