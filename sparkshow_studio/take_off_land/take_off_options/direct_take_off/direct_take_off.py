import queue
import sys
import threading
import traceback
from typing import TYPE_CHECKING, Literal, cast

import bpy
import numpy as np
from numpy.array_api import float32

from ....base import BaseOperator
from ....setup import FPS, get_lightshow
from ....tools.association_tools import get_association
from ....tools.collection_tools import get_drones, get_drones_last_anchor, get_selected_anchors
from ....tools.rtl_calculator import RTLCalculator
from ....tools.takeoff_land_tools import has_drone_takeoff
from ....tools.tutorial_links_tools import draw_tutorial_button, link
from ..take_off_base import TakeOffBasePanel
from ..utils import takeoff_drone

if TYPE_CHECKING:
    from numpy.typing import NDArray


class DirectTakeoff_PT_SubPanel(TakeOffBasePanel):
    bl_label = "\t\tDirect Takeoff"
    bl_idname = "LIGHTSHOW_PT_direct_take_off"
    bl_parent_id = "LIGHTSHOW_PT_take_off_panel"
    bl_options = {"HIDE_HEADER"}

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        props = getattr(context.scene, "dtakeoff_props", None)
        assert props is not None, "Direct takeoff properties not found in the scene"

        draw_tutorial_button(
            layout,
            context,
            main_button_fn=None,
            section=link.takeoff_and_land,
            option="direct_takeoff",
            text="Help with Direct Takeoff",
        )

        if not props.is_running:
            if props.cancelled:
                nb_drones = len(get_drones(context.scene.collection))
                nb_targets = len(get_selected_anchors(context))
                layout.label(
                    text=f"Drones: {nb_drones} Targets: {nb_targets}",
                    icon="CHECKMARK" if nb_drones == nb_targets > 0 else "ERROR",
                )
                layout.operator("lightshow.direct_takeoff", icon="PLAY")
                layout.operator("lightshow.direct_takeoff_reset", icon="FILE_REFRESH")
            elif props.current_time_delta > 0:
                layout.label(text="Generation done", icon="CHECKMARK")
                layout.label(
                    text=f"Max. waiting time = {props.current_time_delta // 1440} min {props.current_time_delta % 1440 // 24} sec",
                    icon="INFO",
                )
                layout.operator("lightshow.direct_takeoff_reset", icon="FILE_REFRESH")
            else:
                nb_drones = len(get_drones(context.scene.collection))
                nb_targets = len(get_selected_anchors(context))
                layout.label(
                    text=f"Drones: {nb_drones} Targets: {nb_targets}",
                    icon="CHECKMARK" if nb_drones == nb_targets > 0 else "ERROR",
                )
                layout.operator("lightshow.direct_takeoff", icon="PLAY")
        else:
            results_box = layout.box()
            results_col = results_box.column(align=True)
            results_col.label(text="Progression", icon="INFO")
            results_col.label(
                text=f"Trajectory: {props.calculated_trajectories} / {props.nb_drones}",
                icon="SORTTIME",
            )
            results_col.label(
                text=f"Waiting time = {props.current_time_delta // 1440} min {props.current_time_delta % 1440 // 24} sec"
            )
            layout.operator("lightshow.direct_takeoff_cancel", text="Cancel", icon="X")


class LIGHTSHOW_OT_direct_takeoff(BaseOperator):
    bl_label = "Direct takeoff"
    bl_description = """Drones take off and proceed directly to their initial show positions without transitional formations.
All drones will take off, please select a number of targets (anchors) equal to the number of drones."""
    bl_idname = "lightshow.direct_takeoff"

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.frame_delta = 8
        self.min_duration = 168  # 7 seconds of transition
        self.takeoff_durations: dict[int, int] = {}
        self.waiting_times: dict[int, int] = {}

    def create_drones_movements(  # noqa: PLR0913
        self,
        drones: list[bpy.types.Object],
        target_positions: "NDArray[np.float32]",  # list[tuple[float, float, float]]
        start_frame: int,
        takeoff_height: float,
        takeoff_stabilisation_frame: int,
        takeoff_end_frames: list[int],
        keyframe_type: Literal["KEYFRAME"],
    ) -> None:
        for drone_object, target_position, takeoff_end_frame in zip(
            drones, target_positions, takeoff_end_frames, strict=True
        ):
            takeoff_drone(
                drone_object,
                [start_frame, takeoff_stabilisation_frame, int(takeoff_end_frame)],
                target_position,
                takeoff_height,
                keyframe_type,
            )

    def unselect_last_anchor(self, drones: list[bpy.types.Object]) -> None:
        for anchor in get_drones_last_anchor(drones):
            anchor.select_set(False)

    @staticmethod
    def get_positions(
        drones: list[bpy.types.Object],
        targets: list[bpy.types.Object],
    ) -> tuple["NDArray[np.float32]", "NDArray[np.float32]"]:
        drone_positions = np.array(
            [drone.matrix_world.to_translation() for drone in drones],
            dtype=np.float32,
        )
        target_positions = np.array(
            [target.matrix_world.to_translation() for target in targets],
            dtype=np.float32,
        )
        return drone_positions, target_positions

    @staticmethod
    def update_movement_with_offset(drone: bpy.types.Object, time_offset: int) -> int:
        """
        Adjust the movement constraint timing of a drone by applying a time offset.

        :param drone: The drone object with the Copy Location constraint.
        :param time_offset: The number of frames to offset the movement.
        :return: The adjusted frame time.
        """
        last_frame = -1

        if not drone.animation_data or not drone.animation_data.action:
            return last_frame

        fcurves = [
            fcurve
            for fcurve in drone.animation_data.action.fcurves
            if fcurve.data_path.startswith("location")
        ]

        if fcurves:
            for fcurve in fcurves:
                # Apply time offset to each keyframe
                for keyframe in fcurve.keyframe_points:
                    keyframe.co.x += time_offset  # Move keyframe in time
                    keyframe.handle_left.x += time_offset
                    keyframe.handle_right.x += time_offset

                    last_frame = max(last_frame, keyframe.co.x)

                # Update animation
                fcurve.update()

        return int(last_frame)

    def delay_drones_in_blender(
        self, waiting_times: dict[int, int], drones: list[bpy.types.Object]
    ) -> int:
        last_frame = -1
        for index, start_delta in waiting_times.items():
            frame = self.update_movement_with_offset(drones[index], start_delta)
            last_frame = max(last_frame, frame)

        return last_frame

    def get_positions_from_fcurve(
        self,
        drones: list[bpy.types.Object],
        start_frame: int,
        scene: bpy.types.Scene,
    ) -> dict[int, list[tuple[int, "NDArray[np.float32]"]]]:
        # Get the list of fcurves
        fcurves = {}
        for index, drone in enumerate(drones):
            for fcurve in drone.animation_data.action.fcurves:  # pyright: ignore
                if (
                    fcurve.data_path.startswith("location")
                    and fcurve.keyframe_points[0].co[0] == start_frame
                ):
                    fcurves[index] = fcurve
                    break

        # Get the list of frames to evaluate
        frames = []
        for fcurve in fcurves.values():
            frames.extend([int(keyframe_point.co[0]) for keyframe_point in fcurve.keyframe_points])

        if not frames:
            return {}
        frames_start = min(frames)
        frames_end = max(frames)

        # Get the positions of the drones movements
        drones_movements = {k: [] for k in fcurves}
        for frame in range(frames_start, frames_end + 1, self.frame_delta):
            scene.frame_set(frame)
            for index, fcurve in fcurves.items():
                drone = drones[index]

                if (
                    frame < fcurve.keyframe_points[0].co[0]
                    or frame > fcurve.keyframe_points[-1].co[0]
                ):
                    continue
                frame_delta = frame - int(fcurve.keyframe_points[0].co[0])
                drones_movements[index].append(
                    (frame_delta, drone.matrix_world.to_translation().xyz)
                )

        # convert to numpy array
        for index in drones_movements:
            numpy_trajectory = [
                (frame_delta, np.array(position, dtype=float32))
                for frame_delta, position in drones_movements[index]
            ]

            drones_movements[index] = numpy_trajectory

        return drones_movements

    def execute(self, context: bpy.types.Context) -> set[str]:  # noqa: C901, PLR0915
        scene = context.scene
        lightshow = get_lightshow(scene)
        takeoff_props = getattr(scene, "takeoff_props", None)
        if takeoff_props is None:
            self.report_print({"ERROR"}, "Takeoff properties not found in the scene")
            return {"CANCELLED"}

        scene.timeline_markers.new("Takeoff start", frame=scene.frame_current)

        drones_objects = get_drones(scene.collection)

        for drone_object in drones_objects:
            if has_drone_takeoff(drone_object):
                self.report_print(
                    {"ERROR"},
                    f"Drone {drone_object.name} has already taken off",
                )
                return {"CANCELLED"}

        targets = get_selected_anchors(context)
        if len(drones_objects) != len(targets):
            self.report_print(
                {"ERROR"},
                f"The number of selected drones ({len(drones_objects)}) "
                f"and targets ({len(targets)}) are different ",
            )
            return {"CANCELLED"}

        drone_positions, target_positions = self.get_positions(drones_objects, targets)

        association = get_association(drone_positions, target_positions)
        sorted_target_positions = target_positions[association]

        durations = np.maximum(
            (
                np.linalg.norm(sorted_target_positions - drone_positions, axis=1)
                * 1.96
                / lightshow.vel_up_max
                * FPS
            ).astype(int),
            self.min_duration,
        )

        takeoff_end_frames = scene.frame_current + takeoff_props.takeoff_duration * FPS + durations

        frame_elevation_duration = int(takeoff_props.takeoff_duration) * FPS

        self.create_drones_movements(
            drones_objects,
            sorted_target_positions,
            context.scene.frame_current,
            takeoff_props.takeoff_height,
            context.scene.frame_current + frame_elevation_duration,
            list(takeoff_end_frames),
            cast(Literal["KEYFRAME"], get_lightshow(context.scene).takeoff_keyframe),
        )

        drones_takeoffs = self.get_positions_from_fcurve(drones_objects, scene.frame_current, scene)
        if not drones_takeoffs:
            self.report_print({"ERROR"}, "Something went wrong, no takeoff found")

        self.takeoff_durations = {
            index: int(drones_takeoffs[index][-1][0] - drones_takeoffs[index][0][0])
            for index in drones_takeoffs
        }

        # reverse positions events
        reversed_drones_takeoffs = {}
        for index, drone_takeoff in drones_takeoffs.items():
            reversed_drones_takeoffs[index] = []
            for frame, position in drone_takeoff[::-1]:
                last_frame = drone_takeoff[-1][0]
                reversed_drones_takeoffs[index].append((last_frame - frame, position))

        lightshow = get_lightshow(scene)
        RTLCalculator.remove_instance()
        rtl_calculator = RTLCalculator.instance(
            reversed_drones_takeoffs,
            min_dist=lightshow.collision_distance * 1.1,  # 10% margin
            frame_delta=self.frame_delta,
        )

        props = getattr(scene, "dtakeoff_props", None)
        assert props is not None, "Direct takeoff properties not found in the scene"

        if rtl_calculator.report_message:
            self.report_print(
                {"ERROR"},
                rtl_calculator.report_message,
            )
            props.cancelled = True
            return {"CANCELLED"}

        props.cancelled = False
        props.calculated_trajectories = 0

        self._iterator = rtl_calculator.get_waiting_times()

        props.is_running = True
        self._queue = queue.Queue()
        self._buffer = []

        def run_in_thread() -> None:
            try:
                for chunk in self._iterator:
                    if props.cancelled:
                        return
                    self._queue.put(chunk)
                self._queue.put(None)
            except Exception as e:  # noqa: BLE001
                print(e, file=sys.stderr)
                traceback.print_exc()
                self._queue.put(None)

        self._thread = threading.Thread(target=run_in_thread)
        self._thread.start()

        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)

        scene.frame_current = lightshow.rtl_start_frame
        return {"RUNNING_MODAL"}

    def modal(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:  # noqa: C901
        scene = context.scene
        props = getattr(scene, "dtakeoff_props", None)
        assert props is not None, "Direct takeoff properties not found in the scene"
        drones = get_drones(scene.collection)
        rtl_calculator = RTLCalculator.instance()
        props.nb_drones = len(drones)

        if event.type == "TIMER":
            try:
                while not self._queue.empty():
                    chunk = self._queue.get()

                    if chunk is None:  # End of the iterator
                        assert self._timer is not None, "Timer is None"
                        context.window_manager.event_timer_remove(self._timer)
                        self._timer = None
                        props.is_running = False

                        max_time = max(
                            [
                                self.waiting_times[drone_idx] + self.takeoff_durations[drone_idx]
                                for drone_idx in self.waiting_times
                            ]
                        )

                        converted_waiting_times = {}
                        for drone_idx, reversed_waiting_time in self.waiting_times.items():
                            takeoff_duration = self.takeoff_durations[drone_idx]
                            converted_waiting_times[drone_idx] = max_time - (
                                reversed_waiting_time + takeoff_duration
                            )

                        if rtl_calculator.report_message:
                            self.report_print(
                                {"ERROR"},
                                rtl_calculator.report_message,
                            )
                            props.cancelled = True
                            return {"CANCELLED"}

                        last_frame = self.delay_drones_in_blender(converted_waiting_times, drones)

                        for drone in get_drones(context.scene.collection):
                            drone.select_set(True)

                        context.scene.timeline_markers.new("Takeoff end", frame=last_frame)
                        context.scene.frame_end = last_frame + 5  # add 5 frames after the end
                        context.scene.frame_current = last_frame + 5

                        props.is_running = False
                        return {"FINISHED"}

                    if not chunk:  # Still computing
                        continue

                    result = rtl_calculator.parse_chunk(chunk)
                    self.waiting_times[result["drone_idx"]] = result["waiting_time"]

                    props.calculated_trajectories += 1
                    props.current_time_delta = result["waiting_time"]
                    self.redraw(context)

            except Exception as e:  # noqa: BLE001
                print(e, file=sys.stderr)
                traceback.print_exc()
                self.report_print({"ERROR"}, f"Failed to run RTL: {e!s}")
                if self._timer is not None:
                    context.window_manager.event_timer_remove(self._timer)
                    self._timer = None
                props.is_running = False
                return {"CANCELLED"}

        if props.cancelled:
            props.is_running = False
            assert self._timer is not None, "Timer is None"
            context.window_manager.event_timer_remove(self._timer)
            self.redraw(context)
            return {"CANCELLED"}

        return {"PASS_THROUGH"}

    def redraw(self, context: bpy.types.Context) -> None:
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


class LIGHTSHOW_OT_direct_takeoff_cancel(BaseOperator):
    bl_label = "Cancel"
    bl_description = """\
Cancel the direct takeoff process"""
    bl_idname = "lightshow.direct_takeoff_cancel"

    def execute(self, context: bpy.types.Context) -> set[str]:
        props = getattr(context.scene, "dtakeoff_props", None)
        assert props is not None, "Direct takeoff properties not found in the scene"
        props.cancelled = True

        # Remove all keyframes for Copy Location constraints
        drones = get_drones(context.scene.collection)
        for drone in drones:
            if drone.animation_data and drone.animation_data.action:
                action = drone.animation_data.action

                for fcurve in action.fcurves:
                    if fcurve.data_path == "location" or fcurve.data_path.startswith(
                        'constraints["Copy Location'
                    ):
                        keyframe_points = fcurve.keyframe_points
                        keyframe_points.clear()

        if "Takeoff start" in context.scene.timeline_markers:
            context.scene.timeline_markers.remove(context.scene.timeline_markers["Takeoff start"])

        return {"FINISHED"}


class LIGHTSHOW_OT_direct_takeoff_reset(BaseOperator):
    bl_label = "Reset"
    bl_description = """\
Reset the direct takeoff process"""
    bl_idname = "lightshow.direct_takeoff_reset"

    def execute(self, context: bpy.types.Context) -> set[str]:
        props = getattr(context.scene, "dtakeoff_props", None)
        assert props is not None, "Direct takeoff properties not found in the scene"
        props.cancelled = False
        props.is_running = False
        props.calculated_trajectories = 0
        props.current_time_delta = 0

        if "Takeoff start" in context.scene.timeline_markers:
            context.scene.timeline_markers.remove(context.scene.timeline_markers["Takeoff start"])

        if "Takeoff end" in context.scene.timeline_markers:
            context.scene.timeline_markers.remove(context.scene.timeline_markers["Takeoff end"])

        context.scene.frame_set(0)
        # Remove all keyframes for Copy Location constraints
        drones = get_drones(context.scene.collection)
        for drone in drones:
            if drone.animation_data and drone.animation_data.action:
                action = drone.animation_data.action

                for fcurve in action.fcurves:
                    if fcurve.data_path == "location" or fcurve.data_path.startswith(
                        'constraints["Copy Location'
                    ):
                        keyframe_points = fcurve.keyframe_points
                        keyframe_points.clear()

        return {"FINISHED"}


classes = (
    LIGHTSHOW_OT_direct_takeoff,
    LIGHTSHOW_OT_direct_takeoff_cancel,
    LIGHTSHOW_OT_direct_takeoff_reset,
    DirectTakeoff_PT_SubPanel,
)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in classes:
        bpy.utils.unregister_class(cls)
