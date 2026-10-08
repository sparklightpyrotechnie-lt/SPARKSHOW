from typing import cast

import bpy
import numpy as np

from ...base import BaseOperator, BasePanelHideIfNoDrone
from ...setup import FPS, get_lightshow, get_physic_parameters
from ...tools.association_tools import get_association
from ...tools.collection_tools import (
    get_drones_last_anchor,
    get_selected_anchors,
    get_selected_drones,
)
from ...tools.takeoff_land_tools import has_drone_takeoff
from ...tools.tutorial_links_tools import draw_tutorial_button, link
from ..association_algorithm.duration_limitation.duration_limitation import (
    get_duration_limitation_second,
)
from ..association_algorithm.duration_limitation.theorical_duration_limitation import (
    get_theorical_duration_limitation_second,
)
from .utils import (
    add_arrow,
    auto_swap,
    get_direction_arrow,
    get_positions,
    get_sorted_couples,
    move_drone,
    swap_order,
    swap_target,
    transition_swap,
    unselect_last_anchor,
)


class LIGHTSHOW_PT_transition(BasePanelHideIfNoDrone):
    bl_label = "Transition"
    bl_idname = "LIGHTSHOW_PT_transition"
    bl_parent_id = "LIGHTSHOW_PT_formation"
    bl_order = 1

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        lightshow = get_lightshow(context.scene)

        drones = get_selected_drones(context)
        last_drones_targets = get_drones_last_anchor(drones)
        targets = [
            target for target in get_selected_anchors(context) if target not in last_drones_targets
        ]
        nb_drones = len(drones)
        nb_targets = len(targets)

        layout.prop(lightshow, "duration_mode", expand=True)
        if lightshow.duration_mode == "MANUAL":
            layout.prop(lightshow, "formation_duration")
        layout.prop(lightshow, "transition_mode", expand=True)
        if lightshow.transition_mode == "STAGGERED":
            layout.prop(lightshow, "staggered_frame_step")
            draw_tutorial_button(
                layout,
                context,
                lambda col: col.operator("lightshow.set_direction"),
                section=link.formation.transition.go_to_target,
                option="staggered_transition",
            )
        draw_tutorial_button(
            layout,
            context,
            lambda col: col.operator("lightshow.go_to_target"),
            section=link.formation.transition.go_to_target,
        )
        layout.label(
            text=f"Drones: {nb_drones} Targets: {nb_targets}",
            icon="CHECKMARK" if nb_drones == nb_targets > 0 else "ERROR",
        )
        draw_tutorial_button(
            layout,
            context,
            main_button_fn=lambda col: col.operator("lightshow.swap_target"),
            section=link.formation.transition.swaps,
            option="",
        )
        if lightshow.transition_mode == "STAGGERED":
            row = layout.row()
            row.operator("lightshow.swap_order")
            row.operator("lightshow.auto_swap_target")


class LIGHTSHOW_OT_set_direction(BaseOperator):
    bl_label = "Set direction"
    bl_description = """\
Set the direction of the staggered transition
The first drone to move will be the one in the direction of the arrow
The last drone to move will be the one in the opposite direction of the arrow"""
    bl_idname = "lightshow.set_direction"

    def execute(self, context: bpy.types.Context) -> set[str]:
        scene = context.scene
        arrow = get_direction_arrow(scene)
        if arrow is None:
            arrow = add_arrow(scene)
        arrow.select_set(True)

        return {"FINISHED"}


class LIGHTSHOW_OT_go_to_target(BaseOperator):
    bl_label = "Go to target"
    bl_description = """\
Make a transition from the current position of the selected drones to the selected targets (anchors)
The drones must have taken off before the transition
The number of selected drones and targets must be the same"""
    bl_idname = "lightshow.go_to_target"

    def execute(self, context: bpy.types.Context) -> set[str]:
        scene = context.scene
        lightshow = get_lightshow(scene)

        # Assign drone and target from the selected objects
        drones = get_selected_drones(context)

        if not drones:
            self.report_print({"ERROR"}, "No drone selected")
            return {"CANCELLED"}

        if not all(has_drone_takeoff(drone, scene.frame_current) for drone in drones):
            for drone in drones:
                drone.select_set(not has_drone_takeoff(drone, scene.frame_current))
            self.report_print({"ERROR"}, "Some drones have not taken off")
            return {"CANCELLED"}

        unselect_last_anchor(drones)

        targets = get_selected_anchors(context)
        if len(drones) != len(targets):
            self.report_print(
                {"ERROR"},
                f"The number of selected drones ({len(drones)}) "
                f"and targets ({len(targets)}) are different ",
            )
            return {"CANCELLED"}

        drone_positions, target_positions = get_positions(drones, targets)

        association = get_association(drone_positions, target_positions)
        sorted_target_positions = target_positions[association]

        frame_current = scene.frame_current
        physic_parameters = get_physic_parameters(lightshow)

        # The transition curve used by move_drone is the exact cubic
        # s(u)=3u^2-2u^3. For a distance D and duration T this gives:
        #   vmax = 1.5 D / T
        #   amax = 6 D / T^2
        # The theoretical duration limiter therefore matches the actual
        # Blender curve instead of merely checking the intention of the UI.
        minimum_duration = max(
            0.25,
            float(
                get_theorical_duration_limitation_second(
                    drone_positions,
                    sorted_target_positions,
                    physic_parameters,
                )
            ),
        )

        if lightshow.duration_mode == "MANUAL":
            if lightshow.formation_duration <= 0:
                self.report_print(
                    {"ERROR"},
                    "Duration must be superior to 0",
                )
                return {"CANCELLED"}

            requested_duration = float(lightshow.formation_duration)
            duration_seconds = max(requested_duration, minimum_duration)
            frame_end = frame_current + max(1, round(duration_seconds * FPS))

            if duration_seconds > requested_duration + 1e-6:
                self.report_print(
                    {"WARNING"},
                    (
                        f"Formation duration increased from {requested_duration:.2f}s "
                        f"to {duration_seconds:.2f}s to respect speed/acceleration limits"
                    ),
                )
        else:
            duration_limitation = get_duration_limitation_second(
                drone_positions,
                sorted_target_positions,
                physic_parameters,
                lightshow,
            )
            frame_end = frame_current + max(1, round(FPS * duration_limitation))
        assert frame_end > frame_current, f"Error:{frame_end=} > {frame_current=}"

        couples = [
            (drone, targets[cast(np.uint16, index)])
            for index, drone in zip(association, drones, strict=False)
        ]
        frame_step = (
            lightshow.staggered_frame_step if lightshow.transition_mode == "STAGGERED" else 0
        )

        sorted_couples = get_sorted_couples(
            scene,
            couples,
            drone_positions,
            sorted_target_positions,
            frame_step,
        )
        for index, (drone, target) in enumerate(sorted_couples):
            move_drone(
                index,
                drone,
                target,
                frame_current,
                frame_end,
                frame_step,
                lightshow.go_to_target_keyframe,
            )

        last_frame = frame_end + (len(sorted_couples) - 1) * frame_step
        scene.frame_set(last_frame + 3)
        scene.frame_end = last_frame + 3

        if lightshow.go_to_target_marker and len(drones) >= 1:
            scene.timeline_markers.new("Go to target start", frame=frame_current)
            scene.timeline_markers.new("Go to target end", frame=last_frame)

        return {"FINISHED"}


class LIGHTSHOW_OT_swap_order(BaseOperator):
    bl_label = "Swap order"
    bl_description = """\
Swap the order of the two selected drones
The swap cannot be applied on previous transitions only on the current one"""
    bl_idname = "lightshow.swap_order"

    def execute(self, context: bpy.types.Context) -> set[str]:
        return transition_swap(context, self.report_print, swap_order, "order")


class LIGHTSHOW_OT_swap_target(BaseOperator):
    bl_label = "Swap target"
    bl_description = """\
Swap the target of the two selected drones
The swap cannot be applied on previous transitions only on the current one"""
    bl_idname = "lightshow.swap_target"

    def execute(self, context: bpy.types.Context) -> set[str]:
        return transition_swap(context, self.report_print, swap_target, "target")


class LIGHTSHOW_OT_auto_swap_target(BaseOperator):
    bl_label = "Auto swap"
    bl_description = """\
Automatically swap the target on all collisions of the selected drones
This operation could need to be repeated several times to remove all collisions
The swap cannot be applied on previous transitions only on the current one"""
    bl_idname = "lightshow.auto_swap_target"

    def execute(self, context: bpy.types.Context) -> set[str]:
        return auto_swap(context, self.report_print, swap_target, "target")


classes = [
    LIGHTSHOW_PT_transition,
    LIGHTSHOW_OT_go_to_target,
    LIGHTSHOW_OT_set_direction,
    LIGHTSHOW_OT_swap_order,
    LIGHTSHOW_OT_swap_target,
    LIGHTSHOW_OT_auto_swap_target,
]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in classes:
        bpy.utils.unregister_class(cls)
