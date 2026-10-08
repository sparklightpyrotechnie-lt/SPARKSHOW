import bpy

from ....base import BaseOperator
from ....setup import get_lightshow
from ....tools.takeoff_land_tools import get_selected_drones_to_land
from ....tools.tutorial_links_tools import draw_tutorial_button, link
from ...utils import keyframe_location
from ..land_base import LandBasePanel
from ..utils import land_drone, remove_constraints_influence


class LIGHTSHOW_PT_manual_land_panel(LandBasePanel):
    bl_label = "\t\tManual Land"
    bl_idname = "LIGHTSHOW_PT_manual_land"
    bl_parent_id = "LIGHTSHOW_PT_land_panel"
    bl_options = {"HIDE_HEADER"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        scene = context.scene
        lightshow = get_lightshow(scene)
        return super().poll(context) and lightshow.takeoff_mode != "using all in one platform"

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        draw_tutorial_button(
            layout,
            context,
            main_button_fn=lambda col: col.operator("lightshow.land", icon="PLAY"),
            section=link.takeoff_and_land,
            option="manual_land",
        )


class LIGHTSHOW_OT_land(BaseOperator):
    bl_label = "Land"
    bl_description = """\
Land the selected drones
The drones should be located around 2 meters above the ground before landing"""
    bl_idname = "lightshow.land"

    def execute(self, context: bpy.types.Context) -> set[str]:
        scene = context.scene

        (
            drones_to_land,
            has_unselected_land_drones,
            has_unselected_takeoff_drones,
        ) = get_selected_drones_to_land(context)
        lightshow = get_lightshow(scene)

        warning_messages: list[str] = []

        if has_unselected_takeoff_drones:
            warning_messages.append(
                "Some selected drones have not taken off, they will be ignored",
            )
        if has_unselected_land_drones:
            warning_messages.append(
                "Some selected drones have already landed, they will be ignored",
            )
        if not drones_to_land:
            self.report_print({"ERROR"}, "No selected drones to land")
            return {"CANCELLED"}
        if warning_messages:
            self.report_print(
                {"WARNING"},
                "\n".join(warning_messages),
            )

        land_start_frame = scene.frame_current
        land_last_frame = scene.frame_current

        for drone in drones_to_land:
            location = drone.matrix_world.to_translation()
            remove_constraints_influence(scene, lightshow, drone)

            # Add a keyframe before the land to avoid an interpolation between a previous keyframe and the land
            keyframe_location(drone, frame=land_start_frame - 1)

            last_end_frame = land_drone(lightshow, drone, location, land_start_frame)
            land_last_frame = max(land_last_frame, last_end_frame)

        if lightshow.land_marker and len(drones_to_land) > 1:
            scene.timeline_markers.new("Land start", frame=scene.frame_current)
            scene.timeline_markers.new("Land end", frame=land_last_frame)
        scene.frame_set(land_last_frame)

        return {"FINISHED"}


classes = (
    LIGHTSHOW_PT_manual_land_panel,
    LIGHTSHOW_OT_land,
)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in classes:
        bpy.utils.unregister_class(cls)
