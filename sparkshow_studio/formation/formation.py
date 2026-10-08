import bpy

from ..base import BasePanelHideIfNoDrone


class LIGHTSHOW_PT_formation(BasePanelHideIfNoDrone):
    bl_parent_id = "SPARKSHOW_STUDIO_PT_show"
    bl_label = "Formation"
    bl_idname = "LIGHTSHOW_PT_formation"

    def draw_header(self, context: bpy.types.Context) -> None:  # noqa: ARG002
        layout = self.layout
        layout.label(icon="LIGHTPROBE_VOLUME")

    def draw(self, context: bpy.types.Context) -> None:  # noqa: ARG002
        return


classes = [
    LIGHTSHOW_PT_formation,
]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in classes:
        bpy.utils.unregister_class(cls)
