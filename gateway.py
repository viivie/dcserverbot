"""Discord Gateway runtime and slash-command synchronization."""

from __future__ import annotations

import logging

from commands import register_all
from commands.context import CommandContext
from config import ID_RE, Config
from discord_api import DiscordApi
from storage import WorshipStore

LOGGER = logging.getLogger("fumao-worship-bot")
PRESENCE_TEXT = "正在膜拜芙帽🛐🛐🛐"


def run_gateway(config: Config) -> None:
    if not config.bot_token:
        raise RuntimeError("Gateway 模式需要設定 Discord Bot Token")
    try:
        import discord
        from discord import app_commands
    except ImportError as exc:
        raise RuntimeError("Gateway 模式需要安裝 discord.py：pip install -r requirements.txt") from exc

    store = WorshipStore(config.data_file)
    context = CommandContext(config, store, DiscordApi(config, store))
    intents = discord.Intents.default()
    intents.message_content = True

    class GatewayClient(discord.Client):
        def __init__(self) -> None:
            super().__init__(intents=intents, activity=discord.CustomActivity(name=PRESENCE_TEXT))
            self.tree = app_commands.CommandTree(self)
            self.commands_synced = False

        async def setup_hook(self) -> None:
            # Remove the old global command. The bot only publishes guild commands,
            # so Discord will show one /worship per server instead of two entries.
            try:
                for command in await self.tree.fetch_commands():
                    if command.name == "worship":
                        await command.delete()
                        LOGGER.info("removed stale global /worship command")
            except discord.HTTPException as error:
                LOGGER.warning("could not remove stale global /worship: %s", error)

            if config.guild_id and ID_RE.fullmatch(config.guild_id):
                guild = discord.Object(id=int(config.guild_id))
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                LOGGER.info("synced /worship to guild %s", config.guild_id)
            else:
                LOGGER.info("guild sync will run after login")

    client = GatewayClient()
    register_all(client.tree, discord, app_commands, context)

    @client.event
    async def on_ready() -> None:
        LOGGER.info("logged in as %s", client.user)
        if client.commands_synced or config.guild_id:
            return
        for guild in client.guilds:
            try:
                client.tree.copy_global_to(guild=guild)
                await client.tree.sync(guild=guild)
                LOGGER.info("synced /worship to guild %s (%s)", guild.id, guild.name)
            except discord.HTTPException as error:
                LOGGER.warning("could not sync /worship to guild %s: %s", guild.id, error)
        client.commands_synced = True

    @client.event
    async def on_message(message) -> None:
        from commands.admin import handle_admin_message

        await handle_admin_message(message)

    client.run(config.bot_token)
