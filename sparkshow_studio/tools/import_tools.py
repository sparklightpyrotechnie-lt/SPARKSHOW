import json
from typing import TYPE_CHECKING

import bpy
import numpy as np

from sparkshow_studio._loader.parameters import LAND_PARAMETERS, TAKEOFF_PARAMETERS
from sparkshow_studio._loader.schemas import ColorEventUser, FireEventUser, PositionEventUser, YawEventUser

from ..setup import FPS
from .fcurve_tools import RGBW_EMISSION_MATERIAL_DATA_PATH, find_fcurve_or_create

if TYPE_CHECKING:
    from ..setup import Lightshow


def add_takeoff_land_intermediate_position(
    position_user_events: list[PositionEventUser], rtl_start_frame: int | None
) -> None:
    # Restore the end of the RTL repositioning
    if rtl_start_frame is not None:
        last_position_event = position_user_events[-1]
        last_position_event.frame = (
            last_position_event.frame + LAND_PARAMETERS.get_rtl_reposition_frame_delta()
        )
    first_frame = position_user_events[0].frame
    first_position = position_user_events[0].xyz
    last_frame = position_user_events[-1].frame
    last_position = position_user_events[-1].xyz
    position_user_events.insert(
        1,
        PositionEventUser(
            frame=first_frame + int(FPS * TAKEOFF_PARAMETERS.takeoff_elevation_duration_second),
            xyz=(
                *first_position[:2],
                first_position[2] + TAKEOFF_PARAMETERS.takeoff_altitude_meter_min,
            ),
        ),
    )
    position_user_events.append(
        PositionEventUser(
            frame=last_frame
            + int(FPS * LAND_PARAMETERS.get_first_land_second_delta(last_position[2])),
            xyz=(*last_position[:2], LAND_PARAMETERS.get_first_land_altitude(last_position[2])),
        ),
    )
    position_user_events.append(
        PositionEventUser(
            frame=last_frame
            + int(FPS * LAND_PARAMETERS.get_land_second_delta(last_position[2]))
            + 1,
            xyz=(*last_position[:2], 0.0),
        ),
    )


def add_position_events_import(
    blender_drone: "bpy.types.Object",
    position_user_events: list["PositionEventUser"],
    rtl_start_frame: int | None,
    is_range_import: bool,
    frame_offset: int,
) -> None:
    if not is_range_import:
        add_takeoff_land_intermediate_position(position_user_events, rtl_start_frame)

    if blender_drone.animation_data is None:
        blender_drone.animation_data_create()
    if blender_drone.animation_data.action is None:
        blender_drone.animation_data.action = bpy.data.actions.new(
            name=f"{blender_drone.name}_Action"
        )

    for position_user_event in position_user_events:
        frame = position_user_event.frame + frame_offset
        blender_drone.location = position_user_event.xyz
        blender_drone.keyframe_insert(data_path="location", index=-1, frame=frame)


def apply_colors_to_material(
    blender_drone: "bpy.types.Object",
    color_events: list[ColorEventUser],
    frame_offset: int,
    lightshow: "Lightshow",
) -> None:
    if blender_drone.name.startswith("Drone "):
        rgbw_fcurves: list[bpy.types.FCurve] = [
            find_fcurve_or_create(blender_drone, "color", color_index)
            for color_index in range(4)
        ]
    else:
        assert blender_drone.active_material is not None
        rgbw_fcurves = [
            find_fcurve_or_create(
                blender_drone.active_material.node_tree,  # pyright: ignore
                RGBW_EMISSION_MATERIAL_DATA_PATH,
                color_index,
            )
            for color_index in range(4)
        ]

    for fcurve_index, fcurve in enumerate(rgbw_fcurves):
        fcurve.keyframe_points.add(len(color_events) - len(fcurve.keyframe_points))
        for color_index, color_event in enumerate(color_events):
            keyframe_point = fcurve.keyframe_points[color_index]
            keyframe_point.co = (
                color_event.frame + frame_offset,
                color_event.rgbw[fcurve_index],
            )
            keyframe_point.interpolation = "LINEAR" if color_event.interpolate else "CONSTANT"
            keyframe_point.type = lightshow.set_color_keyframe


def add_color_events_import(  # noqa: PLR0913
    blender_drone: "bpy.types.Object",
    color_user_events: list[ColorEventUser],
    last_position_frame: int,
    is_range_import: bool,
    frame_offset: int,
    lightshow: "Lightshow",
) -> None:
    if not color_user_events:
        return

    # Remove color events after last position frame and add a black color event
    color_user_events = [
        color_user_event
        for color_user_event in color_user_events
        if color_user_event.frame <= last_position_frame
    ]

    if not is_range_import:
        if color_user_events[0].frame != 0:
            color_user_events.insert(0, ColorEventUser(frame=0, rgbw=(0.0, 0.0, 0.0, 0.0)))
        elif color_user_events[0].rgbw != (0.0, 0.0, 0.0, 0.0):
            if len(color_user_events) > 1 and color_user_events[1].frame < 4:
                color_user_events[0].rgbw = (0.0, 0.0, 0.0, 0.0)
            else:
                color_user_events[0].frame = 4  # 4 frames for the first color event
                color_user_events.insert(0, ColorEventUser(frame=0, rgbw=(0.0, 0.0, 0.0, 0.0)))
        color_user_events[-1].interpolate = False
        if color_user_events[-1].rgbw != (0.0, 0.0, 0.0, 0.0):
            color_user_events.append(
                ColorEventUser(frame=last_position_frame + 1, rgbw=(0.0, 0.0, 0.0, 0.0)),
            )

    apply_colors_to_material(blender_drone, color_user_events, frame_offset, lightshow)


def _get_fire_preview_position(blender_drone: "bpy.types.Object", frame: int) -> tuple[float, float, float] | None:
    """Evaluate location F-curves at an imported fire frame without changing the scene frame."""
    action = blender_drone.animation_data.action if blender_drone.animation_data else None
    if action is None:
        t = blender_drone.matrix_world.translation
        return (float(t.x), float(t.y), float(t.z))
    values = []
    for index in range(3):
        fcurve = action.fcurves.find("location", index=index)
        if fcurve is None:
            return None
        values.append(float(fcurve.evaluate(frame)))
    return (values[0], values[1], values[2])


def add_fire_events_import(
    blender_drone: "bpy.types.Object",
    fire_events: list[FireEventUser],
    frame_offset: int,
    lightshow: "Lightshow",
) -> None:
    fire_fcurves: list[bpy.types.FCurve] = []
    assert blender_drone.animation_data.action is not None
    for i in range(3):
        fcurve = blender_drone.animation_data.action.fcurves.new(
            data_path='["fire"]',
            index=i,
        )

        fcurve.keyframe_points.add(
            sum(1 for fire_event in fire_events if fire_event.channel == i),
        )
        fire_fcurves.append(fcurve)

    kp_indexes = [0] * 3
    for fire_event in fire_events:
        index = kp_indexes[fire_event.channel]
        fire_fcurves[fire_event.channel].keyframe_points[index].co = (
            fire_event.frame + frame_offset,
            fire_event.duration,
        )
        fire_fcurves[fire_event.channel].keyframe_points[index].type = lightshow.fire_keyframe

        kp_indexes[fire_event.channel] += 1

        # Add VDL information
        blender_drone[f"fire_vdl{fire_event.channel}"] = fire_event.vdl

        # Store the real imported event position for the non-exported viewport/synoptic preview.
        try:
            from ..fire.preview import record_event_position
            event_frame = fire_event.frame + frame_offset
            position = _get_fire_preview_position(blender_drone, event_frame)
            record_event_position(blender_drone, fire_event.channel, event_frame, position=position)
        except (ImportError, RuntimeError):
            pass


def add_yaw_events_import(
    blender_drone: "bpy.types.Object",
    yaw_user_events: list[YawEventUser],
    frame_offset: int,
) -> None:
    blender_drone.rotation_mode = "XYZ"
    assert blender_drone.animation_data.action is not None
    fcurve = blender_drone.animation_data.action.fcurves.new(
        data_path="rotation_euler",
        index=2,
    )
    fcurve.keyframe_points.add(len(yaw_user_events))

    for event_index, yaw_user_event in enumerate(yaw_user_events):
        fcurve.keyframe_points[event_index].co = (
            yaw_user_event.frame + frame_offset,
            np.deg2rad(yaw_user_event.angle),
        )

    for keyframe_point in fcurve.keyframe_points:
        keyframe_point.interpolation = "LINEAR"


def convert_step_to_step_x_and_step_y(json_str: str) -> str:
    data = json.loads(json_str)
    if "step" in data:  # import range case
        value: float = data.pop("step")
        data["step_x"] = value
        data["step_y"] = value

    if "show" in data and "step" in data["show"]:  # global import case
        value: float = data["show"].pop("step")
        data["show"]["step_x"] = value
        data["show"]["step_y"] = value

    return json.dumps(data, indent=4)
