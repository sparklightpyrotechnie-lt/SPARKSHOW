from typing import TYPE_CHECKING, Optional, TypeGuard, cast

import bmesh
import bpy
import numpy as np
from tqdm import tqdm

from ..setup import FPS, get_lightshow
from .collection_tools import add_anchor, add_collection, add_cube
from .color_tools import initialize_emission_material
from .drone_tools import create_drone_node_group

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from ..setup import Lightshow


def clean_scene(scene: "bpy.types.Scene") -> None:
    # Unlink and remove all objects
    for obj in list(scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    # Unlink and remove all collections
    collections = list(scene.collection.children)
    for collection in collections:
        scene.collection.children.unlink(collection)
        bpy.data.collections.remove(collection)


def refresh_scene(scene: "bpy.types.Scene") -> None:
    """Refresh the dependency graph without forcing a full frame change."""
    scene.view_layers[0].update()


def get_nb_drones_to_create(lightshow: "Lightshow") -> int:
    return lightshow.nb_x * lightshow.nb_y * lightshow.nb_drones_per_family


DRONE_FAMILY_STEP: float = 0.35
DRONE_FAMILY_STEP_5: float = 0.3
FAMILY_POSITION_MASKS: dict[int, "NDArray[np.bool_]"] = {
    1: np.array([[True]]),
    2: np.array([[True, True]]),
    3: np.array([[True, True], [True, False]]),
    4: np.array([[True, True], [True, True]]),
    5: np.array([[True, False, True], [False, True, False], [True, False, True]]),
    6: np.array([[True, True, True], [True, True, True]]),
    7: np.array([[True, True, True], [True, True, True], [False, True, False]]),
    8: np.array([[True, True, True], [True, False, True], [True, True, True]]),
    9: np.array([[True, True, True], [True, True, True], [True, True, True]]),
}


def get_grid_position(  # noqa: PLR0913
    x_index: int,
    nb_x: int,
    y_index: int,
    nb_y: int,
    step_x: float,
    step_y: float,
    angle: float,
) -> "NDArray[np.float64]":
    x = (x_index - (nb_x - 1) / 2) * step_x
    y = (y_index - (nb_y - 1) / 2) * step_y
    c = np.cos(angle)
    s = np.sin(angle)
    return np.array(
        [
            x * c - y * s,
            x * s + y * c,
            0,
        ],
    )


def create_family_grids(
    nb_drones_per_family: int,
    nb_x: int,
    nb_y: int,
    step: float,
    angle: float,
) -> list["bpy.types.Object"]:
    grids: list[bpy.types.Object] = []
    for index, wave_position in enumerate(get_family_drones_position(nb_drones_per_family, angle)):
        mesh = bpy.data.meshes.new(f"Family Grid {index:03}")
        # Create a grid of vertices
        bm = bmesh.new()
        # Add the vertices
        for position in [
            get_grid_position(x, nb_x, y, nb_y, 1, 1, 0) for y in range(nb_y) for x in range(nb_x)
        ]:
            bm.verts.new(position)  # pyright: ignore
        # Add only the horizontal and vertical neighbors.
        # The previous implementation tested every vertex pair (O(N²)).
        verts = list(bm.verts)
        for y in range(nb_y):
            row = y * nb_x
            for x in range(nb_x):
                i = row + x
                if x + 1 < nb_x:
                    bm.edges.new((verts[i], verts[i + 1]))
                if y + 1 < nb_y:
                    bm.edges.new((verts[i], verts[i + nb_x]))
        bm.to_mesh(mesh)
        bm.free()

        grid = bpy.data.objects.new(f"Family Grid {index:03}", mesh)
        grid.location = wave_position
        grid.rotation_euler[2] = angle
        grid.scale *= step
        grids.append(grid)
    return grids


def get_family_drones_position(
    nb_drones_per_family: int,
    angle: float,
) -> "NDArray[np.float64]":
    mask = FAMILY_POSITION_MASKS.get(nb_drones_per_family)
    if mask is None:
        return np.zeros((nb_drones_per_family, 3))
    nb_y, nb_x = mask.shape
    step = DRONE_FAMILY_STEP_5 if nb_drones_per_family == 5 else DRONE_FAMILY_STEP
    return np.array(
        [
            get_grid_position(x, nb_x, y, nb_y, step, step, angle)
            for y, row in enumerate(mask)
            for x, has_drone in enumerate(row)
            if has_drone
        ],
    )


def get_drones_position(
    matrix: "NDArray[np.intp]",
    step_x: float,
    step_y: float,
    angle: float = 0.0,
) -> list["NDArray[np.float64]"]:
    nb_y, nb_x = matrix.shape
    return [
        get_family_drones_position(nb_drones_per_family, angle)
        + get_grid_position(x, nb_x, y, nb_y, step_x, step_y, angle)
        for y, row in enumerate(matrix)
        for x, nb_drones_per_family in enumerate(row)
    ]


def get_drone_template() -> "bpy.types.Object":
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=8, radius=0.15)
    drone_mesh = bpy.data.meshes.new("Drone")
    bm.to_mesh(drone_mesh)
    bm.free()
    return bpy.data.objects.new("Drone", drone_mesh)


def is_space_view_3d(space: "bpy.types.Space") -> TypeGuard["bpy.types.SpaceView3D"]:
    return space.type == "VIEW_3D"


def is_space_dopesheet_editor(
    space: "bpy.types.Space",
) -> TypeGuard["bpy.types.SpaceDopeSheetEditor"]:
    return space.type == "DOPESHEET_EDITOR"


def init_scene(context: "bpy.types.Context") -> None:
    scene = context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene.unit_settings.use_separate = False
    scene.unit_settings.system_rotation = "DEGREES"
    scene.unit_settings.length_unit = "METERS"
    scene.unit_settings.mass_unit = "KILOGRAMS"
    scene.unit_settings.time_unit = "SECONDS"
    scene.unit_settings.temperature_unit = "KELVIN"

    scene.render.fps = FPS
    scene.render.fps_base = 1.0
    if bpy.app.version >= (4, 2, 2):
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    else:
        scene.render.engine = "BLENDER_EEVEE"  # pyright: ignore
        scene.eevee.use_bloom = True
        scene.eevee.bloom_radius = 0.4
        scene.eevee.bloom_intensity = 0.2

    for area in bpy.data.screens["Layout"].areas:
        for space in area.spaces:
            if is_space_view_3d(space):
                space.shading.type = "MATERIAL"
            if is_space_dopesheet_editor(space):
                space.show_seconds = True

    context.preferences.themes[0].dopesheet_editor.keyframe_movehold_selected = (1, 0, 0)

    scene.frame_start = 1
    scene.frame_set(scene.frame_start)

    add_collection("System", bpy.context.scene.collection, "COLOR_01")


def init_drone(  # noqa: PLR0913
    name: str,
    collection: "bpy.types.Collection",
    current_frame: int,
    lightshow: "Lightshow",
    drone_template: "bpy.types.Object",
    location: tuple[float, float, float] = (0, 0, 0),
) -> "bpy.types.Object":
    drone = cast("bpy.types.Object", drone_template.copy())
    drone.name = name
    assert drone_template.data is not None
    # All drones share the same immutable display mesh. Per-drone color and
    # animation live on the Object, so sharing geometry is safe.
    drone.data = drone_template.data
    drone.location = location
    drone["sparkshow_object_color"] = True
    drone.lock_rotation = (True, True, True)
    drone.lock_scale = (True, True, True)

    # Initialize drone materials
    initialize_emission_material(
        drone,
        current_frame,
        lightshow,
    )

    # Initialize drone fire
    drone["fire"] = [0] * 3
    for i in range(3):
        drone[f"fire_vdl{i}"] = ""

    if not np.isclose(lightshow.angle_export, 0):
        create_drone_node_group(drone)

    collection.objects.link(drone)
    return drone


def init_show(scene: "bpy.types.Scene", matrix: "NDArray[np.intp]") -> list["bpy.types.Object"]:
    lightshow = get_lightshow(scene)

    positions = get_drones_position(
        matrix, lightshow.step_x, lightshow.step_y, lightshow.angle_takeoff
    )
    drones: list[bpy.types.Object] = []
    drone_object_template = get_drone_template()
    families_collection = add_collection("Families", scene.collection)

    for family_id, family_positions in tqdm(
        enumerate(positions),
        desc="Initializing the show",
        total=len(positions),
        unit="family",
    ):
        # Initialize the family
        family_collection = add_collection(
            f"Family {family_id:03}", families_collection, "COLOR_05"
        )

        # Generate the drones of the family
        for drone_id, drone_position in enumerate(family_positions):
            drone_name = f"Drone {family_id:03}.{drone_id:03}"
            drone = init_drone(
                drone_name,
                family_collection,
                scene.frame_current,
                lightshow,
                drone_object_template,
                drone_position,
            )
            drones.append(drone)

    # The template is only a construction helper. Keep its mesh datablock (it
    # is shared by all drones) but remove the unlinked template object.
    bpy.data.objects.remove(drone_object_template, do_unlink=True)

    # Set the angle export to 0. Geometry Nodes is added lazily only when the
    # export angle is actually used.
    lightshow.angle_export = 0

    return drones


def init_show_range(scene: "bpy.types.Scene", nb_drones: int) -> list["bpy.types.Object"]:
    lightshow = get_lightshow(scene)
    drone_object_template = get_drone_template()
    import_collection = add_collection("Import", scene.collection)
    import_origin = add_cube("Import Origin", import_collection)

    drones: list[bpy.types.Object] = []
    for drone_id in range(nb_drones):
        drone_name = f"Import Drone {drone_id:03}"
        drone = init_drone(
            drone_name,
            import_collection,
            scene.frame_current,
            lightshow,
            drone_object_template,
        )
        drone.parent = import_origin
        anchor = add_anchor(drone, import_collection)
        anchor.parent = drone
        drones.append(drone)

    return drones


def create_object_at_position(
    position: tuple[float, float, float], collection: Optional["bpy.types.Collection"] = None
) -> "bpy.types.Object":
    # Create a new mesh object
    mesh = bpy.data.meshes.new(name="TargetMesh")
    obj = bpy.data.objects.new(name="TargetObject", object_data=mesh)

    (collection or bpy.context.collection).objects.link(obj)

    # Set the location of the object
    obj.location = position

    return obj
