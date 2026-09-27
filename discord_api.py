"""Small Discord REST client used for target member/avatar lookup."""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import ID_RE, TARGET_USER_ID, TARGET_USERNAME, Config
from storage import WorshipStore

LOGGER = logging.getLogger("fumao-worship-bot")
CACHE_MS = 60 * 60 * 1000


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
    def __init__(self, config: Config, store: WorshipStore):
        self.config = config
        self.store = store

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
        override = TARGET_USER_ID if ID_RE.fullmatch(TARGET_USER_ID) else None
        if not guild_id or not self.config.bot_token:
            return override, None
        now_ms = int(time.time() * 1000)
        cached = self.store.read_target(guild_id)
        if cached and now_ms - int(cached["refreshedAt"]) < CACHE_MS:
            return cached["userId"], cached["avatarUrl"]

        def remember(user_id: str, avatar_url: str) -> tuple[str, str]:
            self.store.save_target(guild_id, user_id, avatar_url, now_ms)
            return user_id, avatar_url

        if override or cached:
            user_id = override or cached["userId"]
            ok, _, body = self.get(f"/guilds/{guild_id}/members/{user_id}")
            if ok and isinstance(body, dict):
                user = read_user(body.get("user"))
                if user:
                    return remember(user["id"], member_avatar_url(guild_id, user, body.get("avatar")))
            ok, _, body = self.get(f"/users/{user_id}")
            if ok:
                user = read_user(body)
                if user:
                    return remember(user["id"], user_avatar_url(user))

        if not override:
            query = urlencode({"query": TARGET_USERNAME, "limit": 10})
            ok, status, body = self.get(f"/guilds/{guild_id}/members/search?{query}")
            if ok and isinstance(body, list):
                wanted = TARGET_USERNAME.lower()
                for item in body:
                    user = read_user(item.get("user")) if isinstance(item, dict) else None
                    if user and user["username"].lower() == wanted:
                        return remember(user["id"], member_avatar_url(guild_id, user, item.get("avatar")))
            elif status:
                LOGGER.warning("Discord member search failed: %s", status)

        return (cached["userId"], cached["avatarUrl"]) if cached else (override, None)
