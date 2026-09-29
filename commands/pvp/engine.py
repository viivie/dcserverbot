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


def calculate_damage(
    profile: dict[str, Any],
    artifacts: list[dict[str, Any]],
    defender_profile: dict[str, Any] | None = None,
    defender_artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Calculate total damage using separate attacker and defender stats."""
    defender_profile = defender_profile or profile
    defender_artifacts = artifacts if defender_artifacts is None else defender_artifacts
    attacker_stats = equipped_stats(profile, artifacts)
    defender_stats = equipped_stats(defender_profile, defender_artifacts)
    base = PVP_CONFIG["base_stats"]
    atk = (float(base["atk"]) + attacker_stats["atk"]) * (1.0 + attacker_stats["atk_percent"])
    defense = (float(base["def"]) + defender_stats["def"]) * (1.0 + defender_stats["def_percent"])
    hp = (float(base["hp"]) + attacker_stats["hp"]) * (1.0 + attacker_stats["hp_percent"])
    attack_count = max(
        1,
        min(
            int(PVP_CONFIG["damage"].get("max_attacks", 3)),
            int(profile.get("attack_count", PVP_CONFIG["damage"].get("initial_attacks", 1))),
        ),
    )
    k_atk_values: list[float] = []
    k_def_values: list[float] = []
    hit_results: list[dict[str, Any]] = []
    attacker_level = level_multiplier(int(profile.get("level", 1)))
    defender_level = level_multiplier(int(defender_profile.get("level", 1)))
    crit_rate = min(1.0, max(0.0, attacker_stats["crit_rate"]))
    final_increase = float(attacker_stats.get("final_damage_increase", 0.0))
    final_reduction = min(1.0, max(0.0, float(defender_stats.get("final_damage_reduction", 0.0))))

    for _ in range(attack_count):
        k_atk = random.uniform(float(PVP_CONFIG["damage"]["k_min"]), float(PVP_CONFIG["damage"]["k_max"]))
        k_def = random.uniform(float(PVP_CONFIG["damage"]["k_min"]), float(PVP_CONFIG["damage"]["k_max"]))
        critical = random.random() < crit_rate
        multiplier = 1.0 + attacker_stats["crit_damage"] if critical else 1.0
        # ATK% and DEF% are represented as decimals; both use the requested 1+X form.
        raw = atk * k_atk * multiplier * attacker_level * 100.0 / (
            100.0 + defense * k_def * defender_level
        )
        hit_damage = max(0.0, raw * (1.0 + final_increase) * (1.0 - final_reduction))
        k_atk_values.append(k_atk)
        k_def_values.append(k_def)
        hit_results.append({"damage": hit_damage, "critical": critical, "k_atk": k_atk, "k_def": k_def})

    damage = sum(float(hit["damage"]) for hit in hit_results)
    critical = any(bool(hit["critical"]) for hit in hit_results)
    return {
        "damage": damage,
        "r": damage / 100.0,
        "critical": critical,
        "crit_rate": crit_rate,
        "crit_damage": attacker_stats["crit_damage"],
        "k_atk": k_atk_values[0],
        "k_def": k_def_values[0],
        "k_atk_values": k_atk_values,
        "k_def_values": k_def_values,
        "hits": hit_results,
        "attack_count": attack_count,
        "attack": atk,
        "defense": defense,
        "hp": hp,
        "attacker_stats": attacker_stats,
        "defender_stats": defender_stats,
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
    max_level = int(color_data.get("max_level", 1))
    max_main_value = float(main_stats[main_stat].get(color, 0))
    main_value = round(max_main_value / max_level, 4)
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
