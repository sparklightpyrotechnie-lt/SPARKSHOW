import bpy

from sparkshow_studio._loader.parameters import IOSTAR_PHYSIC_PARAMETERS_RECOMMENDATION

from ....base import BaseOperator
from ....setup import get_lightshow
from ....tools.scene_tools import get_grid_position
from ....tools.takeoff_land_tools import get_selected_drones_to_takeoff
from ....tools.tutorial_links_tools import draw_tutorial_button, link
from ..take_off_base import TakeOffBasePanel
from ..utils import get_takeoff_frames, takeoff_drone


class LIGHTSHOW_PT_takeoff_panel(TakeOffBasePanel):
    bl_label = "\t\tManual Take Off"
    bl_idname = "LIGHTSHOW_PT_manual_take_off"
    bl_parent_id = "LIGHTSHOW_PT_take_off_panel"
    bl_options = {"HIDE_HEADER"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        scene = context.scene
        lightshow = get_lightshow(scene)
        return super().poll(context) and lightshow.takeoff_mode != "using all in one platform"

    def draw(self, context: bpy.types.Context) -> None:
        scene = context.scene
        lightshow = get_lightshow(scene)

        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        props = getattr(context.scene, "takeoff_props", None)
        assert props is not None, "Takeoff properties not found in the scene"

        draw_tutorial_button(
            layout,
            context,
            main_button_fn=None,
            section=link.takeoff_and_land,
            option="manual_takeoff",
        )

        layout.prop(lightshow, "takeoff_altitude")
        row = layout.row()
        row.operator("lightshow.takeoff", icon="PLAY")


class LIGHTSHOW_OT_takeoff(BaseOperator):
    bl_label = "Takeoff"
    bl_description = """\
Takeoff the selected drones to the specified altitude
Only the first drone of each family that has not taken off will take off"""
    bl_idname = "lightshow.takeoff"

    _counter: int = 0
    _safety_distance: float = 0.5

    def execute(self, context: bpy.types.Context) -> set[str]:  # noqa: C901
        scene = context.scene
        lightshow = get_lightshow(scene)
        props = getattr(scene, "takeoff_props", None)
        if props is None:
            self.report_print({"ERROR"}, "Takeoff properties not found in the scene")
            return {"CANCELLED"}

        drones_to_takeoff, has_unselected_takeoff_drones = get_selected_drones_to_takeoff(context)

        if has_unselected_takeoff_drones and not drones_to_takeoff:
            self.report_print(
                {"WARNING"},
                "All selected drones have already taken off",
            )
            return {"CANCELLED"}

        if not drones_to_takeoff:
            self.report_print({"WARNING"}, "No selected drones to takeoff")
            return {"CANCELLED"}

        if has_unselected_takeoff_drones and drones_to_takeoff:
            self.report_print(
                {"WARNING"},
                "Some selected drones have already taken off, they will be ignored",
            )

        frame_start_takeoff, frame_middle_takeoff, frame_end_takeoff = get_takeoff_frames(
            scene, lightshow
        )

        takeoff_positions = []
        if lightshow.takeoff_mode == "using all in one platform":
            # taking off and going to the grid position
            positions = [
                get_grid_position(
                    x,
                    lightshow.nb_x,
                    y,
                    lightshow.nb_y,
                    step_x=IOSTAR_PHYSIC_PARAMETERS_RECOMMENDATION.minimum_distance
                    + self._safety_distance,
                    step_y=IOSTAR_PHYSIC_PARAMETERS_RECOMMENDATION.minimum_distance
                    + self._safety_distance,
                    angle=lightshow.angle_takeoff,
                )
                for y in range(lightshow.nb_y)
                for x in range(lightshow.nb_x)
            ]
            for position in positions:
                position[2] = lightshow.takeoff_altitude
                takeoff_positions.append(position)

        elif lightshow.takeoff_mode == "standard_takeoff":
            # taking off in straight line up
            takeoff_positions = [(None, None, lightshow.takeoff_altitude)] * len(drones_to_takeoff)
        else:
            msg = f"Unknown takeoff mode: {lightshow.takeoff_mode}"
            raise ValueError(msg)

        for blender_drone, takeoff_position in zip(
            drones_to_takeoff, takeoff_positions, strict=False
        ):
            takeoff_drone(
                blender_drone,
                [frame_start_takeoff, frame_middle_takeoff, frame_end_takeoff],
                takeoff_position,
                props.takeoff_height,
                lightshow.takeoff_keyframe,
            )

        scene.frame_set(frame_end_takeoff + 2)
        if scene.frame_end < frame_end_takeoff + 2:
            scene.frame_end = frame_end_takeoff + 2

        if lightshow.takeoff_marker and len(drones_to_takeoff) >= 1:
            LIGHTSHOW_OT_takeoff._counter += 1
            scene.timeline_markers.new(
                f"Takeoff start {LIGHTSHOW_OT_takeoff._counter}", frame=frame_start_takeoff
            )
            scene.timeline_markers.new(
                f"Takeoff end {LIGHTSHOW_OT_takeoff._counter}", frame=frame_end_takeoff
            )

        return {"FINISHED"}


classes = (
    LIGHTSHOW_PT_takeoff_panel,
    LIGHTSHOW_OT_takeoff,
)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in classes:
        bpy.utils.unregister_class(cls)
