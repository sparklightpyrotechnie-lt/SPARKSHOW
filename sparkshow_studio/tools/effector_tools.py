from typing import TYPE_CHECKING, Any, cast

import bpy
import numpy as np
from mathutils import Vector

from ..setup import get_lightshow
from .collection_tools import get_drone_index_in_family, get_family_index, get_visible_drones
from .color_tools import get_active_material_color, set_active_material_color
from .geometry_tools import distance_from_mesh, is_drone_inside_mesh

if TYPE_CHECKING:
    from setup import EffectorType

EFFECTOR_FORMAT = {
    "FIXED": ["priority"],
    "RANDOM": ["frame_rate", "priority"],
    "FADED": ["intensity", "priority"],
}


def parse_effector_name(
    name: str,
    effector_format: dict[str, list[str]],
    nb_color: int,
) -> dict[str, Any]:
    name_list = name.split("_")
    effector_dict: dict[str, Any] = {"type": name_list[1]}
    for cpt, key in enumerate(effector_format[name_list[1]]):
        effector_dict[key] = name_list[cpt + 2]
    if effector_dict["type"] == "RANDOM":
        rng = np.random.default_rng(1)
        effector_dict["LED_order"] = rng.integers(0, nb_color, 10 * nb_color)
    return effector_dict


def fixed_effector_color(mesh: bpy.types.Object, drone: bpy.types.Object) -> Vector | None:
    if not is_drone_inside_mesh(mesh, drone):
        return None
    return Vector(get_active_material_color(mesh))


def random_effector_color(
    mesh: bpy.types.Object,
    drone: bpy.types.Object,
    effector_dict: dict[str, Any],
    scene: bpy.types.Scene,
) -> Vector | None:
    if not is_drone_inside_mesh(mesh, drone):
        return None

    rng = np.random.default_rng(100 * get_family_index(drone) + get_drone_index_in_family(drone))
    drone_delay = rng.integers(0, len(effector_dict["LED_order"]) - 1)
    frame_rate = effector_dict["frame_rate"].split(".")[0]
    frame_delay = scene.frame_current // int(frame_rate)
    return Vector(
        get_active_material_color(
            mesh,
            effector_dict["LED_order"][
                (drone_delay + frame_delay) % len(effector_dict["LED_order"])
            ],
        ),
    )


def faded_effector_color(
    mesh: bpy.types.Object,
    drone: bpy.types.Object,
    effector_dict: dict[str, Any],
) -> Vector:
    if is_drone_inside_mesh(mesh, drone):
        return Vector(get_active_material_color(mesh))

    distance = distance_from_mesh(mesh, drone)
    ratio = np.power(
        1 / (1 + distance),
        1 / (float(effector_dict["intensity"]) + 1e-3),
    )
    new_color = Vector(get_active_material_color(mesh)) * ratio
    previous_color = Vector(get_active_material_color(drone)) * (1 - ratio)
    return new_color + previous_color


def make_mesh_scale_positive(mesh: bpy.types.Object) -> None:
    mesh.scale.x = abs(mesh.scale.x)
    mesh.scale.y = abs(mesh.scale.y)
    mesh.scale.z = abs(mesh.scale.z)


def is_effector_name_valid(effector_name: str) -> bool:
    effector_name_split = effector_name.split("_")
    if len(effector_name_split) <= 1:
        return False
    effector_type = effector_name.split("_")[1]
    try:
        if effector_type == "FIXED":
            if len(effector_name_split) != 3:
                return False
            float(effector_name_split[2])
        elif effector_type in {"RANDOM", "FADED"}:
            if len(effector_name_split) != 4:
                return False
            float(effector_name_split[2])
            float(effector_name_split[3])
        else:
            return False
    except ValueError:
        return False
    return True


def change_effector(
    name: str,
    effector_type: "EffectorType",
    effector_intensity: float,
    effector_frame_rate: int,
    effector_priority: float,
) -> None:
    mesh = bpy.data.collections["Effector"].objects[name]
    mesh_name = name.split("_")[0]
    data_dict = {
        "type": effector_type,
        "intensity": effector_intensity,
        "frame_rate": effector_frame_rate,
        "priority": effector_priority,
    }
    mesh_name += f"_{effector_type}"
    for key in EFFECTOR_FORMAT[effector_type]:
        mesh_name += f"_{data_dict[key]:.2f}"
    mesh.name = mesh_name


def update_effector_handler(scene: bpy.types.Scene) -> None:  # noqa: C901
    lightshow = get_lightshow(scene)
    if (
        not (scene.frame_start <= scene.frame_current <= scene.frame_end)
        or lightshow.disable_magic_color
    ):
        return

    effector_collection = scene.collection.children.get("Effector")
    if effector_collection is None:
        return

    visible_drones = get_visible_drones(scene.collection)

    drone_color_list: list[dict[str, Any]] = [
        {"color_sum": Vector((0, 0, 0, 0)), "priority_sum": 0} for _ in range(len(visible_drones))
    ]
    for name in (
        effector_name
        for effector_name in (obj.name for obj in effector_collection.objects)
        if is_effector_name_valid(effector_name)
    ):
        mesh = bpy.data.collections["Effector"].objects[name]
        materials = cast(bpy.types.Mesh, mesh.data).materials
        make_mesh_scale_positive(mesh)
        effector_dict = parse_effector_name(
            name,
            EFFECTOR_FORMAT,
            len(materials),
        )
        if len(materials) > 0:
            for cpt, drone in enumerate(visible_drones):
                if effector_dict["type"] == "FIXED":
                    new_color = fixed_effector_color(mesh, drone)
                elif effector_dict["type"] == "RANDOM":
                    new_color = random_effector_color(
                        mesh,
                        drone,
                        effector_dict,
                        scene,
                    )
                elif effector_dict["type"] == "FADED":
                    new_color = faded_effector_color(
                        mesh,
                        drone,
                        effector_dict,
                    )
                else:
                    new_color = None

                if new_color is not None:
                    drone_color_list[cpt]["color_sum"] += (
                        float(effector_dict["priority"]) * new_color
                    )
                    drone_color_list[cpt]["priority_sum"] += float(
                        effector_dict["priority"],
                    )

    for cpt, drone in enumerate(visible_drones):
        if drone_color_list[cpt]["priority_sum"] != 0:
            set_active_material_color(
                drone,
                drone_color_list[cpt]["color_sum"] / drone_color_list[cpt]["priority_sum"],
            )


def register_update_effector_handler() -> None:
    for handler in bpy.app.handlers.frame_change_post:
        if handler.__name__ == "update_effector_handler" and handler != update_effector_handler:
            bpy.app.handlers.frame_change_post.remove(handler)
    if update_effector_handler not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(update_effector_handler)
