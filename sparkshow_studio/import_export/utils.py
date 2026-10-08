from collections.abc import Sized
from datetime import datetime, timezone
from pathlib import Path

import bpy
from tqdm import tqdm

from sparkshow_studio._loader.parameters import LandType, MagicNumber
from sparkshow_studio._loader.reports import GlobalReport
from sparkshow_studio._loader.schemas import ShowUser

from ..setup import get_lightshow, get_metadata, get_physic_parameters, set_physic_parameters
from ..tools.collection_tools import get_drone_index_from_blender_drone
from ..tools.export_tools import update_show_user_export
from ..tools.import_tools import (
    add_color_events_import,
    add_fire_events_import,
    add_position_events_import,
    add_yaw_events_import,
)
from ..tools.scene_tools import init_scene, init_show, init_show_range
from ..tools.takeoff_land_tools import get_drone_infos


def add_date_to_path(filepath: Path) -> Path:
    date = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    return filepath.with_stem(f"{filepath.stem}_{date}")


def import_show_user(
    show_user: ShowUser,
    context: bpy.types.Context,
    *,
    is_range_import: bool,
) -> None:
    scene = context.scene
    lightshow = get_lightshow(scene)
    if is_range_import:
        blender_drones = init_show_range(scene, show_user.nb_drones)
        frame_offset = scene.frame_current

        import_frame_end = scene.frame_current + max(
            max(
                drone.position_events[-1].frame if len(drone.position_events) else 0,
                drone.color_events[-1].frame if len(drone.color_events) else 0,
                drone.fire_events[-1].frame if len(drone.fire_events) else 0,
            )
            for drone in show_user.drones_user
        )

        scene.timeline_markers.new("Import start", frame=scene.frame_current)
        scene.timeline_markers.new("Import end", frame=import_frame_end)
    else:
        lightshow.nb_drones = show_user.nb_drones
        lightshow.nb_drones_per_family = show_user.nb_drones_per_family
        lightshow.old_nb_x = lightshow.nb_x = show_user.nb_x
        lightshow.old_nb_y = lightshow.nb_y = show_user.nb_y
        lightshow.angle_takeoff = show_user.angle_takeoff
        lightshow.step_x = show_user.step_x
        lightshow.step_y = show_user.step_y
        lightshow.scale_export = show_user.scale
        lightshow.rtl_start_frame = (
            show_user.rtl_start_frame if show_user.rtl_start_frame is not None else -1
        )
        lightshow.takeoff_end_frame = (
            show_user.takeoff_end_frame if show_user.takeoff_end_frame is not None else -1
        )
        lightshow.takeoff_mode = (
            "standard_takeoff"
            if lightshow.step_x == lightshow.step_y
            else "using all in one platform"
        )
        set_physic_parameters(lightshow, show_user.physic_parameters)
        init_scene(context)
        blender_drones = init_show(scene, show_user.matrix)
        frame_offset = 0

    for blender_drone, user_drone in tqdm(
        zip(blender_drones, show_user.drones_user, strict=False),
        total=len(blender_drones),
        desc="Loading drones events",
        unit="drone",
    ):
        blender_drone.animation_data_create()
        blender_drone.animation_data.action = bpy.data.actions.new(
            name=blender_drone.name + "Action",
        )
        last_position_frame = user_drone.position_events[-1].frame
        add_position_events_import(
            blender_drone,
            user_drone.position_events,
            show_user.rtl_start_frame,
            is_range_import,
            frame_offset,
        )
        add_color_events_import(
            blender_drone,
            user_drone.color_events,
            last_position_frame,
            is_range_import,
            frame_offset,
            lightshow,
        )
        add_fire_events_import(blender_drone, user_drone.fire_events, frame_offset, lightshow)
        add_yaw_events_import(blender_drone, user_drone.yaw_events, frame_offset)

    try:
        from ..fire.preview import refresh_preview
        refresh_preview(scene)
    except (ImportError, RuntimeError):
        pass


def get_show_user(
    blender_drones: list[bpy.types.Object],
    scene: bpy.types.Scene,
    use_scene_range: bool,
    with_yaw: bool = False,
) -> ShowUser:
    lightshow = get_lightshow(scene)
    show_user = ShowUser.create(
        nb_drones=len(blender_drones),
        angle_takeoff=lightshow.angle_takeoff,
        step_x=lightshow.step_x,
        step_y=lightshow.step_y,
        metadata=get_metadata(),
    )
    show_user.rtl_start_frame = (
        lightshow.rtl_start_frame if lightshow.rtl_start_frame != -1 else None
    )
    show_user.takeoff_end_frame = (
        lightshow.takeoff_end_frame if lightshow.takeoff_end_frame != -1 else None
    )
    show_user.physic_parameters = get_physic_parameters(lightshow)
    if lightshow.magic_number == "V2":
        show_user.magic_number = MagicNumber.v3

        show_user.land_type = LandType.RTL if lightshow.rtl_start_frame != -1 else LandType.Land

        show_user.scale = lightshow.scale_export
    elif lightshow.magic_number == "V1":
        show_user.magic_number = MagicNumber.v2

    show_user.update_drones_user_indices(
        [
            get_drone_index_from_blender_drone(blender_drone, scene.collection)
            for blender_drone in blender_drones
        ],
    )
    drone_infos = get_drone_infos(
        blender_drones,
        show_user,
        scene.frame_end,
        first_frame=scene.frame_start if use_scene_range else None,
    )
    update_show_user_export(
        drone_infos,
        scene,
        frame_offset=scene.frame_start if use_scene_range else 0,
        with_yaw=with_yaw,
    )
    return show_user


def check_show_user(
    show_user: ShowUser,
    filepath: Path,
    *,
    is_partial: bool = False,
    is_import: bool = False,
) -> str | None:
    """Check if the show_user is valid and return a message and create a report file if not."""
    global_report = GlobalReport.generate(
        show_user,
        without_takeoff_format=is_partial,
        is_partial=is_partial,
        is_import=is_import,
    )
    # Ignore acceleration during RTL
    # It uses linear interpolation and the acceleration is not relevant
    report_summary = global_report.summarize()

    if len(report_summary):
        report_path = filepath.with_name(filepath.stem + "_report.json")
        report_path.write_text(report_summary.model_dump_json(indent=4))

        report_summary_string = "".join(
            [
                f"{report_name}: {len(summary) if isinstance(summary, Sized) else 0} errors \n"
                for report_name, summary in report_summary.__dict__.items()
            ],
        )
        return (
            f"The dance did not pass the loader validation:\n{report_summary_string}\n"
            f"These parameters were used to check the dance:\n{show_user.physic_parameters}\n"
            f"Report saved at {report_path}"
        )

    return None
