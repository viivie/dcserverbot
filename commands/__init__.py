"""Command registry. Add new command modules here."""

from commands.context import CommandContext
from commands.worship import register_worship


def register_all(tree, discord, app_commands, context: CommandContext) -> None:
    register_worship(tree, discord, app_commands, context)
