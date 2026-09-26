from dataclasses import dataclass

from config import Config
from discord_api import DiscordApi
from storage import WorshipStore


@dataclass(frozen=True)
class CommandContext:
    config: Config
    store: WorshipStore
    discord_api: DiscordApi
