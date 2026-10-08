from typing import Literal

import bpy

from ..base import BasePanelHideIfNoDrone
from ..tools.tutorial_links_tools import draw_tutorial_button, link

KeyframeType = Literal["KEYFRAME", "BREAKDOWN", "MOVING_HOLD", "EXTREME", "JITTER"]


class LIGHTSHOW_PT_take_off_land_main_panel(BasePanelHideIfNoDrone):
    bl_parent_id = "SPARKSHOW_STUDIO_PT_show"
    bl_label = "🚀 Take off & Land"
    bl_idname = "LIGHTSHOW_PT_take_off_land_main_panel"

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        draw_tutorial_button(
            layout,
            context,
            main_button_fn=None,
            section=link.takeoff_and_land,
        )


classes = [
    LIGHTSHOW_PT_take_off_land_main_panel,
]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in classes:
        bpy.utils.unregister_class(cls)
