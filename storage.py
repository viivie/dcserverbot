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
        self.path = self._resolve_path(data_file)
        self.lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @staticmethod
    def _resolve_path(data_file: str) -> Path:
        raw = (data_file or "data/database.db").strip()
        if raw.startswith("sqlite:///"):
            raw = raw.removeprefix("sqlite:///")

        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = Path(__file__).resolve().parent / path

        return path

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
                INSERT OR IGNORE INTO metadata(key, value)
                    VALUES ('give_role_permission_migrated', '0');

                CREATE TABLE IF NOT EXISTS actors (
                    actor_id TEXT PRIMARY KEY,
                    streak INTEGER NOT NULL DEFAULT 0,
                    last_date TEXT
                );

                CREATE TABLE IF NOT EXISTS economy_accounts (
                    user_id TEXT PRIMARY KEY,
                    fumao_coins INTEGER NOT NULL DEFAULT 0,
                    crystals INTEGER NOT NULL DEFAULT 0,
                    grace INTEGER NOT NULL DEFAULT 0,
                    level INTEGER NOT NULL DEFAULT 1,
                    last_daily_date TEXT,
                    last_hourly_at INTEGER
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
            migration = connection.execute(
                "SELECT value FROM metadata WHERE key = 'give_role_permission_migrated'"
            ).fetchone()
            if not migration or migration[0] != "1":
                connection.execute(
                    """
                    INSERT OR IGNORE INTO prefix_command_permissions(
                        user_id, command, granted_at
                    )
                    SELECT user_id, 'give_role', granted_at
                    FROM prefix_command_permissions
                    WHERE command = 'give'
                    """
                )
                connection.execute(
                    "DELETE FROM prefix_command_permissions WHERE command = 'give'"
                )
                connection.execute(
                    """
                    UPDATE metadata
                    SET value = '1'
                    WHERE key = 'give_role_permission_migrated'
                    """
                )
            connection.execute("DROP TABLE IF EXISTS targets")

    def total(self) -> int:
        with self.lock, self._connect() as connection:
            row = connection.execute("SELECT value FROM metadata WHERE key = 'total'").fetchone()
            return int(row[0]) if row else 0

    def board(self) -> dict[str, Any]:
        with self.lock, self._connect() as connection:
            total_row = connection.execute("SELECT value FROM metadata WHERE key = 'total'").fetchone()
            return {
                "total": int(total_row[0]) if total_row else 0,
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

    @staticmethod
    def _economy_account_from_row(row: tuple[Any, ...] | None) -> dict[str, Any]:
        if row is None:
            return {
                "user_id": "",
                "fumao_coins": 0,
                "crystals": 0,
                "grace": 0,
                "level": 1,
                "last_daily_date": None,
                "last_hourly_at": None,
            }
        return {
            "user_id": str(row[0]),
            "fumao_coins": int(row[1]),
            "crystals": int(row[2]),
            "grace": int(row[3]),
            "level": int(row[4]),
            "last_daily_date": row[5],
            "last_hourly_at": int(row[6]) if row[6] is not None else None,
        }

    @staticmethod
    def _select_economy_account(connection: sqlite3.Connection, user_id: str) -> dict[str, Any]:
        row = connection.execute(
            """
            SELECT user_id, fumao_coins, crystals, grace, level,
                   last_daily_date, last_hourly_at
            FROM economy_accounts
            WHERE user_id = ?
            """,
            (str(user_id),),
        ).fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO economy_accounts(user_id) VALUES (?)",
                (str(user_id),),
            )
            return WorshipStore._economy_account_from_row((str(user_id), 0, 0, 0, 1, None, None))
        return WorshipStore._economy_account_from_row(row)

    def economy_account(self, user_id: str) -> dict[str, Any]:
        with self.lock, self._connect() as connection:
            return self._select_economy_account(connection, str(user_id))

    def claim_daily(
        self,
        user_id: str,
        day: str,
        base_reward: int,
        multiplier: float,
    ) -> dict[str, Any]:
        with self.lock, self._connect() as connection:
            account = self._select_economy_account(connection, str(user_id))
            if account["last_daily_date"] == day:
                account["claimed"] = False
                account["reward"] = 0
                return account

            reward = int(round(base_reward * multiplier))
            connection.execute(
                """
                UPDATE economy_accounts
                SET fumao_coins = fumao_coins + ?, last_daily_date = ?
                WHERE user_id = ?
                """,
                (reward, day, str(user_id)),
            )
            account = self._select_economy_account(connection, str(user_id))
            account["claimed"] = True
            account["reward"] = reward
            account["base_reward"] = base_reward
            account["multiplier"] = multiplier
            return account

    def claim_hourly(
        self,
        user_id: str,
        now_ms: int,
        base_reward: int,
        saved_hours: int,
        multiplier: float,
    ) -> dict[str, Any]:
        with self.lock, self._connect() as connection:
            account = self._select_economy_account(connection, str(user_id))
            last_hourly_at = account["last_hourly_at"]
            if last_hourly_at is None:
                accumulated_hours = 1
            else:
                accumulated_hours = max(0, (int(now_ms) - last_hourly_at) // 3_600_000)

            if accumulated_hours < 1:
                account["claimed"] = False
                account["reward"] = 0
                account["accumulated_hours"] = 0
                account["next_hourly_at"] = last_hourly_at + 3_600_000
                return account

            accumulated_hours = min(accumulated_hours, max(1, int(saved_hours)))
            reward = int(round(base_reward * accumulated_hours * multiplier))
            connection.execute(
                """
                UPDATE economy_accounts
                SET fumao_coins = fumao_coins + ?, last_hourly_at = ?
                WHERE user_id = ?
                """,
                (reward, int(now_ms), str(user_id)),
            )
            account = self._select_economy_account(connection, str(user_id))
            account["claimed"] = True
            account["reward"] = reward
            account["base_reward"] = base_reward
            account["multiplier"] = multiplier
            account["accumulated_hours"] = accumulated_hours
            return account

    def upgrade_economy(
        self,
        user_id: str,
        target_level: int,
        coin_cost: int,
        crystal_cost: int,
    ) -> dict[str, Any]:
        with self.lock, self._connect() as connection:
            account = self._select_economy_account(connection, str(user_id))
            if account["level"] + 1 != int(target_level):
                account["upgraded"] = False
                account["upgrade_error"] = "level"
                return account
            if (
                account["fumao_coins"] < int(coin_cost)
                or account["crystals"] < int(crystal_cost)
            ):
                account["upgraded"] = False
                account["upgrade_error"] = "balance"
                return account

            connection.execute(
                """
                UPDATE economy_accounts
                SET fumao_coins = fumao_coins - ?,
                    crystals = crystals - ?,
                    level = ?
                WHERE user_id = ?
                """,
                (int(coin_cost), int(crystal_cost), int(target_level), str(user_id)),
            )
            account = self._select_economy_account(connection, str(user_id))
            account["upgraded"] = True
            return account

    def grant_economy_currency(
        self,
        user_id: str,
        currency: str,
        amount: int,
    ) -> dict[str, Any]:
        columns = {
            "fumao_coins": "fumao_coins",
            "crystals": "crystals",
            "grace": "grace",
        }
        column = columns.get(currency)
        if column is None:
            raise ValueError(f"未知的貨幣種類：{currency}")
        if int(amount) < 1:
            raise ValueError("發放數量必須大於 0")

        with self.lock, self._connect() as connection:
            self._select_economy_account(connection, str(user_id))
            connection.execute(
                f"UPDATE economy_accounts SET {column} = {column} + ? WHERE user_id = ?",
                (int(amount), str(user_id)),
            )
            return self._select_economy_account(connection, str(user_id))

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

    def execute_sql(self, statement: str) -> dict[str, Any]:
        """Execute one administrator-approved SQL statement."""
        with self.lock, self._connect() as connection:
            cursor = connection.execute(statement)
            if cursor.description:
                columns = [str(column[0]) for column in cursor.description]
                rows = cursor.fetchmany(50)
                return {
                    "type": "rows",
                    "columns": columns,
                    "rows": [tuple(row) for row in rows],
                    "has_more": cursor.fetchone() is not None,
                }
            return {
                "type": "affected",
                "rowcount": cursor.rowcount,
                "lastrowid": cursor.lastrowid,
            }
