import bpy

from .tools.collection_tools import get_drones


class SPARKSHOW_STUDIO_PT_status(bpy.types.Panel):
    bl_label = "Status"
    bl_idname = "SPARKSHOW_STUDIO_PT_status"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "sparkshow"
    bl_parent_id = "LIGHTSHOW_PT_main_panel"
    bl_options = set()

    def draw_header(self, context):
        self.layout.label(text="", icon="INFO")

    def draw(self, context):
        scene = context.scene
        layout = self.layout
        drones = get_drones(scene.collection)
        fire_preview = getattr(getattr(scene, "lightshow", None), "fire_preview_enabled", False)
        rows = [
            ("Drones", str(len(drones)), "OBJECT_DATA"),
            ("Pyro collection", str(len(bpy.data.collections.get("Sparkshow Pyrotechnics").objects) if bpy.data.collections.get("Sparkshow Pyrotechnics") else 0), "LIGHT_POINT"),
            ("Frame", f"{scene.frame_current} / {scene.frame_end}", "TIME"),
            ("Pyro preview", "ON" if fire_preview else "OFF", "HIDE_OFF" if fire_preview else "HIDE_ON"),
        ]
        for label, value, icon in rows:
            row = layout.row(align=True)
            row.label(text=label, icon=icon)
            row.label(text=value)


def register():
    bpy.utils.register_class(SPARKSHOW_STUDIO_PT_status)


def unregister():
    try:
        bpy.utils.unregister_class(SPARKSHOW_STUDIO_PT_status)
    except RuntimeError:
        pass
