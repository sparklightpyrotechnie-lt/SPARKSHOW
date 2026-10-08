import bpy
import numpy as np
from bpy.app.handlers import persistent
from mathutils import Vector
from tqdm import tqdm

from ...setup import get_lightshow
from ...tools.collection_tools import get_drones
from ...tools.tutorial_links_tools import draw_tutorial_button, link
from ..check import BaseOperator, CheckBase, CheckBasePanel
from ..check_algorithm import apply_performance_check

global_speed_data = {}


class LIGHTSHOW_OT_check_speed_profiles(CheckBase):
    bl_label = "Check speed profile"
    bl_description = """\
Check if the selected drones respect the speed profile in the frame range of the scene"""
    bl_idname = "lightshow.check_speed_profiles"

    def execute(self, context: bpy.types.Context) -> set[str]:
        scene = context.scene

        frame_start, frame_end = scene.frame_start, scene.frame_end

        drones = self.get_taken_off_drones(context, 1)
        if not drones:
            return {"CANCELLED"}

        check_result = apply_performance_check(
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
            "The speed check has successfully passed",
        )
        return {"FINISHED"}


class LIGHTSHOW_PT_speed_accel(CheckBasePanel):
    bl_label = "Speed & Acceleration"
    bl_idname = "LIGHTSHOW_PT_speed_accel"
    bl_parent_id = "LIGHTSHOW_PT_check_group"
    bl_options = {"HIDE_HEADER"}

    def draw(self, context: bpy.types.Context) -> None:
        scene = context.scene
        props = getattr(context.scene, "check_props", None)
        if props is None:
            self.layout.label(text="Check Properties not found", icon="ERROR")
            return

        lightshow = get_lightshow(context.scene)
        layout = self.layout

        draw_tutorial_button(
            layout,
            context,
            lambda col: col.prop(props, "display_drone_movements"),
            section=link.check.speed_and_acceleration,
        )

        layout.use_property_split = True
        layout.use_property_decorate = False

        if props.display_drone_movements:
            layout.operator("lightshow.bake_simulations", text="Bake Simulations")
            if not global_speed_data or not global_speed_data.get("speeds"):
                layout.label(text="Bake simulations to display grid", icon="ERROR")
            else:
                layout.label(
                    text=f"{props.nb_errors} speed&accel errors detected",
                    icon="ERROR" if props.nb_errors else "CHECKMARK",
                )
                layout.prop(props, "sort_by")
                selected_objects = bpy.context.selected_objects
                drone_data = []
                eval_frame = min(
                    max(scene.frame_start, scene.frame_current), scene.frame_end - 1
                )  # Ensure frame is within bounds
                for drone in get_drones(context.scene.collection):
                    speed_xy = (
                        global_speed_data["speeds"]
                        .get(drone.name, {})
                        .get(eval_frame, {})
                        .get("xy", 0)
                    )
                    speed_z = (
                        global_speed_data["speeds"]
                        .get(drone.name, {})
                        .get(eval_frame, {})
                        .get("z", 0)
                    )
                    accel = (
                        global_speed_data["accelerations"].get(drone.name, {}).get(eval_frame, 0)
                    )

                    if (
                        abs(speed_xy) > lightshow.vel_hor_max
                        or abs(speed_z) > lightshow.vel_up_max
                        or abs(speed_z) > lightshow.vel_down_max
                        or abs(accel) > lightshow.acc_max
                        or drone in selected_objects
                    ):
                        drone.select_set(True)
                        drone_data.append(
                            {
                                "name": drone.name,
                                "speed_xy": speed_xy,
                                "speed_z": speed_z,
                                "acceleration": accel,
                                "distance": global_speed_data["distances"]
                                .get(drone.name, {})
                                .get(eval_frame, -1),
                            }
                        )

                if drone_data:
                    box = layout.box()
                    header = box.row()
                    header.label(text="Drone")
                    header.label(text="Speed XY (m/s)")
                    header.label(text="Speed Z (m/s)")
                    header.label(text="Acceleration (m/s²)")
                    header.label(text="Distance (m)")

                    drone_data.sort(
                        key=lambda data: data[props.sort_by], reverse=props.sort_by != "name"
                    )

                    for data in drone_data:
                        row = box.row()
                        row.label(text=data["name"])
                        row.label(
                            text=f"{data['speed_xy']:.2f}",
                            icon="ERROR"
                            if abs(data["speed_xy"]) > lightshow.vel_hor_max
                            else "NONE",
                        )
                        row.label(
                            text=f"{data['speed_z']:.2f}",
                            icon="ERROR"
                            if abs(data["speed_z"]) > lightshow.vel_up_max
                            or abs(data["speed_z"]) > lightshow.vel_down_max
                            else "NONE",
                        )
                        row.label(
                            text=f"{data['acceleration']:.2f}",
                            icon="ERROR"
                            if abs(data["acceleration"]) > lightshow.acc_max
                            else "NONE",
                        )
                        row.label(text=f"{data['distance']:.2f}")

        layout.prop(lightshow, "vel_hor_max")
        layout.prop(lightshow, "vel_up_max")
        layout.prop(lightshow, "vel_down_max")
        layout.prop(lightshow, "acc_max")
        layout.operator("lightshow.check_speed_profiles")


def compute_speeds_and_distances(
    frame_range: tuple[int, int],
    delta_time: float,
    drones: list[bpy.types.Object],
    positions: dict[str, dict[int, Vector]],
    speed_limits: tuple[float, float, float],
) -> tuple[dict[str, dict[int, dict[str, float]]], dict[str, dict[int, float]], int | None, int]:
    start_frame, end_frame = frame_range
    vel_hor_max, vel_up_max, vel_down_max = speed_limits

    first_error_frame = None
    nb_errors = 0
    speeds = {drone.name: {} for drone in drones}
    distances = {drone.name: {} for drone in drones}

    # Compute speeds and distances for each frame
    for drone in drones:
        name = drone.name
        for frame in range(start_frame, end_frame):
            pos_prev = positions[name][frame]
            pos_curr = positions[name][frame + 1]
            delta_pos = pos_curr - pos_prev

            speed = delta_pos / delta_time
            speed_xy = float(np.linalg.norm(speed[0:2]))
            if abs(speed_xy) > vel_hor_max:
                drone.select_set(True)
                if first_error_frame is None:
                    first_error_frame = frame
                nb_errors += 1

            speed_z = delta_pos.z / delta_time
            if abs(speed_z) > vel_up_max or abs(speed_z) > vel_down_max:
                drone.select_set(True)
                if first_error_frame is None:
                    first_error_frame = frame
                nb_errors += 1

            speeds[name][frame] = {"xy": speed_xy, "z": speed_z, "xyz": speed}

            # Calculate distance traveled in this frame
            frame_distance = delta_pos.length
            distances[name][frame] = frame_distance + distances[name].get(frame - 1, 0)

    return speeds, distances, first_error_frame, nb_errors


def compute_acceleration(
    frame_range: tuple[int, int],
    delta_time: float,
    drones: list[bpy.types.Object],
    speeds: dict[str, dict[int, dict[str, float]]],
    acc_max: float,
) -> tuple[dict[str, dict[int, float]], int | None, int]:
    start_frame, end_frame = frame_range

    first_error_frame = None
    nb_errors = 0
    accelerations = {drone.name: {} for drone in drones}

    for drone in drones:
        name = drone.name
        for frame in range(start_frame, end_frame - 1):
            vel_curr = speeds[name][frame]["xyz"]
            vel_next = speeds[name][frame + 1]["xyz"]

            acceleration = (vel_next - vel_curr) / delta_time
            accel_value = float(np.linalg.norm(acceleration))

            if accel_value > acc_max:
                drone.select_set(True)
                if first_error_frame is None:
                    first_error_frame = frame
                nb_errors += 1

            accelerations[name][frame] = accel_value

    return accelerations, first_error_frame, nb_errors


def analyze_drone_motion(
    context: bpy.types.Context, start_frame: int, end_frame: int
) -> int | None:
    scene = context.scene
    lightshow = get_lightshow(scene)

    first_error_frame = None

    fps = scene.render.fps
    assert fps == 24, "FPS must be 24"
    delta_time = 1 / fps

    drones = get_drones(scene.collection)
    positions = {drone.name: {} for drone in drones}
    for frame in tqdm(range(start_frame, end_frame + 1), desc="Computing positions", unit="frame"):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        for drone in drones:
            pos = drone.matrix_world.translation.copy()
            positions[drone.name][frame] = pos

    props = getattr(scene, "check_props", None)
    if props is None:
        msg = "Check Properties not found in the scene"
        raise ValueError(msg)

    props.nb_errors = 0

    speeds, distances, error_frame, nb_errors = compute_speeds_and_distances(
        (start_frame, end_frame),
        delta_time,
        drones,
        positions,
        (lightshow.vel_hor_max, lightshow.vel_up_max, lightshow.vel_down_max),
    )

    props.nb_errors += nb_errors
    if first_error_frame is None or (error_frame is not None and error_frame < first_error_frame):
        first_error_frame = error_frame

    accelerations, error_frame, nb_errors = compute_acceleration(
        (start_frame, end_frame),
        delta_time,
        drones,
        speeds,
        lightshow.acc_max,
    )

    props.nb_errors += nb_errors
    if first_error_frame is None or (error_frame is not None and error_frame < first_error_frame):
        first_error_frame = error_frame

    global global_speed_data  # noqa: PLW0603
    global_speed_data = {
        "positions": positions,
        "speeds": speeds,
        "accelerations": accelerations,
        "distances": distances,
    }
    return first_error_frame


class LIGHTSHOW_OT_bake_simulations(BaseOperator):
    """Bake Geometry Nodes Simulations for All Drones in selected frame range.

    Drones that don't respect the speed profile will be selected.
    Frame will be set to the first frame with a drone not respecting the speed profile.
    """

    bl_idname = "lightshow.bake_simulations"
    bl_label = "Bake Simulations"

    def execute(self, context: bpy.types.Context) -> set[str]:
        scene = context.scene
        start_frame = scene.frame_start
        end_frame = scene.frame_end

        props = getattr(scene, "check_props", None)
        if props is None:
            self.report_print({"ERROR"}, "Check Properties not found in the scene")
            return {"CANCELLED"}

        first_error_frame = analyze_drone_motion(context, start_frame, end_frame)

        if first_error_frame is None:
            self.report_print({"INFO"}, "All drones respect the speed profile")
            return {"FINISHED"}

        scene.frame_current = first_error_frame
        self.report_print(
            {"WARNING"},
            "Simulations baked successfully. Drones not respecting the speed profile are selected.",
        )
        return {"FINISHED"}


@persistent
def update_ui_on_frame_change(scene: bpy.types.Scene) -> None:
    props = getattr(scene, "check_props", None)
    if props and props.display_drone_movements:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()


classes = [
    LIGHTSHOW_PT_speed_accel,
    LIGHTSHOW_OT_bake_simulations,
    LIGHTSHOW_OT_check_speed_profiles,
]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.app.handlers.frame_change_post.append(update_ui_on_frame_change)


def unregister() -> None:
    for cls in classes:
        bpy.utils.unregister_class(cls)
    bpy.app.handlers.frame_change_post.remove(update_ui_on_frame_change)
