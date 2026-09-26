"""SQLite storage for worship counts and avatar cache."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from commands.worship import next_streak, taipei_today


class WorshipStore:
    def __init__(self, data_file: str):
        self.path, legacy_path = self._resolve_path(data_file)
        self.lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        if legacy_path:
            self._migrate_json(legacy_path)

    @staticmethod
    def _resolve_path(data_file: str) -> tuple[Path, Path | None]:
        raw = (data_file or "data/worship.sqlite3").strip()
        if raw.startswith("sqlite:///"):
            raw = raw.removeprefix("sqlite:///")

        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = Path(__file__).resolve().parent / path

        # Keep old deployments safe: import an existing JSON file into SQLite.
        if path.suffix.lower() == ".json":
            legacy_path = path
            path = path.parent / "data" / "worship.sqlite3"
            return path, legacy_path if legacy_path.is_file() else None
        return path, None

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                INSERT OR IGNORE INTO metadata(key, value) VALUES ('total', '0');

                CREATE TABLE IF NOT EXISTS actors (
                    actor_id TEXT PRIMARY KEY,
                    streak INTEGER NOT NULL DEFAULT 0,
                    last_date TEXT
                );

                CREATE TABLE IF NOT EXISTS targets (
                    guild_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    avatar_url TEXT NOT NULL,
                    refreshed_at INTEGER NOT NULL
                );
                """
            )

    def _migrate_json(self, legacy_path: Path) -> None:
        try:
            value = json.loads(legacy_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"無法讀取舊 JSON 資料檔：{legacy_path}") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"舊 JSON 資料格式錯誤：{legacy_path}")

        actors = value.get("actors", {})
        targets = value.get("targets", {})
        with self.lock, self._connect() as connection:
            existing = connection.execute("SELECT COUNT(*) FROM actors").fetchone()[0]
            existing += connection.execute("SELECT COUNT(*) FROM targets").fetchone()[0]
            if existing:
                return
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES ('total', ?)",
                (str(int(value.get("total", 0))),),
            )
            if isinstance(actors, dict):
                for actor_id, row in actors.items():
                    if isinstance(row, dict):
                        connection.execute(
                            "INSERT OR REPLACE INTO actors(actor_id, streak, last_date) VALUES (?, ?, ?)",
                            (str(actor_id), int(row.get("streak", 0)), row.get("lastDate")),
                        )
            if isinstance(targets, dict):
                for guild_id, row in targets.items():
                    if isinstance(row, dict):
                        connection.execute(
                            """
                            INSERT OR REPLACE INTO targets(guild_id, user_id, avatar_url, refreshed_at)
                            VALUES (?, ?, ?, ?)
                            """,
                            (
                                str(guild_id),
                                str(row.get("userId", "")),
                                str(row.get("avatarUrl", "")),
                                int(row.get("refreshedAt", 0)),
                            ),
                        )

    def total(self) -> int:
        with self.lock, self._connect() as connection:
            row = connection.execute("SELECT value FROM metadata WHERE key = 'total'").fetchone()
            return int(row[0]) if row else 0

    def latest_avatar(self) -> str | None:
        with self.lock, self._connect() as connection:
            row = connection.execute(
                "SELECT avatar_url FROM targets ORDER BY refreshed_at DESC LIMIT 1"
            ).fetchone()
            return row[0] if row else None

    def board(self) -> dict[str, Any]:
        with self.lock, self._connect() as connection:
            total_row = connection.execute("SELECT value FROM metadata WHERE key = 'total'").fetchone()
            avatar_row = connection.execute(
                "SELECT avatar_url FROM targets ORDER BY refreshed_at DESC LIMIT 1"
            ).fetchone()
            return {
                "total": int(total_row[0]) if total_row else 0,
                "avatarUrl": avatar_row[0] if avatar_row else None,
            }

    def apply_worship(self, actor_id: str, display_name: str) -> dict[str, Any]:
        with self.lock, self._connect() as connection:
            row = connection.execute(
                "SELECT streak, last_date FROM actors WHERE actor_id = ?",
                (actor_id,),
            ).fetchone()
            old_streak = int(row[0]) if row else 0
            last_date = row[1] if row else None
            today = taipei_today()
            next_value, counted = next_streak(last_date, old_streak, today)

            if counted:
                connection.execute(
                    """
                    INSERT INTO actors(actor_id, streak, last_date) VALUES (?, ?, ?)
                    ON CONFLICT(actor_id) DO UPDATE SET streak = excluded.streak, last_date = excluded.last_date
                    """,
                    (actor_id, next_value, today),
                )
                connection.execute(
                    "UPDATE metadata SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) WHERE key = 'total'"
                )

            total_row = connection.execute("SELECT value FROM metadata WHERE key = 'total'").fetchone()
            return {
                "displayName": display_name,
                "total": int(total_row[0]) if total_row else 0,
                "streak": next_value,
                "counted": counted,
            }

    def read_target(self, guild_id: str) -> dict[str, Any] | None:
        with self.lock, self._connect() as connection:
            row = connection.execute(
                "SELECT user_id, avatar_url, refreshed_at FROM targets WHERE guild_id = ?",
                (guild_id,),
            ).fetchone()
            if not row:
                return None
            return {"userId": row[0], "avatarUrl": row[1], "refreshedAt": row[2]}

    def save_target(self, guild_id: str, user_id: str, avatar_url: str, refreshed_at: int) -> None:
        with self.lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO targets(guild_id, user_id, avatar_url, refreshed_at) VALUES (?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    avatar_url = excluded.avatar_url,
                    refreshed_at = excluded.refreshed_at
                """,
                (guild_id, user_id, avatar_url, refreshed_at),
            )
