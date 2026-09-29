"""JSON-backed PvP and artifact configuration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
JSON_DIR = ROOT / "json"


def _load(name: str) -> dict[str, Any]:
    path = JSON_DIR / name
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"PvP 設定檔無法讀取：{path}") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"PvP 設定檔必須是 JSON 物件：{path}")
    return value


PVP_CONFIG = _load("pvp_config.json")
ARTIFACT_CONFIG = _load("artifacts.json")


def pvp_rules() -> dict[str, Any]:
    return PVP_CONFIG["rules"]


def direct_upgrade_config() -> dict[str, Any]:
    return PVP_CONFIG["direct_upgrade"]


def artifact_color(color: str) -> dict[str, Any]:
    return PVP_CONFIG["artifact_colors"].get(
        color,
        PVP_CONFIG["artifact_colors"]["green"],
    )


def artifact_domain(domain_id: str | None = None) -> dict[str, Any] | None:
    domains = ARTIFACT_CONFIG.get("domains", [])
    if not domains:
        return None
    if domain_id is None:
        return domains[0]
    return next((item for item in domains if item.get("id") == domain_id), None)
