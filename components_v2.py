"""Shared Discord Components V2 card helpers."""

from __future__ import annotations

import discord


def _embed_color(embed: discord.Embed) -> int | None:
    colour = getattr(embed, "colour", None)
    return getattr(colour, "value", None) if colour else None


def _clone_button(source: discord.ui.Button) -> discord.ui.Button:
    """Copy a legacy button while retaining its bound callback."""
    button = discord.ui.Button(
        style=source.style,
        label=source.label,
        disabled=source.disabled,
        emoji=source.emoji,
        custom_id=source.custom_id,
        url=source.url,
    )
    if source.url is None:
        button.callback = source.callback
    return button


class V2CardView(discord.ui.LayoutView):
    """Render an existing Embed-shaped card as a Components V2 layout."""

    def __init__(
        self,
        embed: discord.Embed,
        *,
        content: str | None = None,
        legacy_view: discord.ui.View | None = None,
    ) -> None:
        timeout = legacy_view.timeout if legacy_view is not None else 180.0
        super().__init__(timeout=timeout)
        self.legacy_view = legacy_view

        container = discord.ui.Container(accent_color=_embed_color(embed))
        title = getattr(embed, "title", None)
        description = getattr(embed, "description", None)
        thumbnail_url = getattr(getattr(embed, "thumbnail", None), "url", None)

        heading_parts: list[str] = []
        if content:
            heading_parts.append(content)
        if title:
            heading_parts.append(f"## {title}")
        if description:
            heading_parts.append(description)
        if heading_parts:
            heading = discord.ui.TextDisplay("\n".join(heading_parts))
            if thumbnail_url:
                container.add_item(
                    discord.ui.Section(
                        heading,
                        accessory=discord.ui.Thumbnail(str(thumbnail_url)),
                    )
                )
            else:
                container.add_item(heading)

        for field in getattr(embed, "fields", ()):
            container.add_item(discord.ui.Separator())
            container.add_item(
                discord.ui.TextDisplay(
                    f"### {field.name}\n{field.value}"
                )
            )

        image_url = getattr(getattr(embed, "image", None), "url", None)
        if image_url:
            container.add_item(discord.ui.Separator())
            gallery = discord.ui.MediaGallery()
            gallery.add_item(media=str(image_url))
            container.add_item(gallery)

        footer_text = getattr(getattr(embed, "footer", None), "text", None)
        if footer_text:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(f"-# {footer_text}"))

        if legacy_view is not None:
            buttons = [
                item
                for item in legacy_view.children
                if isinstance(item, discord.ui.Button)
            ]
            if buttons:
                container.add_item(discord.ui.Separator())
                action_row = discord.ui.ActionRow()
                for button in buttons:
                    action_row.add_item(_clone_button(button))
                container.add_item(action_row)

        self.add_item(container)

    async def on_timeout(self) -> None:
        if self.legacy_view is not None:
            await self.legacy_view.on_timeout()
        self.stop()


def v2_view_from_embed(
    embed: discord.Embed,
    *,
    content: str | None = None,
    legacy_view: discord.ui.View | None = None,
) -> V2CardView:
    return V2CardView(embed, content=content, legacy_view=legacy_view)
