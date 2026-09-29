"""SQLite operations used by the PvP commands.

PvP owns its tables here while sharing the bot's existing database file and lock.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from .config import ARTIFACT_CONFIG, artifact_color


class PvpStore:
    def __init__(self, base_store: Any) -> None:
        self.base = base_store
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return self.base._connect()

    def _initialize(self) -> None:
        with self.base.lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS pvp_profiles (
                    user_id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    baseline_coins INTEGER NOT NULL DEFAULT 0,
                    loss_cap INTEGER NOT NULL DEFAULT 0,
                    lost_coins INTEGER NOT NULL DEFAULT 0,
                    toggle_cooldown_until INTEGER NOT NULL DEFAULT 0,
                    forced_cooldown_until INTEGER NOT NULL DEFAULT 0,
                    direct_atk INTEGER NOT NULL DEFAULT 0,
                    direct_def INTEGER NOT NULL DEFAULT 0,
                    direct_atk_percent REAL NOT NULL DEFAULT 0,
                    direct_def_percent REAL NOT NULL DEFAULT 0,
                    direct_hp INTEGER NOT NULL DEFAULT 0,
                    direct_hp_percent REAL NOT NULL DEFAULT 0,
                    direct_crit_rate REAL NOT NULL DEFAULT 0,
                    direct_crit_damage REAL NOT NULL DEFAULT 0,
                    attack_count INTEGER NOT NULL DEFAULT 1,
                    updated_at INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS pvp_artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    color TEXT NOT NULL,
                    set_id TEXT NOT NULL DEFAULT '',
                    slot TEXT NOT NULL,
                    level INTEGER NOT NULL DEFAULT 0,
                    main_stat TEXT NOT NULL,
                    main_value REAL NOT NULL DEFAULT 0,
                    sub_stats TEXT NOT NULL DEFAULT '{}',
                    original_value INTEGER NOT NULL DEFAULT 0,
                    upgrade_cost INTEGER NOT NULL DEFAULT 0,
                    equipped INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_pvp_artifacts_user
                    ON pvp_artifacts(user_id, equipped, slot);
                CREATE TABLE IF NOT EXISTS pvp_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor_id TEXT NOT NULL,
                    target_id TEXT,
                    action TEXT NOT NULL,
                    amount INTEGER NOT NULL DEFAULT 0,
                    details TEXT NOT NULL DEFAULT '{}',
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_pvp_logs_actor_time
                    ON pvp_logs(actor_id, created_at DESC);
                """
            )
            self._migrate_legacy_main_values(connection)

    @staticmethod
    def _migrate_legacy_main_values(connection: sqlite3.Connection) -> None:
        """Normalize artifacts created before main stats gained per-level growth."""
        rows = connection.execute(
            "SELECT id, color, main_stat, main_value, level FROM pvp_artifacts"
        ).fetchall()
        main_stats = ARTIFACT_CONFIG.get("main_stats", {})
        for artifact_id, color, main_stat, current_value, level in rows:
            color_data = artifact_color(str(color))
            max_level = int(color_data.get("max_level", 1))
            max_value = float(main_stats.get(str(main_stat), {}).get(str(color), 0))
            if max_level < 1 or max_value <= 0:
                continue
            expected = round(
                max_value * min(int(level) + 1, max_level) / max_level,
                4,
            )
            # Old records stored the max-level value even at Lv.0 or lower levels.
            if float(current_value) >= max_value * 0.999 and expected < max_value * 0.999:
                connection.execute(
                    "UPDATE pvp_artifacts SET main_value = ? WHERE id = ?",
                    (expected, int(artifact_id)),
                )

    @staticmethod
    def _profile(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "user_id": str(row[0]), "enabled": bool(row[1]),
            "baseline_coins": int(row[2]), "loss_cap": int(row[3]),
            "lost_coins": int(row[4]), "toggle_cooldown_until": int(row[5]),
            "forced_cooldown_until": int(row[6]), "direct_atk": int(row[7]),
            "direct_def": int(row[8]), "direct_atk_percent": float(row[9]),
            "direct_def_percent": float(row[10]), "direct_hp": int(row[11]),
            "direct_hp_percent": float(row[12]), "direct_crit_rate": float(row[13]),
            "direct_crit_damage": float(row[14]), "attack_count": int(row[15]),
            "updated_at": int(row[16]),
        }

    def _select_profile(self, connection: sqlite3.Connection, user_id: str) -> dict[str, Any]:
        row = connection.execute(
            """
            SELECT user_id, enabled, baseline_coins, loss_cap, lost_coins,
                   toggle_cooldown_until, forced_cooldown_until,
                   direct_atk, direct_def, direct_atk_percent, direct_def_percent,
                   direct_hp, direct_hp_percent, direct_crit_rate,
                   direct_crit_damage, attack_count, updated_at
            FROM pvp_profiles WHERE user_id = ?
            """, (str(user_id),),
        ).fetchone()
        if row is None:
            now_ms = int(time.time() * 1000)
            connection.execute(
                "INSERT INTO pvp_profiles(user_id, updated_at) VALUES (?, ?)",
                (str(user_id), now_ms),
            )
            row = (str(user_id), 0, 0, 0, 0, 0, 0, 0, 0, 0.0, 0.0, 0, 0.0, 0.0, 0.0, 1, now_ms)
        return self._profile(row)

    def _account(self, connection: sqlite3.Connection, user_id: str) -> dict[str, Any]:
        return self.base._select_economy_account(connection, str(user_id))

    def _refresh(self, connection: sqlite3.Connection, user_id: str, now_ms: int) -> dict[str, Any]:
        profile = self._select_profile(connection, user_id)
        account = self._account(connection, user_id)
        coins = int(account["fumao_coins"])
        if profile["enabled"] and profile["baseline_coins"] > 0:
            if coins < profile["baseline_coins"] * 0.15:
                connection.execute(
                    "UPDATE pvp_profiles SET enabled = 0, forced_cooldown_until = ?, updated_at = ? WHERE user_id = ?",
                    (int(now_ms) + 24 * 60 * 60 * 1000, int(now_ms), str(user_id)),
                )
            elif coins > profile["baseline_coins"] * 2:
                # The baseline is fixed at the moment PvP is opened.  Only
                # the loss cap grows during an active session; it is reset
                # together with the baseline on the next opening.
                new_cap = max(1, int(coins * 0.10))
                connection.execute(
                    "UPDATE pvp_profiles SET loss_cap = ?, updated_at = ? WHERE user_id = ?",
                    (new_cap, int(now_ms), str(user_id)),
                )
        return self._select_profile(connection, user_id)

    def profile(self, user_id: str, now_ms: int | None = None) -> dict[str, Any]:
        now = int(time.time() * 1000) if now_ms is None else int(now_ms)
        with self.base.lock, self._connect() as connection:
            profile = self._refresh(connection, str(user_id), now)
            account = self._account(connection, str(user_id))
            profile.update({"fumao_coins": int(account["fumao_coins"]), "level": int(account["level"])})
            return profile

    def recent_attack_logs(self, user_id: str, limit: int = 5) -> dict[str, list[dict[str, Any]]]:
        """Return recent thefts made by and against a user."""
        safe_limit = max(1, min(int(limit), 20))
        with self.base.lock, self._connect() as connection:
            result: dict[str, list[dict[str, Any]]] = {"attacks": [], "defended": []}
            for action, key in (("attack", "attacks"), ("defended", "defended")):
                rows = connection.execute(
                    """
                    SELECT actor_id, target_id, amount, details, created_at
                    FROM pvp_logs
                    WHERE actor_id = ? AND action = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                    """,
                    (str(user_id), action, safe_limit),
                ).fetchall()
                for actor_id, target_id, amount, details, created_at in rows:
                    try:
                        parsed_details = json.loads(details)
                    except (TypeError, json.JSONDecodeError):
                        parsed_details = {}
                    result[key].append({
                        "actor_id": str(actor_id),
                        "target_id": str(target_id) if target_id is not None else "",
                        "amount": int(amount),
                        "created_at": int(created_at),
                        "details": parsed_details if isinstance(parsed_details, dict) else {},
                    })
            return result

    def enabled_profiles(self, user_ids: list[str] | set[str], now_ms: int | None = None) -> list[dict[str, Any]]:
        """Return enabled PvP profiles belonging to the supplied guild members."""
        member_ids = {str(user_id) for user_id in user_ids}
        if not member_ids:
            return []
        now = int(time.time() * 1000) if now_ms is None else int(now_ms)
        with self.base.lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT user_id FROM pvp_profiles WHERE enabled = 1"
            ).fetchall()
            enabled_ids = [str(row[0]) for row in rows if str(row[0]) in member_ids]
            profiles: list[dict[str, Any]] = []
            for user_id in enabled_ids:
                profile = self._refresh(connection, user_id, now)
                if not profile["enabled"]:
                    continue
                account = self._account(connection, user_id)
                profile.update({"fumao_coins": int(account["fumao_coins"]), "level": int(account["level"])})
                profiles.append(profile)
            profiles.sort(key=lambda item: (-int(item["fumao_coins"]), str(item["user_id"])))
            return profiles

    def toggle(self, user_id: str, enabled: bool, now_ms: int, minimum: int, cooldown_ms: int) -> dict[str, Any]:
        with self.base.lock, self._connect() as connection:
            profile = self._refresh(connection, str(user_id), int(now_ms))
            account = self._account(connection, str(user_id))
            if profile["enabled"] == bool(enabled):
                profile["error"] = "already_enabled" if enabled else "already_disabled"
            elif now_ms < profile["toggle_cooldown_until"]:
                profile["error"] = "toggle_cooldown"
                profile["remaining_ms"] = profile["toggle_cooldown_until"] - int(now_ms)
            elif enabled and now_ms < profile["forced_cooldown_until"]:
                profile["error"] = "forced_cooldown"
                profile["remaining_ms"] = profile["forced_cooldown_until"] - int(now_ms)
            elif enabled and int(account["fumao_coins"]) < int(minimum):
                profile["error"] = "insufficient_funds"
                profile["required"] = int(minimum)
                profile["fumao_coins"] = int(account["fumao_coins"])
            elif enabled:
                coins = int(account["fumao_coins"])
                connection.execute(
                    """
                    UPDATE pvp_profiles SET enabled = 1, baseline_coins = ?,
                           loss_cap = ?, lost_coins = 0, toggle_cooldown_until = ?, updated_at = ?
                    WHERE user_id = ?
                    """,
                    (coins, max(1, int(coins * 0.10)), int(now_ms) + int(cooldown_ms), int(now_ms), str(user_id)),
                )
            else:
                connection.execute(
                    "UPDATE pvp_profiles SET enabled = 0, toggle_cooldown_until = ?, updated_at = ? WHERE user_id = ?",
                    (int(now_ms) + int(cooldown_ms), int(now_ms), str(user_id)),
                )
            result = self._select_profile(connection, str(user_id))
            result["fumao_coins"] = int(account["fumao_coins"])
            return result

    def upgrade_stat(
        self, user_id: str, stat: str, amount: float, cost: int,
        crit_rate_cap: float, crit_damage_cap: float, now_ms: int,
    ) -> dict[str, Any]:
        columns = {
            "atk": "direct_atk", "def": "direct_def",
            "atk_percent": "direct_atk_percent", "def_percent": "direct_def_percent",
            "hp": "direct_hp", "hp_percent": "direct_hp_percent",
            "crit_rate": "direct_crit_rate", "crit_damage": "direct_crit_damage",
        }
        column = columns.get(stat)
        if column is None:
            raise ValueError("未知的 PvP 升級屬性")
        with self.base.lock, self._connect() as connection:
            profile = self._refresh(connection, str(user_id), int(now_ms))
            account = self._account(connection, str(user_id))
            if int(account["fumao_coins"]) < int(cost):
                profile.update(error="insufficient_funds", fumao_coins=int(account["fumao_coins"]))
                return profile
            old = float(profile[column])
            new = old + float(amount)
            if stat == "crit_rate":
                new = min(new, float(crit_rate_cap))
            if stat == "crit_damage":
                new = min(new, float(crit_damage_cap))
            if new <= old:
                profile.update(error="at_cap", fumao_coins=int(account["fumao_coins"]))
                return profile
            connection.execute(
                f"UPDATE pvp_profiles SET {column} = ?, updated_at = ? WHERE user_id = ?",
                (new, int(now_ms), str(user_id)),
            )
            connection.execute(
                "UPDATE economy_accounts SET fumao_coins = fumao_coins - ? WHERE user_id = ?",
                (int(cost), str(user_id)),
            )
            self.base._record_economy_currency_change(
                connection, str(user_id), "fumao_coins", -int(cost), f"PvP 升級 {stat}", int(now_ms)
            )
            result = self._select_profile(connection, str(user_id))
            result.update(changed=new - old, fumao_coins=int(account["fumao_coins"]) - int(cost))
            return result

    @staticmethod
    def _artifact(row: tuple[Any, ...]) -> dict[str, Any]:
        try:
            subs = json.loads(row[8])
        except (TypeError, json.JSONDecodeError):
            subs = {}
        return {
            "id": int(row[0]), "user_id": str(row[1]), "color": str(row[2]),
            "set_id": str(row[3]), "slot": str(row[4]), "level": int(row[5]),
            "main_stat": str(row[6]), "main_value": float(row[7]),
            "sub_stats": subs if isinstance(subs, dict) else {},
            "original_value": int(row[9]), "upgrade_cost": int(row[10]),
            "equipped": bool(row[11]), "created_at": int(row[12]),
        }

    def artifacts(self, user_id: str) -> list[dict[str, Any]]:
        with self.base.lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, user_id, color, set_id, slot, level, main_stat,
                       main_value, sub_stats, original_value, upgrade_cost,
                       equipped, created_at FROM pvp_artifacts
                WHERE user_id = ?
                ORDER BY level DESC,
                         CASE color
                             WHEN 'yellow' THEN 4
                             WHEN 'purple' THEN 3
                             WHEN 'blue' THEN 2
                             WHEN 'green' THEN 1
                             ELSE 0
                         END DESC,
                         equipped DESC, id
                """, (str(user_id),),
            ).fetchall()
            return [self._artifact(row) for row in rows]

    def add_artifact(self, user_id: str, artifact: dict[str, Any], now_ms: int) -> int:
        with self.base.lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO pvp_artifacts(
                    user_id, color, set_id, slot, level, main_stat, main_value,
                    sub_stats, original_value, upgrade_cost, equipped, created_at
                ) VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, 0, 0, ?)
                """,
                (
                    str(user_id), str(artifact.get("color", "green")), str(artifact.get("set_id", "")),
                    str(artifact["slot"]), str(artifact["main_stat"]), float(artifact.get("main_value", 0)),
                    json.dumps(artifact.get("sub_stats", {}), ensure_ascii=False),
                    int(artifact.get("original_value", 0)), int(now_ms),
                ),
            )
            return int(cursor.lastrowid)

    def equip_artifact(self, user_id: str, artifact_id: int) -> dict[str, Any]:
        with self.base.lock, self._connect() as connection:
            row = connection.execute(
                "SELECT slot FROM pvp_artifacts WHERE id = ? AND user_id = ?",
                (int(artifact_id), str(user_id)),
            ).fetchone()
            if row is None:
                raise ValueError("找不到這件聖遺物")
            connection.execute(
                "UPDATE pvp_artifacts SET equipped = 0 WHERE user_id = ? AND slot = ?",
                (str(user_id), str(row[0])),
            )
            connection.execute(
                "UPDATE pvp_artifacts SET equipped = 1 WHERE id = ? AND user_id = ?",
                (int(artifact_id), str(user_id)),
            )
            selected = connection.execute(
                """
                SELECT id, user_id, color, set_id, slot, level, main_stat,
                       main_value, sub_stats, original_value, upgrade_cost,
                       equipped, created_at FROM pvp_artifacts WHERE id = ?
                """, (int(artifact_id),),
            ).fetchone()
            return self._artifact(selected) if selected else {}

    def upgrade_artifact(
        self, user_id: str, artifact_id: int, max_level: int,
        cost: int, roll_stat: str | None, roll_amount: float,
        main_value: float, now_ms: int,
    ) -> dict[str, Any]:
        with self.base.lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, user_id, color, set_id, slot, level, main_stat,
                       main_value, sub_stats, original_value, upgrade_cost,
                       equipped, created_at FROM pvp_artifacts
                WHERE id = ? AND user_id = ?
                """, (int(artifact_id), str(user_id)),
            ).fetchone()
            if row is None:
                raise ValueError("找不到這件聖遺物")
            artifact = self._artifact(row)
            if artifact["level"] >= int(max_level):
                raise ValueError("這件聖遺物已達等級上限")
            account = self._account(connection, str(user_id))
            if int(account["fumao_coins"]) < int(cost):
                raise ValueError("芙帽幣不足")
            sub_stats = dict(artifact["sub_stats"])
            if roll_stat:
                sub_stats[roll_stat] = round(float(sub_stats.get(roll_stat, 0)) + float(roll_amount), 4)
                upgrade_counts = sub_stats.setdefault("__upgrade_counts__", {})
                if isinstance(upgrade_counts, dict):
                    upgrade_counts[roll_stat] = int(upgrade_counts.get(roll_stat, 0)) + 1
            new_level = artifact["level"] + 1
            connection.execute(
                """
                UPDATE pvp_artifacts
                SET level = ?, main_value = ?, sub_stats = ?, upgrade_cost = upgrade_cost + ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    new_level, float(main_value), json.dumps(sub_stats, ensure_ascii=False),
                    int(cost), int(artifact_id), str(user_id),
                ),
            )
            connection.execute(
                "UPDATE economy_accounts SET fumao_coins = fumao_coins - ? WHERE user_id = ?",
                (int(cost), str(user_id)),
            )
            self.base._record_economy_currency_change(
                connection, str(user_id), "fumao_coins", -int(cost), "PvP 聖遺物升級", int(now_ms)
            )
            updated = connection.execute(
                """
                SELECT id, user_id, color, set_id, slot, level, main_stat,
                       main_value, sub_stats, original_value, upgrade_cost,
                       equipped, created_at FROM pvp_artifacts WHERE id = ?
                """, (int(artifact_id),),
            ).fetchone()
            return self._artifact(updated)

    def upgrade_artifact_batch(
        self,
        user_id: str,
        artifact_id: int,
        max_level: int,
        upgrades: list[tuple[int, str | None, float, float]],
        now_ms: int,
    ) -> dict[str, Any]:
        """Apply several artifact levels atomically.

        Each tuple contains (coin_cost, rolled_sub_stat, rolled_value, main_value).
        """
        if not upgrades:
            raise ValueError("至少要升級 1 次")
        with self.base.lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, user_id, color, set_id, slot, level, main_stat,
                       main_value, sub_stats, original_value, upgrade_cost,
                       equipped, created_at FROM pvp_artifacts
                WHERE id = ? AND user_id = ?
                """, (int(artifact_id), str(user_id)),
            ).fetchone()
            if row is None:
                raise ValueError("找不到這件聖遺物")
            artifact = self._artifact(row)
            if artifact["level"] + len(upgrades) > int(max_level):
                raise ValueError("批量升級會超過這件聖遺物的等級上限")
            total_cost = sum(int(item[0]) for item in upgrades)
            account = self._account(connection, str(user_id))
            if int(account["fumao_coins"]) < total_cost:
                raise ValueError(f"芙帽幣不足，需要 {total_cost:,} 芙帽幣。")

            sub_stats = dict(artifact["sub_stats"])
            events: list[dict[str, Any]] = []
            level = int(artifact["level"])
            main_value = float(artifact["main_value"])
            for cost, roll_stat, roll_amount, next_main_value in upgrades:
                level += 1
                main_value = float(next_main_value)
                if roll_stat:
                    sub_stats[roll_stat] = round(float(sub_stats.get(roll_stat, 0)) + float(roll_amount), 4)
                    upgrade_counts = sub_stats.setdefault("__upgrade_counts__", {})
                    if isinstance(upgrade_counts, dict):
                        upgrade_counts[roll_stat] = int(upgrade_counts.get(roll_stat, 0)) + 1
                    events.append({"level": level, "stat": roll_stat, "amount": float(roll_amount)})

            connection.execute(
                """
                UPDATE pvp_artifacts
                SET level = ?, main_value = ?, sub_stats = ?, upgrade_cost = upgrade_cost + ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    level, main_value, json.dumps(sub_stats, ensure_ascii=False),
                    total_cost, int(artifact_id), str(user_id),
                ),
            )
            connection.execute(
                "UPDATE economy_accounts SET fumao_coins = fumao_coins - ? WHERE user_id = ?",
                (total_cost, str(user_id)),
            )
            self.base._record_economy_currency_change(
                connection, str(user_id), "fumao_coins", -total_cost,
                f"PvP 聖遺物批量升級 x{len(upgrades)}", int(now_ms),
            )
            updated = connection.execute(
                """
                SELECT id, user_id, color, set_id, slot, level, main_stat,
                       main_value, sub_stats, original_value, upgrade_cost,
                       equipped, created_at FROM pvp_artifacts WHERE id = ?
                """, (int(artifact_id),),
            ).fetchone()
            result = self._artifact(updated)
            result["upgrade_events"] = events
            result["upgrade_count"] = len(upgrades)
            result["total_cost"] = total_cost
            return result

    def charge_domain_entry(
        self,
        user_id: str,
        required_level: int,
        now_ms: int,
        base_cost_per_level: int = 1000,
        balance_rate: float = 0.01,
    ) -> dict[str, Any]:
        """Charge a domain entry fee based on its unlock level and current balance."""
        with self.base.lock, self._connect() as connection:
            account = self._account(connection, str(user_id))
            balance = int(account["fumao_coins"])
            cost = int(round(int(base_cost_per_level) * int(required_level) + balance * float(balance_rate)))
            if balance < cost:
                raise ValueError(
                    f"芙帽幣不足，進入此副本需要 {cost:,} 芙帽幣。"
                )
            connection.execute(
                "UPDATE economy_accounts SET fumao_coins = fumao_coins - ? WHERE user_id = ?",
                (cost, str(user_id)),
            )
            self.base._record_economy_currency_change(
                connection, str(user_id), "fumao_coins", -cost,
                f"PvP 秘境入場 Lv.{int(required_level)}", int(now_ms),
            )
            return {"cost": cost, "balance": balance - cost}

    def salvage_artifact(self, user_id: str, artifact_id: int, now_ms: int) -> int:
        with self.base.lock, self._connect() as connection:
            row = connection.execute(
                "SELECT original_value, upgrade_cost FROM pvp_artifacts WHERE id = ? AND user_id = ?",
                (int(artifact_id), str(user_id)),
            ).fetchone()
            if row is None:
                raise ValueError("找不到這件聖遺物")
            refund = int(row[0]) + int(int(row[1]) * 0.75)
            connection.execute(
                "DELETE FROM pvp_artifacts WHERE id = ? AND user_id = ?",
                (int(artifact_id), str(user_id)),
            )
            connection.execute(
                "UPDATE economy_accounts SET fumao_coins = fumao_coins + ? WHERE user_id = ?",
                (refund, str(user_id)),
            )
            self.base._record_economy_currency_change(
                connection, str(user_id), "fumao_coins", refund, "PvP 分解聖遺物", int(now_ms)
            )
            return refund

    def resolve_attack(
        self, attacker_id: str, defender_id: str, theft_amount: int,
        now_ms: int, details: dict[str, Any],
    ) -> dict[str, Any]:
        with self.base.lock, self._connect() as connection:
            attacker_profile = self._refresh(connection, str(attacker_id), int(now_ms))
            defender_profile = self._refresh(connection, str(defender_id), int(now_ms))
            if not attacker_profile["enabled"]:
                raise ValueError("你必須先開啟 PvP 才能攻擊")
            if not defender_profile["enabled"]:
                raise ValueError("對方目前沒有開啟 PvP")
            attacker = self._account(connection, str(attacker_id))
            defender = self._account(connection, str(defender_id))
            requested = max(0, int(theft_amount))
            remaining = max(0, defender_profile["loss_cap"] - defender_profile["lost_coins"])
            formula_loss = remaining + (requested - remaining) * 0.5 if requested > remaining else requested
            actual = min(int(defender["fumao_coins"]), max(0, int(formula_loss)))
            connection.execute(
                "UPDATE economy_accounts SET fumao_coins = fumao_coins + ? WHERE user_id = ?",
                (actual, str(attacker_id)),
            )
            connection.execute(
                "UPDATE economy_accounts SET fumao_coins = fumao_coins - ? WHERE user_id = ?",
                (actual, str(defender_id)),
            )
            lost = defender_profile["lost_coins"] + actual
            closed = requested > remaining or lost >= defender_profile["loss_cap"]
            connection.execute(
                """
                UPDATE pvp_profiles
                SET enabled = ?, lost_coins = ?,
                    toggle_cooldown_until = CASE WHEN ? THEN 0 ELSE toggle_cooldown_until END,
                    forced_cooldown_until = CASE WHEN ? THEN 0 ELSE forced_cooldown_until END,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (
                    0 if closed else 1,
                    lost,
                    1 if closed else 0,
                    1 if closed else 0,
                    int(now_ms),
                    str(defender_id),
                ),
            )
            payload = dict(details)
            payload.update({"requested_theft": requested, "actual_loss": actual,
                            "remaining_before": remaining, "closed": closed})
            for actor, target, action, amount in (
                (attacker_id, defender_id, "attack", actual),
                (defender_id, attacker_id, "defended", -actual),
            ):
                connection.execute(
                    """
                    INSERT INTO pvp_logs(actor_id, target_id, action, amount, details, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (str(actor), str(target), action, int(amount), json.dumps(payload, ensure_ascii=False), int(now_ms)),
                )
            self.base._record_economy_currency_change(
                connection, str(attacker_id), "fumao_coins", actual, "PvP 偷竊", int(now_ms)
            )
            self.base._record_economy_currency_change(
                connection, str(defender_id), "fumao_coins", -actual, "PvP 被偷竊", int(now_ms)
            )
            return {
                "amount": actual, "requested_amount": requested, "closed": closed,
                "attacker_balance": int(attacker["fumao_coins"]) + actual,
                "defender_balance": int(defender["fumao_coins"]) - actual,
                "defender_lost": lost, "defender_cap": defender_profile["loss_cap"],
            }
