"""PvP formulas and artifact generation."""

from __future__ import annotations

import random
from typing import Any

from .config import ARTIFACT_CONFIG, PVP_CONFIG, artifact_color


STAT_KEYS = (
    "atk", "def", "hp", "atk_percent", "def_percent", "hp_percent",
    "crit_rate", "crit_damage", "final_damage_increase", "final_damage_reduction",
)


def level_multiplier(level: int) -> float:
    return 1.0 + 0.015 * max(0, int(level) - 10) ** 1.8


def equipped_stats(profile: dict[str, Any], artifacts: list[dict[str, Any]]) -> dict[str, float]:
    stats = {key: 0.0 for key in STAT_KEYS}
    for key in STAT_KEYS:
        stats[key] += float(profile.get(f"direct_{key}", 0))
    for artifact in artifacts:
        if not artifact.get("equipped"):
            continue
        main_stat = str(artifact.get("main_stat", ""))
        if main_stat in stats:
            stats[main_stat] += float(artifact.get("main_value", 0))
        for key, value in artifact.get("sub_stats", {}).items():
            if key in stats:
                stats[key] += float(value)

    set_counts: dict[str, int] = {}
    for artifact in artifacts:
        if artifact.get("equipped") and artifact.get("set_id"):
            set_counts[str(artifact["set_id"])] = set_counts.get(str(artifact["set_id"]), 0) + 1
    for set_id, count in set_counts.items():
        set_data = ARTIFACT_CONFIG.get("sets", {}).get(set_id, {})
        # A set's always_stats are applied once, not once per equipped piece.
        for stat, value in set_data.get("always_stats", {}).items():
            if stat in stats:
                stats[stat] += float(value)
        for threshold, key in ((2, "two_piece"), (4, "four_piece")):
            if count >= threshold:
                for stat, value in set_data.get(key, {}).get("stats", {}).items():
                    if stat in stats:
                        stats[stat] += float(value)
    return stats


def calculate_damage(profile: dict[str, Any], artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    stats = equipped_stats(profile, artifacts)
    base = PVP_CONFIG["base_stats"]
    atk = (float(base["atk"]) + stats["atk"]) * (1.0 + stats["atk_percent"])
    defense = (float(base["def"]) + stats["def"]) * (1.0 + stats["def_percent"])
    hp = (float(base["hp"]) + stats["hp"]) * (1.0 + stats["hp_percent"])
    k_atk = random.uniform(float(PVP_CONFIG["damage"]["k_min"]), float(PVP_CONFIG["damage"]["k_max"]))
    k_def = random.uniform(float(PVP_CONFIG["damage"]["k_min"]), float(PVP_CONFIG["damage"]["k_max"]))
    crit_rate = min(1.0, max(0.0, stats["crit_rate"]))
    critical = random.random() < crit_rate
    multiplier = 1.0 + stats["crit_damage"] if critical else 1.0
    atk_level = level_multiplier(int(profile.get("level", 1)))
    def_level = level_multiplier(int(profile.get("level", 1)))
    # ATK% and DEF% are represented as decimals; both use the requested 1+X form.
    raw = atk * k_atk * multiplier * atk_level * 100.0 / (
        100.0 + defense * k_def * def_level
    )
    final_increase = float(stats.get("final_damage_increase", 0.0))
    final_reduction = min(1.0, max(0.0, float(stats.get("final_damage_reduction", 0.0))))
    damage = max(0.0, raw * (1.0 + final_increase) * (1.0 - final_reduction))
    return {
        "damage": damage,
        "r": damage / 100.0,
        "critical": critical,
        "crit_rate": crit_rate,
        "crit_damage": stats["crit_damage"],
        "k_atk": k_atk,
        "k_def": k_def,
        "attack": atk,
        "defense": defense,
        "hp": hp,
        "stats": stats,
    }


def _sub_value(stat: str, color: str) -> float:
    data = ARTIFACT_CONFIG.get("sub_stats", {}).get(stat, {})
    values = data.get("yellow") or data.get("purple") or [0]
    value = float(random.choice(values))
    return round(value * float(artifact_color(color).get("ratio", 1.0)), 4)


def generate_artifact(color: str, set_id: str = "", slot: str | None = None) -> dict[str, Any]:
    color_data = artifact_color(color)
    color = color if color in PVP_CONFIG["artifact_colors"] else "green"
    slots = ARTIFACT_CONFIG.get("slots", ["生之花", "死之羽", "時之沙", "空之杯", "理之冠"])
    main_stats = ARTIFACT_CONFIG.get("main_stats", {})
    main_stat = random.choice(list(main_stats))
    main_value = float(main_stats[main_stat].get(color, 0))
    sub_count = {"green": 2, "blue": 3, "purple": 4, "yellow": 4}.get(color, 2)
    pool = [key for key in ARTIFACT_CONFIG.get("sub_stats", {}) if key != main_stat]
    random.shuffle(pool)
    sub_stats = {key: _sub_value(key, color) for key in pool[:sub_count]}
    return {
        "color": color,
        "set_id": set_id,
        "slot": slot or random.choice(slots),
        "main_stat": main_stat,
        "main_value": main_value,
        "sub_stats": sub_stats,
        "original_value": int(color_data.get("original_value", color_data.get("max_level", 0) * 1000)),
    }


def drop_count(domain: dict[str, Any], color: str, difficulty: int) -> int:
    rule = domain.get("drop_rules", {}).get(color, {}).get(str(int(difficulty)))
    if not isinstance(rule, dict):
        return 0
    if "guaranteed" in rule:
        count = int(rule["guaranteed"])
        if "max" in rule:
            return random.randint(count, int(rule["max"]))
        if rule.get("extra_chance", 0) and random.random() < float(rule["extra_chance"]):
            count += 1
        return count
    if random.random() >= float(rule.get("chance", 0)):
        return 0
    return random.randint(1, int(rule.get("max", 1)))
