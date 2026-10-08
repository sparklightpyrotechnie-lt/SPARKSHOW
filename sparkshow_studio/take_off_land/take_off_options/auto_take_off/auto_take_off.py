from typing import TYPE_CHECKING

import bpy
import numpy as np

from ....base import BaseOperator
from ....setup import FPS, get_lightshow
from ....tools.collection_tools import get_drones
from ....tools.takeoff_land_tools import set_selected_drones_to_takeoff
from ....tools.tutorial_links_tools import draw_tutorial_button, link
from ..take_off_base import TakeOffBasePanel

if TYPE_CHECKING:
    from ....setup import Lightshow


class LIGHTSHOW_PT_auto_take_off(TakeOffBasePanel):
    bl_label = "\t\tAuto Take Off"
    bl_idname = "LIGHTSHOW_PT_auto_take_off"
    bl_parent_id = "LIGHTSHOW_PT_take_off_panel"
    bl_options = {"HIDE_HEADER"}

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        draw_tutorial_button(
            layout,
            context,
            main_button_fn=None,
            section=link.takeoff_and_land,
            option="auto_takeoff",
            text="Help with Auto Takeoff",
        )

        layout.operator("lightshow.auto_take_off", icon="PLAY")


class LIGHTSHOW_OT_auto_take_off(BaseOperator):
    bl_label = "Auto takeoff"
    bl_description = """Automatically take off all drones (selected or not).
If there is several drones in a family, each drone will take off at a different time.
Each wave of takeoff will be separated by 100 frames to avoid collisions, and height will be decreased by 2 meters for each layer.
Maximum altitude is 2 meters * number of drones per family"""
    bl_idname = "lightshow.auto_take_off"

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.frames_between_launches = 100
        self.height_between_layers = 2.0
        self.start_frame = 1  # minimum value

    @staticmethod
    def _smoothstep(t: float) -> float:
        t = max(0.0, min(1.0, float(t)))
        return t * t * (3.0 - 2.0 * t)

    @classmethod
    def _time_to_clear_vertical_distance(cls, distance: float, takeoff_height: float, first_phase_seconds: float, second_phase_seconds: float, final_altitude: float) -> float:
        """Return a conservative time until a takeoff trajectory is at least
        ``distance`` metres above its launch point.  This mirrors the actual
        takeoff curve generated in takeoff_drone(), which uses smoothstep on
        the two vertical segments.
        """
        target = max(0.0, float(distance))
        h0 = max(0.0, float(takeoff_height))
        h1 = max(h0, float(final_altitude))
        t1 = max(0.0, float(first_phase_seconds))
        t2 = max(0.0, float(second_phase_seconds))

        if target <= 0.0:
            return 0.0

        if t1 > 0.0 and target <= h0:
            if h0 <= 1e-9:
                return 0.0
            lo, hi = 0.0, 1.0
            for _ in range(32):
                mid = (lo + hi) * 0.5
                if h0 * cls._smoothstep(mid) < target:
                    lo = mid
                else:
                    hi = mid
            return hi * t1

        remaining = target - h0
        travel = h1 - h0
        if t2 <= 0.0 or travel <= 1e-9:
            return t1
        ratio = max(0.0, min(1.0, remaining / travel))
        lo, hi = 0.0, 1.0
        for _ in range(32):
            mid = (lo + hi) * 0.5
            if cls._smoothstep(mid) < ratio:
                lo = mid
            else:
                hi = mid
        return t1 + hi * t2

    def calculate_delay(self, lightshow: "Lightshow") -> int:
        # Consecutive drones of the same family start from nearby/identical
        # launch positions.  The next drone must not enter the launch volume
        # until the previous drone has actually climbed beyond the collision
        # distance.  The old formula estimated this from acceleration only and
        # could launch the next drone while the first one was still too close.
        takeoff_props = getattr(bpy.context.scene, "takeoff_props", None)
        takeoff_height = getattr(takeoff_props, "takeoff_height", 1.0) if takeoff_props else 1.0
        first_phase_seconds = getattr(takeoff_props, "takeoff_duration", 3.0) if takeoff_props else 3.0
        margin = max(0.1, float(lightshow.collision_distance) * 0.10)
        clear_distance = max(float(lightshow.collision_distance) + margin, 0.5)

        # Use the same second-phase duration model as get_takeoff_frames().
        from ..utils import get_takeoff_duration

        final_altitude = max(clear_distance + takeoff_height, float(lightshow.takeoff_altitude))
        second_phase_seconds = get_takeoff_duration(
            max(0.0, final_altitude - takeoff_height),
            a=lightshow.acc_max,
            vmax=lightshow.vel_up_max,
            transition_duration=getattr(takeoff_props, "transition_duration", 0.0) if takeoff_props else 0.0,
        )

        clear_seconds = self._time_to_clear_vertical_distance(
            clear_distance,
            takeoff_height,
            first_phase_seconds,
            second_phase_seconds,
            final_altitude,
        )

        # One extra frame avoids the new drone being spawned on the exact
        # clearance frame, which is especially important with discrete frame
        # evaluation in the collision checker.
        return max(1, int(np.ceil(clear_seconds * FPS)) + 1)

    def execute(self, context: bpy.types.Context) -> set[str]:
        lightshow = get_lightshow(context.scene)

        # set altitude to the maximum value
        takeoff_altitude = lightshow.nb_drones_per_family * self.height_between_layers
        if lightshow.takeoff_mode == "using all in one platform":
            takeoff_altitude += self.height_between_layers

        # selecting all drones
        all_drones = get_drones(context.scene.collection)
        for drone in all_drones:
            drone.select_set(True)
        self.start_frame = max(self.start_frame, context.scene.frame_current)

        frames_between_launches = self.calculate_delay(lightshow)

        for i in range(lightshow.nb_drones_per_family):
            lightshow.takeoff_altitude = takeoff_altitude - i * self.height_between_layers
            context.scene.frame_current = i * frames_between_launches + self.start_frame
            set_selected_drones_to_takeoff(all_drones)
            bpy.ops.lightshow.takeoff()  # pyright: ignore

        lightshow.takeoff_end_frame = context.scene.frame_current
        context.scene.frame_end = context.scene.frame_current

        return {"FINISHED"}


classes = (
    LIGHTSHOW_PT_auto_take_off,
    LIGHTSHOW_OT_auto_take_off,
)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in classes:
        bpy.utils.unregister_class(cls)
