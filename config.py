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
    data_file: str
    google_drive_client_file: str
    google_drive_token_file: str
    google_drive_folder_id: str
    google_drive_filename: str
    google_drive_backup_interval: int

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv(BOT_DIR / ".env")
        load_dotenv(ROOT / ".env")
        client_file = Path(
            os.getenv(
                "GOOGLE_DRIVE_OAUTH_CLIENT_FILE",
                str(BOT_DIR / "credentials" / "google_drives.json"),
            ).strip()
        )
        return cls(
            bot_token=first_environment_value("DISCORD_BOT_TOKEN", "DISCORD_TOKEN", "BOT_TOKEN", "TOKEN")
            .removeprefix("Bot ")
            .strip(),
            data_file=str(BOT_DIR / "database.db"),
            google_drive_client_file=str(client_file),
            google_drive_token_file=os.getenv(
                "GOOGLE_DRIVE_OAUTH_TOKEN_FILE",
                str(client_file.with_name("google_drive_token.json")),
            ).strip(),
            google_drive_folder_id=os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip(),
            google_drive_filename=os.getenv("GOOGLE_DRIVE_FILENAME", "database.db").strip()
            or "database.db",
            google_drive_backup_interval=_positive_int(
                os.getenv("GOOGLE_DRIVE_BACKUP_INTERVAL", "3600"),
                default=3600,
            ),
        )


def _positive_int(value: str, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
