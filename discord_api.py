"""Small Discord REST client used for target member/avatar lookup."""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config import TARGET_USER_ID, Config

LOGGER = logging.getLogger("fumao-worship-bot")


def read_user(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or not isinstance(value.get("id"), str) or not isinstance(value.get("username"), str):
        return None
    return {"id": value["id"], "username": value["username"], "globalName": value.get("global_name"), "avatar": value.get("avatar")}


def avatar_ext(avatar_hash: str) -> str:
    return "gif" if avatar_hash.startswith("a_") else "png"


def user_avatar_url(user: dict[str, Any]) -> str:
    if user.get("avatar"):
        return f"https://cdn.discordapp.com/avatars/{user['id']}/{user['avatar']}.{avatar_ext(user['avatar'])}?size=1024"
    return f"https://cdn.discordapp.com/embed/avatars/{(int(user['id']) >> 22) % 6}.png"


def member_avatar_url(guild_id: str, user: dict[str, Any], guild_avatar: str | None) -> str:
    if guild_avatar:
        return f"https://cdn.discordapp.com/guilds/{guild_id}/users/{user['id']}/avatars/{guild_avatar}.{avatar_ext(guild_avatar)}?size=1024"
    return user_avatar_url(user)


class DiscordApi:
    def __init__(self, config: Config, store: Any | None = None):
        self.config = config

    def get(self, path: str) -> tuple[bool, int, Any]:
        if not self.config.bot_token:
            return False, 0, None
        request = Request(f"https://discord.com/api/v10{path}", headers={"Authorization": f"Bot {self.config.bot_token}"})
        try:
            with urlopen(request, timeout=1.8) as response:
                try:
                    return True, response.status, json.loads(response.read())
                except json.JSONDecodeError:
                    return True, response.status, None
        except HTTPError as error:
            return False, error.code, None
        except (URLError, TimeoutError, OSError) as error:
            LOGGER.warning("Discord avatar lookup failed: %s", error)
            return False, 0, None

    def resolve_target(self, guild_id: str | None) -> tuple[str | None, str | None]:
        if not guild_id or not self.config.bot_token:
            return TARGET_USER_ID, None

        ok, _, body = self.get(f"/guilds/{guild_id}/members/{TARGET_USER_ID}")
        if ok and isinstance(body, dict):
            user = read_user(body.get("user"))
            if user:
                return TARGET_USER_ID, member_avatar_url(guild_id, user, body.get("avatar"))

        ok, _, body = self.get(f"/users/{TARGET_USER_ID}")
        if ok:
            user = read_user(body)
            if user:
                return TARGET_USER_ID, user_avatar_url(user)

        return TARGET_USER_ID, None
