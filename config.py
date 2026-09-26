"""Environment configuration and shared constants."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parent
ROOT = BOT_DIR.parent
TARGET_USERNAME = "ariel970927"
TARGET_USER_ID = "1146045542082809866"
ID_RE = re.compile(r"^\d{17,20}$")


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def first_environment_value(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def first_environment_name(*names: str) -> str:
    for name in names:
        if os.getenv(name, "").strip():
            return name
    return "none"


@dataclass(frozen=True)
class Config:
    bot_token: str
    guild_id: str
    target_username: str
    target_user_id: str
    data_file: str

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv(BOT_DIR / ".env")
        load_dotenv(ROOT / ".env")
        return cls(
            bot_token=first_environment_value("DISCORD_BOT_TOKEN", "DISCORD_TOKEN", "BOT_TOKEN", "TOKEN")
            .removeprefix("Bot ")
            .strip(),
            guild_id=os.getenv("DISCORD_GUILD_ID", "").strip(),
            target_username=os.getenv("DISCORD_TARGET_USERNAME", TARGET_USERNAME).strip().lstrip("@"),
            target_user_id=os.getenv("DISCORD_TARGET_USER_ID", TARGET_USER_ID).strip(),
            data_file=os.getenv(
                "DATA_FILE",
                os.getenv("WORSHIP_DATA_FILE", str(BOT_DIR / "data" / "worship.sqlite3")),
            ).strip(),
        )
