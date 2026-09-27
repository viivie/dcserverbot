"""SQLite storage for worship counts and avatar cache."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
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

                CREATE TABLE IF NOT EXISTS prefix_command_permissions (
                    user_id TEXT NOT NULL,
                    command TEXT NOT NULL,
                    granted_at INTEGER NOT NULL,
                    PRIMARY KEY (user_id, command)
                );

                CREATE TABLE IF NOT EXISTS deleted_messages (
                    message_id TEXT PRIMARY KEY,
                    guild_id TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    author_id TEXT NOT NULL,
                    author_name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    attachments TEXT NOT NULL,
                    created_at INTEGER NOT NULL DEFAULT 0,
                    deleted_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_deleted_messages_channel_time
                    ON deleted_messages(channel_id, deleted_at DESC);

                CREATE TABLE IF NOT EXISTS master_relationships (
                    guild_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    master_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, actor_id, master_id)
                );
                """
            )
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(deleted_messages)")
            }
            if "created_at" not in columns:
                connection.execute(
                    "ALTER TABLE deleted_messages ADD COLUMN created_at INTEGER NOT NULL DEFAULT 0"
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

    def add_master(self, guild_id: str, actor_id: str, master_id: str) -> bool:
        """Record one accepted master relationship.

        Returns False when the same relationship already exists.
        """
        with self.lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO master_relationships(
                    guild_id, actor_id, master_id, created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (guild_id, actor_id, master_id, int(time.time() * 1000)),
            )
            return cursor.rowcount > 0

    def has_master_relationship(self, guild_id: str, actor_id: str, master_id: str) -> bool:
        with self.lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM master_relationships
                WHERE guild_id = ? AND actor_id = ? AND master_id = ?
                """,
                (guild_id, actor_id, master_id),
            ).fetchone()
            return row is not None

    def remove_master(self, guild_id: str, actor_id: str, master_id: str) -> bool:
        with self.lock, self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM master_relationships
                WHERE guild_id = ? AND actor_id = ? AND master_id = ?
                """,
                (guild_id, actor_id, master_id),
            )
            return cursor.rowcount > 0

    def list_masters(self, guild_id: str, actor_id: str) -> list[str]:
        with self.lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT master_id
                FROM master_relationships
                WHERE guild_id = ? AND actor_id = ?
                ORDER BY created_at ASC, master_id ASC
                """,
                (guild_id, actor_id),
            ).fetchall()
            return [str(row[0]) for row in rows]

    def list_slaves(self, guild_id: str, master_id: str) -> list[str]:
        with self.lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT actor_id
                FROM master_relationships
                WHERE guild_id = ? AND master_id = ?
                ORDER BY created_at ASC, actor_id ASC
                """,
                (guild_id, master_id),
            ).fetchall()
            return [str(row[0]) for row in rows]


    def grant_prefix_command(self, user_id: str, command: str) -> bool:
        with self.lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO prefix_command_permissions(user_id, command, granted_at)
                VALUES (?, ?, ?)
                """,
                (str(user_id), command.lower(), int(time.time() * 1000)),
            )
            return cursor.rowcount > 0

    def revoke_prefix_command(self, user_id: str, command: str) -> bool:
        with self.lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM prefix_command_permissions WHERE user_id = ? AND command = ?",
                (str(user_id), command.lower()),
            )
            return cursor.rowcount > 0

    def clear_prefix_commands(self, user_id: str) -> None:
        with self.lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM prefix_command_permissions WHERE user_id = ?",
                (str(user_id),),
            )

    def has_prefix_command(self, user_id: str, command: str) -> bool:
        with self.lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM prefix_command_permissions
                WHERE user_id = ? AND command = ?
                """,
                (str(user_id), command.lower()),
            ).fetchone()
            return row is not None

    def list_prefix_commands(self, user_id: str) -> list[str]:
        with self.lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT command
                FROM prefix_command_permissions
                WHERE user_id = ?
                ORDER BY command ASC
                """,
                (str(user_id),),
            ).fetchall()
            return [str(row[0]) for row in rows]

    def record_deleted_message(
        self,
        message_id: str,
        guild_id: str,
        channel_id: str,
        author_id: str,
        author_name: str,
        content: str,
        attachments: list[str],
        created_at: int,
    ) -> None:
        with self.lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO deleted_messages(
                    message_id, guild_id, channel_id, author_id, author_name,
                    content, attachments, created_at, deleted_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(message_id),
                    str(guild_id),
                    str(channel_id),
                    str(author_id),
                    str(author_name),
                    content,
                    json.dumps(attachments, ensure_ascii=False),
                    int(created_at),
                    int(time.time() * 1000),
                ),
            )
            connection.execute(
                """
                DELETE FROM deleted_messages
                WHERE message_id NOT IN (
                    SELECT message_id
                    FROM deleted_messages
                    ORDER BY deleted_at DESC, rowid DESC
                    LIMIT 500
                )
                """
            )

    def latest_deleted_messages(self, channel_id: str, limit: int = 1) -> list[dict[str, Any]]:
        with self.lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT author_id, author_name, content, attachments, created_at, deleted_at
                FROM deleted_messages
                WHERE channel_id = ?
                ORDER BY deleted_at DESC, rowid DESC
                LIMIT ?
                """,
                (str(channel_id), max(1, min(int(limit), 10))),
            ).fetchall()

            result = []
            for row in rows:
                try:
                    attachments = json.loads(row[3])
                except (TypeError, json.JSONDecodeError):
                    attachments = []
                if not isinstance(attachments, list):
                    attachments = []

                result.append(
                    {
                        "author_id": str(row[0]),
                        "author_name": str(row[1]),
                        "content": str(row[2]),
                        "attachments": [str(item) for item in attachments],
                        "created_at": int(row[4]),
                        "deleted_at": int(row[5]),
                    }
                )
            return result
