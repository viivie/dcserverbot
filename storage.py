"""SQLite storage for worship counts and avatar cache."""

from __future__ import annotations

import json
import random
import sqlite3
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from commands.worship import next_streak, taipei_today

ECONOMY_LOG_RETENTION_MS = 3 * 24 * 60 * 60 * 1000
PVP_CONFIG_PATH = Path(__file__).resolve().parent / "commands" / "pvp" / "json" / "pvp_config.json"


@lru_cache(maxsize=1)
def _pvp_economy_config() -> dict[str, Any]:
    try:
        value = json.loads(PVP_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "cooldowns": {"forced_hours": 24},
            "rules": {
                "loss_cap_rate": 0.1,
                "growth_threshold": 2.0,
                "forced_close_threshold": 0.15,
            },
        }
    return value if isinstance(value, dict) else {}


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

                CREATE TABLE IF NOT EXISTS economy_currency_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    amount INTEGER NOT NULL CHECK(amount != 0),
                    source TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_economy_currency_logs_user_time
                    ON economy_currency_logs(user_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS bets (
                    message_id TEXT PRIMARY KEY,
                    guild_id TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    started_at INTEGER,
                    currency TEXT NOT NULL DEFAULT 'fumao_coins',
                    resolved_outcome TEXT,
                    closed_at INTEGER
                );

                CREATE TABLE IF NOT EXISTS bet_options (
                    bet_message_id TEXT NOT NULL,
                    option_name TEXT NOT NULL,
                    odds REAL NOT NULL,
                    sort_order INTEGER NOT NULL,
                    PRIMARY KEY (bet_message_id, option_name),
                    FOREIGN KEY (bet_message_id) REFERENCES bets(message_id)
                );

                CREATE TABLE IF NOT EXISTS bet_entries (
                    bet_message_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    option_name TEXT NOT NULL,
                    currency TEXT NOT NULL DEFAULT 'fumao_coins',
                    amount INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    PRIMARY KEY (bet_message_id, user_id, option_name, currency),
                    FOREIGN KEY (bet_message_id) REFERENCES bets(message_id)
                );

                CREATE TABLE IF NOT EXISTS bet_prohibitions (
                    bet_message_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    option_name TEXT NOT NULL,
                    PRIMARY KEY (bet_message_id, user_id, option_name),
                    FOREIGN KEY (bet_message_id) REFERENCES bets(message_id)
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
            bet_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(bets)")
            }
            if "closed_at" not in bet_columns:
                connection.execute(
                    "ALTER TABLE bets ADD COLUMN closed_at INTEGER"
                )
            if "currency" not in bet_columns:
                connection.execute(
                    "ALTER TABLE bets ADD COLUMN currency TEXT NOT NULL DEFAULT 'fumao_coins'"
                )
            if "started_at" not in bet_columns:
                connection.execute(
                    "ALTER TABLE bets ADD COLUMN started_at INTEGER"
                )
                connection.execute(
                    "UPDATE bets SET started_at = created_at WHERE started_at IS NULL"
                )
            bet_entry_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(bet_entries)")
            }
            if "currency" not in bet_entry_columns:
                connection.execute(
                    "ALTER TABLE bet_entries ADD COLUMN currency TEXT NOT NULL DEFAULT 'fumao_coins'"
                )
            bet_entry_primary_key = [
                row[1]
                for row in sorted(
                    connection.execute("PRAGMA table_info(bet_entries)").fetchall(),
                    key=lambda row: row[5],
                )
                if row[5]
            ]
            expected_bet_entry_primary_key = [
                "bet_message_id",
                "user_id",
                "option_name",
                "currency",
            ]
            if bet_entry_primary_key != expected_bet_entry_primary_key:
                connection.execute("ALTER TABLE bet_entries RENAME TO bet_entries_legacy")
                connection.execute(
                    """
                    CREATE TABLE bet_entries (
                        bet_message_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        option_name TEXT NOT NULL,
                        currency TEXT NOT NULL DEFAULT 'fumao_coins',
                        amount INTEGER NOT NULL,
                        created_at INTEGER NOT NULL,
                        PRIMARY KEY (bet_message_id, user_id, option_name, currency),
                        FOREIGN KEY (bet_message_id) REFERENCES bets(message_id)
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO bet_entries(
                        bet_message_id, user_id, option_name, currency,
                        amount, created_at
                    )
                    SELECT bet_message_id, user_id, option_name, currency,
                           amount, created_at
                    FROM bet_entries_legacy
                    """
                )
                connection.execute("DROP TABLE bet_entries_legacy")
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

    def apply_worship(
        self,
        actor_id: str,
        display_name: str,
        tribute_percent: int = 1,
    ) -> dict[str, Any]:
        tribute_percent = int(tribute_percent)
        if not 1 <= tribute_percent <= 10:
            raise ValueError("獻祭百分比必須介於 1 到 10。")

        with self.lock, self._connect() as connection:
            row = connection.execute(
                "SELECT streak, last_date FROM actors WHERE actor_id = ?",
                (actor_id,),
            ).fetchone()
            old_streak = int(row[0]) if row else 0
            last_date = row[1] if row else None
            today = taipei_today()
            next_value, counted = next_streak(last_date, old_streak, today)

            account = self._select_economy_account(connection, str(actor_id).removeprefix("discord:"))
            if not counted:
                total_row = connection.execute("SELECT value FROM metadata WHERE key = 'total'").fetchone()
                return {
                    "displayName": display_name,
                    "total": int(total_row[0]) if total_row else 0,
                    "streak": next_value,
                    "counted": False,
                    "reason": "already_counted",
                    "balance": int(account["fumao_coins"]),
                    "tribute_percent": tribute_percent,
                    "tribute_amount": 0,
                    "crystals_reward": 0,
                }

            balance = int(account["fumao_coins"])
            tribute_amount = max(100, balance * tribute_percent // 100)
            if balance < tribute_amount:
                total_row = connection.execute("SELECT value FROM metadata WHERE key = 'total'").fetchone()
                return {
                    "displayName": display_name,
                    "total": int(total_row[0]) if total_row else 0,
                    "streak": next_value,
                    "counted": False,
                    "reason": "insufficient_funds",
                    "balance": balance,
                    "tribute_percent": tribute_percent,
                    "tribute_amount": tribute_amount,
                    "crystals_reward": 0,
                }

            crystals_reward = random.randint(1, 5) if random.random() < tribute_percent * 0.07 else 0
            user_id = str(actor_id).removeprefix("discord:")
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
            connection.execute(
                "UPDATE economy_accounts SET fumao_coins = fumao_coins - ?, crystals = crystals + ? WHERE user_id = ?",
                (tribute_amount, crystals_reward, user_id),
            )
            self._refresh_pvp_state(connection, user_id, int(time.time() * 1000))
            self._record_economy_currency_change(
                connection,
                user_id,
                "fumao_coins",
                -tribute_amount,
                f"膜拜獻祭 {tribute_percent}%",
                int(time.time() * 1000),
            )
            if crystals_reward:
                self._record_economy_currency_change(
                    connection,
                    user_id,
                    "crystals",
                    crystals_reward,
                    "膜拜獻祭獎勵",
                    int(time.time() * 1000),
                )

            total_row = connection.execute("SELECT value FROM metadata WHERE key = 'total'").fetchone()
            return {
                "displayName": display_name,
                "total": int(total_row[0]) if total_row else 0,
                "streak": next_value,
                "counted": counted,
                "reason": "counted",
                "balance": balance - tribute_amount,
                "tribute_percent": tribute_percent,
                "tribute_amount": tribute_amount,
                "crystals_reward": crystals_reward,
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

    @staticmethod
    def _purge_economy_currency_logs(
        connection: sqlite3.Connection,
        now_ms: int,
    ) -> None:
        connection.execute(
            "DELETE FROM economy_currency_logs WHERE created_at < ?",
            (int(now_ms) - ECONOMY_LOG_RETENTION_MS,),
        )

    @staticmethod
    def _record_economy_currency_change(
        connection: sqlite3.Connection,
        user_id: str,
        currency: str,
        amount: int,
        source: str,
        created_at: int,
    ) -> None:
        if int(amount) == 0:
            return
        connection.execute(
            """
            INSERT INTO economy_currency_logs(
                user_id, currency, amount, source, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (str(user_id), currency, int(amount), source[:120], int(created_at)),
        )

    def economy_currency_logs(
        self,
        user_id: str,
        now_ms: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        current_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
        with self.lock, self._connect() as connection:
            self._purge_economy_currency_logs(connection, current_ms)
            rows = connection.execute(
                """
                SELECT currency, amount, source, created_at
                FROM economy_currency_logs
                WHERE user_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (str(user_id), max(1, min(int(limit), 100))),
            ).fetchall()
            return [
                {
                    "currency": str(row[0]),
                    "amount": int(row[1]),
                    "source": str(row[2]),
                    "created_at": int(row[3]),
                }
                for row in rows
            ]

    @staticmethod
    def _refresh_pvp_state(
        connection: sqlite3.Connection,
        user_id: str,
        now_ms: int,
    ) -> bool:
        """Refresh PvP thresholds after an economy balance change."""
        try:
            profile = connection.execute(
                """
                SELECT enabled, baseline_coins, loss_cap
                FROM pvp_profiles WHERE user_id = ?
                """, (str(user_id),),
            ).fetchone()
            account = connection.execute(
                "SELECT fumao_coins FROM economy_accounts WHERE user_id = ?",
                (str(user_id),),
            ).fetchone()
        except sqlite3.OperationalError:
            # The PvP command module creates this table during command registration.
            return False
        if profile is None or not bool(profile[0]) or account is None:
            return False
        pvp_config = _pvp_economy_config()
        rules = pvp_config.get("rules", {})
        coins = int(account[0])
        baseline = int(profile[1])
        if baseline > 0 and coins < baseline * float(rules.get("forced_close_threshold", 0.15)):
            forced_hours = float(pvp_config.get("cooldowns", {}).get("forced_hours", 24))
            connection.execute(
                "UPDATE pvp_profiles SET enabled = 0, forced_cooldown_until = ?, updated_at = ? WHERE user_id = ?",
                (int(now_ms) + int(forced_hours * 60 * 60 * 1000), int(now_ms), str(user_id)),
            )
            return False
        if baseline > 0 and coins > baseline * float(rules.get("growth_threshold", 2.0)):
            new_cap = max(
                int(profile[2]),
                max(1, int(coins * float(rules.get("loss_cap_rate", 0.1)))),
            )
            connection.execute(
                "UPDATE pvp_profiles SET loss_cap = ?, updated_at = ? WHERE user_id = ?",
                (new_cap, int(now_ms), str(user_id)),
            )
        return True

    @staticmethod
    def _pvp_bonus_multiplier(
        connection: sqlite3.Connection,
        user_id: str,
        level: int,
        now_ms: int,
    ) -> float:
        """Return the PvP reward bonus after refreshing PvP thresholds."""
        if not WorshipStore._refresh_pvp_state(connection, user_id, now_ms):
            return 1.0
        bounded_level = max(1, min(int(level), 30))
        return 1.5 + (bounded_level - 1) * (1.5 / 29)

    def claim_daily(
        self,
        user_id: str,
        day: str,
        base_reward: int,
        multiplier: float,
        random_multiplier: float = 1.0,
    ) -> dict[str, Any]:
        with self.lock, self._connect() as connection:
            now_ms = int(time.time() * 1000)
            self._purge_economy_currency_logs(connection, now_ms)
            account = self._select_economy_account(connection, str(user_id))
            if account["last_daily_date"] == day:
                account["claimed"] = False
                account["reward"] = 0
                return account

            pvp_multiplier = self._pvp_bonus_multiplier(
                connection, str(user_id), int(account["level"]), now_ms
            )
            reward = int(round(base_reward * random_multiplier * multiplier * pvp_multiplier))
            connection.execute(
                """
                UPDATE economy_accounts
                SET fumao_coins = fumao_coins + ?, last_daily_date = ?
                WHERE user_id = ?
                """,
                (reward, day, str(user_id)),
            )
            self._refresh_pvp_state(connection, str(user_id), now_ms)
            self._record_economy_currency_change(
                connection,
                str(user_id),
                "fumao_coins",
                reward,
                "每日簽到",
                now_ms,
            )
            account = self._select_economy_account(connection, str(user_id))
            account["claimed"] = True
            account["reward"] = reward
            account["base_reward"] = base_reward
            account["random_multiplier"] = random_multiplier
            account["multiplier"] = multiplier
            account["pvp_multiplier"] = pvp_multiplier
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
            now_ms = int(time.time() * 1000)
            self._purge_economy_currency_logs(connection, now_ms)
            account = self._select_economy_account(connection, str(user_id))
            last_hourly_at = account["last_hourly_at"]
            hour_ms = 3_600_000
            current_hour_start = (int(now_ms) // hour_ms) * hour_ms
            if last_hourly_at is None:
                accumulated_hours = 1
            else:
                last_hour_start = (int(last_hourly_at) // hour_ms) * hour_ms
                accumulated_hours = max(
                    0,
                    (current_hour_start - last_hour_start) // hour_ms,
                )

            if accumulated_hours < 1:
                account["claimed"] = False
                account["reward"] = 0
                account["accumulated_hours"] = 0
                account["next_hourly_at"] = current_hour_start + hour_ms
                return account

            accumulated_hours = min(accumulated_hours, max(1, int(saved_hours)))
            pvp_multiplier = self._pvp_bonus_multiplier(
                connection, str(user_id), int(account["level"]), now_ms
            )
            reward = int(round(base_reward * accumulated_hours * multiplier * pvp_multiplier))
            connection.execute(
                """
                UPDATE economy_accounts
                SET fumao_coins = fumao_coins + ?, last_hourly_at = ?
                WHERE user_id = ?
                """,
                (reward, current_hour_start, str(user_id)),
            )
            self._refresh_pvp_state(connection, str(user_id), now_ms)
            self._record_economy_currency_change(
                connection,
                str(user_id),
                "fumao_coins",
                reward,
                "每小時簽到",
                now_ms,
            )
            account = self._select_economy_account(connection, str(user_id))
            account["claimed"] = True
            account["reward"] = reward
            account["base_reward"] = base_reward
            account["multiplier"] = multiplier
            account["pvp_multiplier"] = pvp_multiplier
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
            now_ms = int(time.time() * 1000)
            self._purge_economy_currency_logs(connection, now_ms)
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
            self._refresh_pvp_state(connection, str(user_id), now_ms)
            self._record_economy_currency_change(
                connection,
                str(user_id),
                "fumao_coins",
                -int(coin_cost),
                "簽到等級升級",
                now_ms,
            )
            self._record_economy_currency_change(
                connection,
                str(user_id),
                "crystals",
                -int(crystal_cost),
                "簽到等級升級",
                now_ms,
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
        if int(amount) == 0:
            raise ValueError("數量不可為 0")

        with self.lock, self._connect() as connection:
            now_ms = int(time.time() * 1000)
            self._purge_economy_currency_logs(connection, now_ms)
            account = self._select_economy_account(connection, str(user_id))
            requested = int(amount)
            actual = requested
            if requested < 0:
                actual = -min(int(account[currency]), abs(requested))
            connection.execute(
                f"UPDATE economy_accounts SET {column} = {column} + ? WHERE user_id = ?",
                (actual, str(user_id)),
            )
            if currency == "fumao_coins":
                self._refresh_pvp_state(connection, str(user_id), now_ms)
            self._record_economy_currency_change(
                connection,
                str(user_id),
                currency,
                actual,
                "管理員發放" if actual > 0 else "管理員扣除",
                now_ms,
            )
            account = self._select_economy_account(connection, str(user_id))
            account["changed"] = actual
            return account

    def grant_economy_currency_all(
        self,
        currency: str,
        amount: int,
    ) -> int:
        """Grant a currency to every account already registered in the database."""
        columns = {
            "fumao_coins": "fumao_coins",
            "crystals": "crystals",
            "grace": "grace",
        }
        column = columns.get(currency)
        if column is None:
            raise ValueError(f"未知的貨幣種類：{currency}")
        if int(amount) == 0:
            raise ValueError("數量不可為 0")

        with self.lock, self._connect() as connection:
            now_ms = int(time.time() * 1000)
            self._purge_economy_currency_logs(connection, now_ms)
            users = [
                str(row[0])
                for row in connection.execute(
                    "SELECT user_id FROM economy_accounts"
                ).fetchall()
            ]
            changed = 0
            source = "管理員全體發放" if int(amount) > 0 else "管理員全體扣除"
            for user_id in users:
                account = self._select_economy_account(connection, user_id)
                requested = int(amount)
                actual = requested
                if requested < 0:
                    actual = -min(int(account[currency]), abs(requested))
                connection.execute(
                    f"UPDATE economy_accounts SET {column} = {column} + ? WHERE user_id = ?",
                    (actual, user_id),
                )
                if currency == "fumao_coins":
                    self._refresh_pvp_state(connection, user_id, now_ms)
                self._record_economy_currency_change(
                    connection, user_id, currency, actual, source, now_ms
                )
                changed += 1
            return changed

    def create_bet(
        self,
        message_id: str,
        guild_id: str,
        channel_id: str,
        title: str,
        content: str,
        created_at: int,
        expires_at: int,
        started_at: int | None,
        options: list[tuple[str, float]],
    ) -> None:
        with self.lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO bets(
                    message_id, guild_id, channel_id, title, content,
                    created_at, expires_at, started_at, currency
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(message_id),
                    str(guild_id),
                    str(channel_id),
                    title,
                    content,
                    int(created_at),
                    int(expires_at),
                    int(started_at) if started_at is not None else None,
                    "multi",
                ),
            )
            connection.executemany(
                """
                INSERT INTO bet_options(bet_message_id, option_name, odds, sort_order)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (str(message_id), option_name, float(odds), index)
                    for index, (option_name, odds) in enumerate(options)
                ],
            )

    def bet_details(self, message_id: str) -> dict[str, Any] | None:
        with self.lock, self._connect() as connection:
            bet = connection.execute(
                """
                SELECT message_id, guild_id, channel_id, title, content,
                       created_at, expires_at, started_at, currency,
                       resolved_outcome, closed_at
                FROM bets WHERE message_id = ?
                """,
                (str(message_id),),
            ).fetchone()
            if bet is None:
                return None
            options = connection.execute(
                """
                SELECT option_name, odds
                FROM bet_options
                WHERE bet_message_id = ?
                ORDER BY sort_order
                """,
                (str(message_id),),
            ).fetchall()
            return {
                "message_id": str(bet[0]),
                "guild_id": str(bet[1]),
                "channel_id": str(bet[2]),
                "title": str(bet[3]),
                "content": str(bet[4]),
                "created_at": int(bet[5]),
                "expires_at": int(bet[6]),
                "started_at": int(bet[7]) if bet[7] is not None else None,
                "currency": str(bet[8]),
                "resolved_outcome": bet[9],
                "closed_at": int(bet[10]) if bet[10] is not None else None,
                "options": [(str(row[0]), float(row[1])) for row in options],
            }

    def latest_bet_message_id(self, channel_id: str) -> str | None:
        with self.lock, self._connect() as connection:
            bet = connection.execute(
                """
                SELECT message_id
                FROM bets
                WHERE channel_id = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """,
                (str(channel_id),),
            ).fetchone()
            return str(bet[0]) if bet is not None else None

    def start_bet(self, message_id: str, now_ms: int) -> dict[str, Any]:
        with self.lock, self._connect() as connection:
            bet = connection.execute(
                """
                SELECT started_at, resolved_outcome, closed_at
                FROM bets WHERE message_id = ?
                """,
                (str(message_id),),
            ).fetchone()
            if bet is None:
                raise ValueError("找不到這個賭盤")
            if bet[1] is not None:
                raise ValueError("這個賭盤已經結算，無法開始下注")
            if bet[2] is not None:
                raise ValueError("這個賭盤已經停止下注，無法開始")
            if bet[0] is not None:
                raise ValueError("這個賭盤已經開始下注")
            connection.execute(
                "UPDATE bets SET started_at = ? WHERE message_id = ?",
                (int(now_ms), str(message_id)),
            )
            return {"started_at": int(now_ms)}

    def stop_bet(self, message_id: str, now_ms: int) -> dict[str, Any]:
        with self.lock, self._connect() as connection:
            bet = connection.execute(
                """
                SELECT resolved_outcome, closed_at
                FROM bets WHERE message_id = ?
                """,
                (str(message_id),),
            ).fetchone()
            if bet is None:
                raise ValueError("找不到這個賭盤")
            if bet[0] is None and bet[1] is None:
                connection.execute(
                    "UPDATE bets SET closed_at = ? WHERE message_id = ?",
                    (int(now_ms), str(message_id)),
                )
                connection.execute(
                    "DELETE FROM bet_prohibitions WHERE bet_message_id = ?",
                    (str(message_id),),
                )
            return {
                "resolved_outcome": bet[0],
                "closed_at": int(bet[1]) if bet[1] is not None else int(now_ms),
            }

    def place_bet(
        self,
        message_id: str,
        user_id: str,
        option_name: str,
        currency: str,
        amount: int,
        now_ms: int,
    ) -> dict[str, Any]:
        if int(amount) < 1:
            raise ValueError("下注數量必須大於 0")

        with self.lock, self._connect() as connection:
            self._purge_economy_currency_logs(connection, int(now_ms))
            bet = connection.execute(
                "SELECT expires_at, resolved_outcome, closed_at, started_at FROM bets WHERE message_id = ?",
                (str(message_id),),
            ).fetchone()
            if bet is None:
                raise ValueError("找不到這個賭盤")
            if bet[1] is not None:
                raise ValueError("這個賭盤已經結算")
            if bet[2] is not None:
                raise ValueError("這個賭盤已經停止下注")
            if bet[3] is None:
                raise ValueError("這個賭盤尚未開始下注")
            if int(now_ms) >= int(bet[0]):
                raise ValueError("這個賭盤已經截止下注")

            option = connection.execute(
                """
                SELECT odds FROM bet_options
                WHERE bet_message_id = ? AND option_name = ?
                """,
                (str(message_id), option_name),
            ).fetchone()
            if option is None:
                raise ValueError("找不到這個下注狀況")

            prohibited = connection.execute(
                """
                SELECT 1 FROM bet_prohibitions
                WHERE bet_message_id = ? AND user_id = ? AND option_name = ?
                """,
                (str(message_id), str(user_id), option_name),
            ).fetchone()
            if prohibited is not None:
                raise ValueError("你無法下注這個賭盤的指定選項")

            currency = str(currency)
            if currency != "fumao_coins":
                raise ValueError("賭盤只能使用芙帽幣下注")
            currency_column = "fumao_coins"
            account = self._select_economy_account(connection, str(user_id))
            if int(account[currency]) < int(amount):
                raise ValueError("下注貨幣餘額不足")
            connection.execute(
                f"UPDATE economy_accounts SET {currency_column} = {currency_column} - ? WHERE user_id = ?",
                (int(amount), str(user_id)),
            )
            self._refresh_pvp_state(connection, str(user_id), int(now_ms))
            self._record_economy_currency_change(
                connection,
                str(user_id),
                currency,
                -int(amount),
                f"下注：{option_name}",
                int(now_ms),
            )
            connection.execute(
                """
                INSERT INTO bet_entries(
                    bet_message_id, user_id, option_name, currency, amount, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(bet_message_id, user_id, option_name, currency)
                DO UPDATE SET amount = amount + excluded.amount
                """,
                (
                    str(message_id),
                    str(user_id),
                    option_name,
                    currency,
                    int(amount),
                    int(now_ms),
                ),
            )
            return {
                "amount": int(amount),
                "option_name": option_name,
                "odds": float(option[0]),
                "balance": int(account[currency]) - int(amount),
                "currency": currency,
            }

    def prohibit_bet_options(
        self,
        message_id: str,
        user_ids: list[str],
        option_names: list[str],
    ) -> int:
        unique_users = list(dict.fromkeys(str(user_id) for user_id in user_ids))
        unique_options = list(dict.fromkeys(option.strip() for option in option_names if option.strip()))
        if not unique_users or not unique_options:
            raise ValueError("至少需要一位使用者與一個賭盤選項")

        with self.lock, self._connect() as connection:
            bet = connection.execute(
                """
                SELECT message_id, resolved_outcome, closed_at, expires_at
                FROM bets WHERE message_id = ?
                """,
                (str(message_id),),
            ).fetchone()
            if bet is None:
                raise ValueError("找不到這個賭盤")
            if bet[1] is not None or bet[2] is not None:
                connection.execute(
                    "DELETE FROM bet_prohibitions WHERE bet_message_id = ?",
                    (str(message_id),),
                )
                raise ValueError("這個賭盤已經結束，無法新增下注限制")
            if int(time.time() * 1000) >= int(bet[3]):
                connection.execute(
                    "DELETE FROM bet_prohibitions WHERE bet_message_id = ?",
                    (str(message_id),),
                )
                raise ValueError("這個賭盤已經截止，無法新增下注限制")

            available_options = {
                str(row[0])
                for row in connection.execute(
                    "SELECT option_name FROM bet_options WHERE bet_message_id = ?",
                    (str(message_id),),
                ).fetchall()
            }
            invalid_options = [
                option for option in unique_options if option not in available_options
            ]
            if invalid_options:
                raise ValueError(
                    "找不到賭盤選項：" + "、".join(invalid_options)
                )

            before = connection.total_changes
            connection.executemany(
                """
                INSERT OR IGNORE INTO bet_prohibitions(
                    bet_message_id, user_id, option_name
                ) VALUES (?, ?, ?)
                """,
                [
                    (str(message_id), user_id, option_name)
                    for user_id in unique_users
                    for option_name in unique_options
                ],
            )
            return max(0, connection.total_changes - before)

    def resolve_bet(self, message_id: str, outcome: str, now_ms: int) -> dict[str, Any]:
        with self.lock, self._connect() as connection:
            self._purge_economy_currency_logs(connection, int(now_ms))
            bet = connection.execute(
                "SELECT resolved_outcome FROM bets WHERE message_id = ?",
                (str(message_id),),
            ).fetchone()
            if bet is None:
                raise ValueError("找不到這個賭盤")
            if bet[0] is not None:
                raise ValueError("這個賭盤已經結算")
            requested_outcomes = [
                item.strip()
                for item in outcome.split(",")
                if item.strip()
            ]
            if not requested_outcomes:
                raise ValueError("請提供至少一個結算狀況")
            if any(item.casefold() == "return" for item in requested_outcomes):
                if len(requested_outcomes) != 1:
                    raise ValueError("return 不能與其他結算狀況一起使用")
                normalized = "return"
                winning_odds: dict[str, float] = {}
            else:
                winning_odds = {}
                for requested in requested_outcomes:
                    if requested in winning_odds:
                        raise ValueError(f"結算狀況 `{requested}` 重複了")
                    option = connection.execute(
                        """
                        SELECT odds FROM bet_options
                        WHERE bet_message_id = ? AND option_name = ?
                        """,
                        (str(message_id), requested),
                    ).fetchone()
                    if option is None:
                        raise ValueError(f"找不到這個結算狀況：{requested}")
                    winning_odds[requested] = float(option[0])
                normalized = ",".join(requested_outcomes)

            entries = connection.execute(
                """
                SELECT user_id, option_name, currency, amount
                FROM bet_entries WHERE bet_message_id = ?
                """,
                (str(message_id),),
            ).fetchall()
            refunded = 0
            paid = 0
            winners = 0
            paid_by_currency: dict[str, int] = {}
            refunded_by_currency: dict[str, int] = {}
            for user_id, option_name, entry_currency, amount in entries:
                amount = int(amount)
                entry_currency = str(entry_currency)
                currency_columns = {
                    "fumao_coins": "fumao_coins",
                    "crystals": "crystals",
                    "grace": "grace",
                }
                currency_column = currency_columns.get(entry_currency)
                if currency_column is None:
                    raise ValueError("下注紀錄使用了未知的貨幣種類")
                if normalized.casefold() == "return":
                    payout = amount
                    refunded += payout
                    refunded_by_currency[entry_currency] = (
                        refunded_by_currency.get(entry_currency, 0) + payout
                    )
                elif str(option_name) in winning_odds:
                    payout = int(round(amount * winning_odds[str(option_name)]))
                    if entry_currency == "fumao_coins":
                        account = self._select_economy_account(connection, str(user_id))
                        pvp_multiplier = self._pvp_bonus_multiplier(
                            connection, str(user_id), int(account["level"]), int(now_ms)
                        )
                        payout = int(round(payout * pvp_multiplier))
                    paid += payout
                    winners += 1
                    paid_by_currency[entry_currency] = (
                        paid_by_currency.get(entry_currency, 0) + payout
                    )
                else:
                    payout = 0
                if payout:
                    self._select_economy_account(connection, str(user_id))
                    connection.execute(
                        f"UPDATE economy_accounts SET {currency_column} = {currency_column} + ? WHERE user_id = ?",
                        (payout, str(user_id)),
                    )
                    source = (
                        "賭盤退款"
                        if normalized.casefold() == "return"
                        else f"賭盤結算：{'、'.join(requested_outcomes)}"
                    )
                    self._record_economy_currency_change(
                        connection,
                        str(user_id),
                        entry_currency,
                        payout,
                        source,
                        int(now_ms),
                    )
                    if entry_currency == "fumao_coins":
                        self._refresh_pvp_state(connection, str(user_id), int(now_ms))

            connection.execute(
                "UPDATE bets SET resolved_outcome = ? WHERE message_id = ?",
                (normalized, str(message_id)),
            )
            connection.execute(
                "DELETE FROM bet_prohibitions WHERE bet_message_id = ?",
                (str(message_id),),
            )
            total_entries = sum(int(row[3]) for row in entries)
            return {
                "outcome": normalized,
                "entries": len(entries),
                "total_staked": total_entries,
                "refunded": refunded,
                "paid": paid,
                "winners": winners,
                "paid_by_currency": paid_by_currency,
                "refunded_by_currency": refunded_by_currency,
            }

    def change_economy_currency(
        self,
        user_id: str,
        currency: str,
        amount: int,
        source: str = "系統獲得",
    ) -> dict[str, Any]:
        """Apply a currency delta without allowing the wallet to go negative."""
        if currency != "fumao_coins":
            raise ValueError("目前只有芙帽幣支援增減操作")

        with self.lock, self._connect() as connection:
            now_ms = int(time.time() * 1000)
            self._purge_economy_currency_logs(connection, now_ms)
            account = self._select_economy_account(connection, str(user_id))
            requested = int(amount)
            actual = requested
            if requested < 0:
                actual = -min(account["fumao_coins"], abs(requested))
            connection.execute(
                "UPDATE economy_accounts SET fumao_coins = fumao_coins + ? WHERE user_id = ?",
                (actual, str(user_id)),
            )
            self._refresh_pvp_state(connection, str(user_id), now_ms)
            self._record_economy_currency_change(
                connection,
                str(user_id),
                currency,
                actual,
                source,
                now_ms,
            )
            account = self._select_economy_account(connection, str(user_id))
            account["changed"] = actual
            return account

    def transfer_fumao_coins(
        self,
        sender_id: str,
        recipient_id: str,
        amount: int,
        fee_rate: float = 0.05,
    ) -> dict[str, Any]:
        """Transfer FumaoCoin atomically; the fee is taken from the transfer amount."""
        amount = int(amount)
        if amount < 1:
            raise ValueError("轉帳金額必須大於 0")
        fee = int(amount * float(fee_rate))
        received = amount - fee
        if received < 1:
            raise ValueError("轉帳金額扣除手續費後必須至少剩下 1 芙帽幣")
        total = amount

        with self.lock, self._connect() as connection:
            now_ms = int(time.time() * 1000)
            self._purge_economy_currency_logs(connection, now_ms)
            if str(sender_id) == str(recipient_id):
                raise ValueError("不能轉帳給自己")
            sender = self._select_economy_account(connection, str(sender_id))
            if int(sender["fumao_coins"]) < total:
                raise ValueError(
                    f"芙帽幣不足，需要 {total:,} 芙帽幣（含 {fee:,} 手續費）。"
                )
            self._select_economy_account(connection, str(recipient_id))
            connection.execute(
                "UPDATE economy_accounts SET fumao_coins = fumao_coins - ? WHERE user_id = ?",
                (total, str(sender_id)),
            )
            connection.execute(
                "UPDATE economy_accounts SET fumao_coins = fumao_coins + ? WHERE user_id = ?",
                (received, str(recipient_id)),
            )
            self._refresh_pvp_state(connection, str(sender_id), now_ms)
            self._refresh_pvp_state(connection, str(recipient_id), now_ms)
            self._record_economy_currency_change(
                connection, str(sender_id), "fumao_coins", -total,
                f"轉帳給 {recipient_id}（手續費 {fee}）", now_ms,
            )
            self._record_economy_currency_change(
                connection, str(recipient_id), "fumao_coins", received,
                f"收到 {sender_id} 的轉帳", now_ms,
            )
            return {
                "amount": amount,
                "fee": fee,
                "received": received,
                "total": total,
                "sender_balance": int(sender["fumao_coins"]) - total,
                "recipient_balance": int(
                    self._select_economy_account(connection, str(recipient_id))["fumao_coins"]
                ),
            }

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
