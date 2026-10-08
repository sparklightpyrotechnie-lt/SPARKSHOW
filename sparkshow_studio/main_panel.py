import bpy

from .base import BaseOperator
from .setup import FPS, get_lightshow
from .tools.collection_tools import get_drones


def get_fps(scene: bpy.types.Scene) -> float:
    if scene.render.fps_base == 1.0:
        return round(scene.render.fps)
    return round(scene.render.fps / scene.render.fps_base, 2)


class LIGHTSHOW_PT_main_panel(bpy.types.Panel):
    bl_label = "Sparkshow Studio"
    bl_idname = "LIGHTSHOW_PT_main_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "sparkshow"

    def draw(self, context: bpy.types.Context) -> None:
        scene = context.scene
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        lightshow = get_lightshow(scene)
        drones = get_drones(scene.collection)
        pyro = bpy.data.collections.get("Sparkshow Pyrotechnics")
        pyro_count = len(pyro.objects) if pyro else 0

        header = layout.box()
        header.label(text="SPARKSHOW STUDIO", icon="LIGHT")
        row = header.row(align=True)
        row.label(text=f"{len(drones):,} drones".replace(",", " "), icon="OBJECT_DATA")
        row.label(text=f"F{scene.frame_current}", icon="TIME")
        row.label(text=f"{scene.frame_start}–{scene.frame_end}")

        state = header.row(align=True)
        initialized = len(drones) > 0
        state.label(
            text="SHOW READY" if initialized else "SETUP REQUIRED",
            icon="CHECKMARK" if initialized else "INFO",
        )
        state.label(text=f"Pyro {pyro_count}", icon="LIGHT_POINT")

        fps = get_fps(scene)
        if fps != FPS:
            warn = header.row(align=True)
            warn.label(text=f"Timeline FPS: {fps} (recommended {FPS})", icon="ERROR")
            warn.operator("lightshow.reset_fps", text="Reset", icon="FILE_REFRESH")

        if getattr(lightshow, "dev_mode", False):
            debug = layout.box()
            debug.label(text="Developer", icon="CONSOLE")
            debug.prop(lightshow, "dev_mode")


class LIGHTSHOW_OP_reset_fps(BaseOperator):
    bl_idname = "lightshow.reset_fps"
    bl_label = "Reset FPS"
    bl_description = f"Reset FPS to {FPS}"

    def execute(self, context: bpy.types.Context) -> set[str]:
        context.scene.render.fps = FPS
        context.scene.render.fps_base = 1
        return {"FINISHED"}


classes = [
    LIGHTSHOW_PT_main_panel,
    LIGHTSHOW_OP_reset_fps,
]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in classes:
        bpy.utils.unregister_class(cls)
