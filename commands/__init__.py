"""Command registry. Add new command modules here."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from commands.context import CommandContext


def register_all(tree, discord, app_commands, context: CommandContext) -> None:
    from commands.worship import register_worship

    register_worship(tree, discord, app_commands, context)
