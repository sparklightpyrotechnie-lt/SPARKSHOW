import bpy

from ..base import BasePanelHideIfNoDrone
from ..tools.tutorial_links_tools import draw_tutorial_button, link


class LIGHTSHOW_PT_color(BasePanelHideIfNoDrone):
    bl_parent_id = "SPARKSHOW_STUDIO_PT_lighting"
    bl_label = "Color"
    bl_idname = "LIGHTSHOW_PT_color"

    def draw_header(self, context: bpy.types.Context) -> None:  # noqa: ARG002
        layout = self.layout
        layout.label(icon="COLORSET_10_VEC")

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        draw_tutorial_button(
            layout,
            context,
            main_button_fn=None,
            section=link.color,
            option="",
        )
        props = getattr(context.scene, "color_properties", None)
        if props is None:
            layout.label(text="Color properties not found", icon="ERROR")
            return
        layout.prop(props, "color_type", text="Mode", expand=True)


class ColorBasePanel(BasePanelHideIfNoDrone):
    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        scene = context.scene
        props = getattr(scene, "color_properties", None)
        return props and cls.bl_idname == "LIGHTSHOW_PT_" + props.color_type.lower().replace(
            " ", "_"
        )


classes = [
    LIGHTSHOW_PT_color,
]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in classes:
        bpy.utils.unregister_class(cls)
