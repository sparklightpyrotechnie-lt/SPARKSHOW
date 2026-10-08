import bpy

from ...setup import get_lightshow
from ...tools.tutorial_links_tools import draw_tutorial_button, link
from ..check import CheckBase, CheckBasePanel
from ..check_algorithm import apply_collision_check


class LIGHTSHOW_PT_proximity(CheckBasePanel):
    bl_label = "Proximity Check"
    bl_idname = "LIGHTSHOW_PT_proximity"
    bl_parent_id = "LIGHTSHOW_PT_check_group"  # Grouping under main
    bl_options = {"HIDE_HEADER"}

    def draw(self, context: bpy.types.Context) -> None:
        lightshow = get_lightshow(context.scene)
        layout = self.layout
        layout.use_property_decorate = False

        row = layout.row()
        draw_tutorial_button(
            row,
            context,
            lambda col: col.prop(lightshow, "enable_proximity_warning"),
            section=link.check.proximity,
        )
        if lightshow.enable_proximity_warning:
            proximity_lines = bpy.data.objects.get("Proximity Lines")
            if proximity_lines is None:
                layout.label(text="Proximity Lines not found", icon="ERROR")
            else:
                depsgraph = bpy.context.evaluated_depsgraph_get()
                nb_lines = int(len(proximity_lines.evaluated_get(depsgraph).to_mesh().vertices) / 8)
                layout.label(
                    text=f"{nb_lines} warning(s) at current frame"
                    if nb_lines > 0
                    else "No warning at current frame",
                    icon="ERROR" if nb_lines > 0 else "CHECKMARK",
                )
        layout.use_property_split = True
        layout.prop(lightshow, "collision_distance")
        layout.operator("lightshow.check_collisions")


class LIGHTSHOW_OT_check_collisions(CheckBase):
    bl_label = "Check collisions"
    bl_description = """\
Check if the selected drones collide with each other in the frame range of the scene"""
    bl_idname = "lightshow.check_collisions"

    def execute(self, context: bpy.types.Context) -> set[str]:
        scene = context.scene
        frame_start, frame_end = scene.frame_start, scene.frame_end

        drones = self.get_taken_off_drones(context, 2)
        if not drones:
            return {"CANCELLED"}

        check_result, _ = apply_collision_check(
            drones,
            frame_start,
            frame_end,
            scene,
        )
        if check_result != "OK":
            self.report_print(
                {"ERROR"},
                check_result,
            )
            return {"CANCELLED"}
        self.report_print(
            {"INFO"},
            "The collision check has successfully passed",
        )
        return {"FINISHED"}


classes = [
    LIGHTSHOW_PT_proximity,
    LIGHTSHOW_OT_check_collisions,
]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in classes:
        bpy.utils.unregister_class(cls)
