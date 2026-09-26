"""Small CLI entry point for the Discord Gateway bot."""

from __future__ import annotations

import argparse
import logging
import os

from config import Config, first_environment_name
from gateway import run_gateway


def main() -> int:
    parser = argparse.ArgumentParser(description="芙帽 Discord /worship 機器人")
    parser.add_argument("command", nargs="?", choices=("gateway",), default="gateway")
    parser.parse_args()

    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    config = Config.from_env()
    logging.getLogger("fumao-worship-bot").info(
        "Discord token source=%s, length=%d",
        first_environment_name("DISCORD_BOT_TOKEN", "DISCORD_TOKEN", "BOT_TOKEN", "TOKEN"),
        len(config.bot_token),
    )
    run_gateway(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
