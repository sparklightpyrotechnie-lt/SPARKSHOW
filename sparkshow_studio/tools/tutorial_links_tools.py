import os
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import bpy


class TutorialLinks:
    def __init__(self, path: list[str] | None = None) -> None:
        self.base_url = os.environ.get("SPARKSHOW_HELP_URL", "").rstrip("/")
        self.path = path or []

    def __getattr__(self, name: str) -> "TutorialLinks":
        return TutorialLinks([*self.path, name])

    def __str__(self) -> str:
        if not self.base_url:
            return ""
        return "/".join([self.base_url, *self.path])

    def __repr__(self) -> str:
        return str(self)


link = TutorialLinks()


def draw_tutorial_button(  # noqa: PLR0913
    layout: "bpy.types.UILayout",
    context: "bpy.types.Context",
    main_button_fn: Callable[["bpy.types.UILayout"], Any] | None,
    section: TutorialLinks,
    option: str = "",
    text: str = "Getting Started",
) -> None:
    help_url = str(section).replace("_", "-")
    if option:
        help_url += f"#{option}".replace(" ", "-").replace("_", "-")

    # During addon registration Blender may redraw panels before AddonPreferences
    # has been registered. Never let the tutorial UI prevent the panel from drawing.
    addon = context.preferences.addons.get("sparkshow_studio")
    prefs = addon.preferences if addon is not None else None
    if prefs is not None and prefs.help_enable and help_url:  # pyright: ignore
        if main_button_fn is None:
            box = layout.box()
            row = box.row()

            split = row.split(factor=0.2)
            split.column()

            center_split = split.split(factor=0.8)
            col = center_split.column()
            col.alignment = "CENTER"

            op = col.operator("wm.url_open", text=text, icon="QUESTION")
            op.url = help_url  # pyright: ignore

            center_split.column()
            return

        row = layout.row()
        split = row.split(factor=0.7)
        col1 = split.column()
        col2 = split.column()

        main_button_fn(col1)

        op = col2.operator("wm.url_open", text="Help", icon="QUESTION")
        op.url = help_url  # pyright: ignore
    elif main_button_fn is not None:
        main_button_fn(layout)
