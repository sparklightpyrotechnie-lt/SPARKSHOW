import itertools
from collections.abc import Callable, Generator, Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, TypeVar, cast

import bpy
import numpy as np
from tqdm import tqdm

from ..setup import get_lightshow
from .fcurve_tools import (
    RGBW_EMISSION_MATERIAL_DATA_PATH,
    change_interpolation,
    change_keyframes_type,
    find_fcurve_or_create,
    find_fcurve_or_none,
    find_fcurve_or_none_from_fcurves,
    remove_range_keyframes,
)

if TYPE_CHECKING:
    from ..setup import KeyframeType, Lightshow


INVALID_COLOR_KEYFRAMES = (
    "Some drones have inconsistent color keyframes.\n"
    "This should not happen.\n"
    "Please report this issue to the Sparkshow Creator project."
)

RGBW_FCURVES = tuple[
    bpy.types.FCurve,
    bpy.types.FCurve,
    bpy.types.FCurve,
    bpy.types.FCurve,
]
RGBW_KEYFRAMES = tuple[
    bpy.types.Keyframe,
    bpy.types.Keyframe,
    bpy.types.Keyframe,
    bpy.types.Keyframe,
]
RGBW = tuple[float, float, float, float]


def _iter_materials_recursive(drone: bpy.types.Object):
    """Yield unique materials found on the drone and all descendants."""
    seen = set()
    stack = [drone]
    while stack:
        obj = stack.pop()
        if obj is None:
            continue
        try:
            children = list(obj.children)
        except Exception:
            children = []
        stack.extend(children)

        materials = []
        try:
            if obj.active_material:
                materials.append(obj.active_material)
        except Exception:
            pass
        try:
            for slot in obj.material_slots:
                if slot.material:
                    materials.append(slot.material)
        except Exception:
            pass

        for material in materials:
            key = material.as_pointer() if hasattr(material, "as_pointer") else id(material)
            if key in seen:
                continue
            seen.add(key)
            yield material


def _material_has_rgbw_animation(material: bpy.types.Material) -> bool:
    if not material or not material.use_nodes or not material.node_tree:
        return False
    tree = material.node_tree
    if tree.animation_data is None or tree.animation_data.action is None:
        return False
    curves = tuple(
        find_fcurve_or_none(tree, RGBW_EMISSION_MATERIAL_DATA_PATH, index)
        for index in range(4)
    )
    return all(curve is not None and len(curve.keyframe_points) > 0 for curve in curves)


def _find_rgbw_material(drone: bpy.types.Object) -> bpy.types.Material | None:
    """Find a descendant material carrying the RGBW emission animation."""
    for material in _iter_materials_recursive(drone):
        try:
            if not material.use_nodes or not material.node_tree:
                continue
            if material.node_tree.nodes.get("RGBW Emission") and _material_has_rgbw_animation(material):
                return material
        except Exception:
            continue
    return None


def _uses_object_color(drone: bpy.types.Object) -> bool:
    """Return whether this drone uses the shared Object.color backend.

    The old name-based fallback was removed because real Sparkshow drones can
    also use the legacy per-drone RGBW Emission material on a child object.
    The explicit custom property is authoritative; an existing complete
    Object.color animation is accepted as a compatibility fallback.
    """
    if bool(drone.get("sparkshow_object_color", False)):
        return True
    if drone.animation_data and drone.animation_data.action:
        curves = tuple(find_fcurve_or_none(drone, "color", index) for index in range(4))
        if all(curve is not None and len(curve.keyframe_points) > 0 for curve in curves):
            return True
    # If a child material already contains the baked RGBW animation, it is the
    # authoritative color backend for this scene.
    return _find_rgbw_material(drone) is None


def create_color_attribute_node(
    nodes: bpy.types.Nodes,
) -> bpy.types.Node:
    color_attribute = nodes.new(type="ShaderNodeAttribute")
    color_attribute.name = "Color Attribute"
    color_attribute.attribute_name = "Color"  # pyright: ignore
    color_attribute.location = (-300, 0)
    return color_attribute


def create_rgbw_emission_node(
    nodes: bpy.types.Nodes,
    lightshow: "Lightshow",
) -> bpy.types.Node:
    emission = nodes.new(type="ShaderNodeEmission")
    emission.name = "RGBW Emission"
    emission.location = (-100, 0)
    emission.inputs["Color"].default_value = (1, 1, 1, 0)  # pyright: ignore
    emission.inputs["Strength"].default_value = 5.0  # Render-only shader baseline; overridden by the visual-intensity setting.
    return emission


def create_output_material(nodes: bpy.types.Nodes) -> bpy.types.Node:
    output_material = nodes.new(type="ShaderNodeOutputMaterial")
    output_material.location = (100, 0)
    return output_material


def add_driver_from_from_emission_color_and_white_to_diffuse_color(
    material: bpy.types.Material,
) -> None:
    drivers = [material.driver_add("diffuse_color", index).driver for index in range(3)]
    for index, driver in enumerate(drivers):
        driver.type = "SUM"
        variable = driver.variables.new()
        target = variable.targets[0]
        target.id_type = "MATERIAL"
        target.id = material
        target.data_path = (
            f'node_tree.nodes["RGBW Emission"].inputs["Color"].default_value[{index}]'
        )
        variable = driver.variables.new()
        target = variable.targets[0]
        target.id_type = "MATERIAL"
        target.id = material
        target.data_path = 'node_tree.nodes["RGBW Emission"].inputs["Color"].default_value[3]'


def create_shared_drone_material(lightshow: "Lightshow") -> bpy.types.Material:
    """Create/reuse the single material used by all show drones.

    Drone colors are stored on each Object (Object.color), so the material and
    mesh can safely be shared across thousands of drones.
    """
    name = "Sparkshow Drone RGBW (Shared)"
    material = bpy.data.materials.get(name)
    if material is not None:
        try:
            material.node_tree.nodes["RGBW Emission"]
            return material
        except (AttributeError, KeyError):
            bpy.data.materials.remove(material)

    material = bpy.data.materials.new(name=name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()

    object_info = nodes.new(type="ShaderNodeObjectInfo")
    object_info.name = "Drone Object Color"
    object_info.location = (-300, 0)
    emission = create_rgbw_emission_node(nodes, lightshow)
    output = create_output_material(nodes)
    links.new(object_info.outputs["Color"], emission.inputs["Color"])
    links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return material


def create_emission_material(
    mesh: bpy.types.Object,
    lightshow: "Lightshow",
) -> bpy.types.Material:
    """Create a private RGBW emission material for non-drone meshes/effectors."""
    drone_material = bpy.data.materials.new(name=f"{mesh.name} RGBW Emission")
    drone_material.use_nodes = True
    drone_material.node_tree.links.clear()  # pyright: ignore
    drone_material.node_tree.nodes.clear()  # pyright: ignore
    nodes = drone_material.node_tree.nodes  # pyright: ignore
    links = drone_material.node_tree.links  # pyright: ignore
    create_color_attribute_node(nodes)
    rgbw_emission = create_rgbw_emission_node(nodes, lightshow)
    output_material = create_output_material(nodes)
    links.new(rgbw_emission.outputs["Emission"], output_material.inputs["Surface"])
    cast(bpy.types.Mesh, mesh.data).materials.append(drone_material)

    add_driver_from_from_emission_color_and_white_to_diffuse_color(drone_material)

    return drone_material


def initialize_emission_material(
    blender_drone: bpy.types.Object,
    current_frame: int,
    lightshow: "Lightshow",
) -> None:
    """Initialize a drone using the shared RGBW material.

    The animation lives on Object.color, not on the material node tree. This
    avoids one material/action per drone while preserving per-drone animation.
    """
    blender_drone["sparkshow_object_color"] = True
    material = create_shared_drone_material(lightshow)
    mesh = cast(bpy.types.Mesh, blender_drone.data)
    # Blender's MaterialSlot collection accepts names for membership tests,
    # not Material datablocks.  Since the drone mesh is shared in Sparkshow,
    # never clear the collection here: doing so would alter every drone that
    # already uses the same mesh.  Ensure the shared material is present.
    if mesh.materials.get(material.name) is None:
        mesh.materials.append(material)

    # Make the shared RGBW material the active slot so the shader used by the
    # drone is deterministic even when the template came from an older show.
    shared_index = next(
        (index for index, slot_material in enumerate(mesh.materials)
         if slot_material is material or slot_material.name == material.name),
        None,
    )
    if shared_index is not None:
        blender_drone.active_material_index = shared_index
    blender_drone.color = (0.0, 0.0, 0.0, 0.0)
    blender_drone.keyframe_insert(data_path="color", frame=current_frame)
    rgbw_fcurves = get_color_fcurves_or_create(blender_drone)
    for fcurve in rgbw_fcurves:
        change_keyframes_type(fcurve, [current_frame], lightshow.takeoff_keyframe)


def is_color_close(color1: RGBW, color2: RGBW) -> bool:
    """Return True if the two colors have the same RGBW values."""
    return ((np.array(color1) * 255).round() == (np.array(color2) * 255).round()).all()


def animate_emission_color(
    blender_drone: bpy.types.Object,
    rgbw: RGBW,
    frame_delta: int,
    interpolation: str,
    keyframe_type: "KeyframeType",
) -> None:
    frame_start = bpy.context.scene.frame_current
    frame_end = frame_start + frame_delta

    # Drone colors are animated on the object so all drones can share one
    # material and one mesh.
    blender_drone.keyframe_insert(data_path="color", frame=frame_start)
    set_active_material_color(blender_drone, rgbw)
    blender_drone.keyframe_insert(data_path="color", frame=frame_end)

    rgbw_fcurves = get_color_fcurves_or_create(blender_drone)
    for fcurve in rgbw_fcurves:
        change_keyframes_type(
            fcurve,
            [frame_start, frame_end],
            keyframe_type,
        )

    if frame_delta == 0:
        interpolation = "CONSTANT"
        frame_start -= 1

    for fcurve in rgbw_fcurves:
        change_interpolation(
            fcurve,
            interpolation,
            frame_start,
        )
        change_interpolation(
            fcurve,
            "CONSTANT",
            frame_end,
        )


def register_emission_color(
    blender_drone: bpy.types.Object,
    rgbw: RGBW,
    interpolation: str,
    keyframe_type: "KeyframeType",
    frame: int,
) -> None:
    set_active_material_color(blender_drone, rgbw)
    blender_drone.keyframe_insert(data_path="color", frame=frame)

    rgbw_fcurves = get_color_fcurves_or_create(blender_drone)
    for fcurve in rgbw_fcurves:
        change_keyframes_type(fcurve, [frame], keyframe_type)
        change_interpolation(fcurve, interpolation, frame)


def keyframe_active_material_color(material: bpy.types.Material, frame: int) -> None:
    """Keyframe the RGBW emission of a non-drone material (legacy API)."""
    material.node_tree.keyframe_insert(
        data_path=RGBW_EMISSION_MATERIAL_DATA_PATH,
        frame=frame,
    )


def get_active_material_color(
    mesh: bpy.types.Object,
    index: int | None = None,
) -> RGBW:
    """Return the current RGBW color, using Object.color for show drones."""
    if _uses_object_color(mesh) and index is None:
        return tuple(mesh.color)  # pyright: ignore[reportReturnType]
    material = (
        mesh.active_material
        if index is None
        else cast("bpy.types.Mesh", mesh.data).materials[index]
    )
    assert material is not None
    rgbw_emission = material.node_tree.nodes["RGBW Emission"]
    return tuple(rgbw_emission.inputs["Color"].default_value)  # pyright: ignore


def set_active_material_color(
    blender_drone: bpy.types.Object,
    rgbw: RGBW,
) -> None:
    if _uses_object_color(blender_drone):
        blender_drone.color = rgbw
        return
    assert blender_drone.active_material is not None
    rgbw_emission = blender_drone.active_material.node_tree.nodes["RGBW Emission"]
    rgbw_emission.inputs["Color"].default_value = rgbw


def get_color_fcurves(drone: bpy.types.Object) -> RGBW_FCURVES | None:
    """Return the complete RGBW animation from the backend actually used."""
    if _uses_object_color(drone):
        fcurves = tuple(
            find_fcurve_or_none(drone, "color", color_index)
            for color_index in range(4)
        )
        if all(fcurve is not None and len(fcurve.keyframe_points) > 0 for fcurve in fcurves):
            return cast(RGBW_FCURVES, fcurves)

    material = _find_rgbw_material(drone)
    if material is None:
        # Legacy scenes may have the material on the active object but with no
        # keyframes yet. Keep that path available for create/bake operations.
        for candidate in _iter_materials_recursive(drone):
            try:
                if candidate.node_tree and candidate.node_tree.nodes.get("RGBW Emission"):
                    material = candidate
                    break
            except Exception:
                pass

    if material is None or not material.node_tree:
        return None

    fcurves = tuple(
        find_fcurve_or_none(
            material.node_tree,
            RGBW_EMISSION_MATERIAL_DATA_PATH,
            color_index,
        )
        for color_index in range(4)
    )
    if all(fcurve is not None and len(fcurve.keyframe_points) > 0 for fcurve in fcurves):
        return cast(RGBW_FCURVES, fcurves)
    return None


def get_color_fcurves_or_create(drone: bpy.types.Object) -> RGBW_FCURVES:
    if _uses_object_color(drone):
        return cast(
            RGBW_FCURVES,
            tuple(find_fcurve_or_create(drone, "color", color_index) for color_index in range(4)),
        )
    assert drone.active_material is not None
    return cast(
        RGBW_FCURVES,
        tuple(
            find_fcurve_or_create(
                drone.active_material.node_tree,
                RGBW_EMISSION_MATERIAL_DATA_PATH,
                color_index,
            )
            for color_index in range(4)
        ),
    )


def copy_colors_action(drone: bpy.types.Object) -> bpy.types.Action:
    get_color_fcurves_or_create(drone)
    assert drone.animation_data is not None and drone.animation_data.action is not None
    return cast(bpy.types.Action, drone.animation_data.action.copy())


def replace_colors_action(drone: bpy.types.Object, action: bpy.types.Action) -> None:
    if drone.animation_data is None:
        drone.animation_data_create()
    drone.animation_data.action = action


def get_colors_fcurves_from_action(action: bpy.types.Action) -> RGBW_FCURVES:
    return cast(
        RGBW_FCURVES,
        tuple(
            find_fcurve_or_none_from_fcurves(action.fcurves, "color", color_index)
            for color_index in range(4)
        ),
    )


def get_colors_keyframes(rgbw_fcurves: RGBW_FCURVES) -> Iterator[RGBW_KEYFRAMES] | None:
    if len(rgbw_fcurves) != 4 or any(fcurve is None for fcurve in rgbw_fcurves):
        return None
    length = len(rgbw_fcurves[0].keyframe_points)
    if any(len(fcurve.keyframe_points) != length for fcurve in rgbw_fcurves[1:]):
        raise RuntimeError(INVALID_COLOR_KEYFRAMES)
    if length == 0:
        return None
    return zip(
        rgbw_fcurves[0].keyframe_points,
        rgbw_fcurves[1].keyframe_points,
        rgbw_fcurves[2].keyframe_points,
        rgbw_fcurves[3].keyframe_points,
        strict=True,
    )

def check_color_keyframes_consistency(rgbw: RGBW_KEYFRAMES) -> tuple[int, str]:
    """Validate that the four RGBW curves share frame and interpolation data."""
    frame = rgbw[0].co[0]
    if not all(keyframe.co[0] == frame for keyframe in rgbw[1:]):
        raise RuntimeError(INVALID_COLOR_KEYFRAMES)
    interpolation = rgbw[0].interpolation
    if not all(keyframe.interpolation == interpolation for keyframe in rgbw[1:]):
        raise RuntimeError(INVALID_COLOR_KEYFRAMES)
    return round(frame), interpolation


def get_keyframes_color(rgbw: RGBW_KEYFRAMES) -> RGBW:
    return tuple(rgbw[index].co[1] for index in range(4))  # pyright: ignore[reportReturnType]


def set_keyframes_color(rgbw_keyframes: RGBW_KEYFRAMES, rgbw: RGBW) -> None:
    for index in range(4):
        rgbw_keyframes[index].co[1] = rgbw[index]


def pick_color(
    drone: bpy.types.Object,
    frame_current: int,
) -> RGBW | None:
    """Pick the evaluated RGBW color at the current frame.

    Exact-keyframe matching is intentionally avoided: a baked animation may
    use interpolation between keys, and the user should be able to pick the
    color visible at any frame. The four channels are evaluated together from
    the backend that actually stores the animation.
    """
    rgbw_fcurves = get_color_fcurves(drone)
    if rgbw_fcurves is None:
        return None
    try:
        return tuple(float(fcurve.evaluate(frame_current)) for fcurve in rgbw_fcurves)  # type: ignore[return-value]
    except Exception:
        return None


def swap_color(
    drone: bpy.types.Object,
    old_color: RGBW,
    new_color: RGBW,
    frame_start: int,
    frame_end: int,
) -> int:
    nb_swapped = 0

    rgbw_fcurves = get_color_fcurves(drone)
    if rgbw_fcurves is None:
        return nb_swapped

    colors_keyframes = get_colors_keyframes(rgbw_fcurves)
    if colors_keyframes is None:
        return nb_swapped

    for rgbw in colors_keyframes:
        frame, _ = check_color_keyframes_consistency(rgbw)
        if frame < frame_start:
            continue
        if frame > frame_end:
            break
        color = get_keyframes_color(rgbw)
        if np.allclose(color, old_color):
            set_keyframes_color(rgbw, new_color)
            nb_swapped += 1

    return nb_swapped


TFrameData = TypeVar("TFrameData")


def bake_color(  # noqa: C901, PLR0913, PLR0915
    context: bpy.types.Context,
    drones: list[bpy.types.Object],
    frame_start: int,
    frame_end: int,
    frame_step: int,
    interpolation: str,
    keyframe_type: "KeyframeType",
    get_frame_data_fn: Callable[[], TFrameData],
    get_drone_color_fn: Callable[[bpy.types.Object, TFrameData], RGBW],
) -> None:
    """Bake the color of the given drones.

    The baking is done on a copy of the fcurves to avoid interfering with the original fcurves.

    Args:
        context: The context of the operator.
        drones: The drones to bake the color of.
        frame_start: The start frame of the baking.
        frame_end: The end frame of the baking.
        frame_step: The step of the baking.
        interpolation: The interpolation of the keyframes.
        keyframe_type: The type of the keyframes.
        get_frame_data_fn: A function that returns the frame data.
        get_drone_color_fn: A function that returns the color of the drone at the given frame.
        keep_old_keyframes: Whether to remove the old keyframes before adding new ones.
    """
    # Exit early if there is no need to bake
    if len(drones) == 0:
        return

    def remove_old_keyframes() -> None:
        """Remove the old keyframes.

        This avoids having several keyframes at the same frame which can cause issues
        when the baking is done multiple times.
        """
        for rgbw_fcurves in tqdm(drones_rgbw_fcurves, desc="Removing old keyframes", unit="drone"):
            for fcurve in rgbw_fcurves:
                # Remove old keyframes before adding new ones
                remove_range_keyframes(fcurve, frame_start - 1, frame_end + 1)

    def add_color_keyframe(
        rgbw_fcurves: RGBW_FCURVES,
        frame: int,
        color: RGBW,
        interpolation: str = interpolation,
    ) -> None:
        """Add a new color keyframe at the given frame."""
        for v, fcurve in zip(color, rgbw_fcurves, strict=True):
            fcurve.keyframe_points.add(1)
            keyframe = fcurve.keyframe_points[-1]
            keyframe.co = frame, v
            keyframe.interpolation = interpolation  # pyright: ignore
            keyframe.type = keyframe_type

    @contextmanager
    def disable_magic_color() -> Generator[None, None, None]:
        """Context manager to disable the magic color.

        This is used to get the pre and post colors without the magic color.
        """
        lightshow.disable_magic_color = True
        yield
        lightshow.disable_magic_color = False

    def add_pre_and_post_color_keyframes() -> None:
        """Add the pre and post colors keyframes.

        This avoids unexpected color interpolations before and after the baking range.
        """
        frames = [frame_end + 1]
        # Do not add a pre keyframe if the start frame is 0, as it would be invalid
        if frame_start > 0:
            frames.append(frame_start - 1)

        with disable_magic_color():
            for frame in frames:
                scene.frame_set(frame)
                frame_data = get_frame_data_fn()
                for drone, rgbw_fcurves in zip(drones, drones_rgbw_fcurves, strict=True):
                    add_color_keyframe(
                        rgbw_fcurves,
                        frame,
                        get_drone_color_fn(drone, frame_data),
                        # Use constant interpolation to avoid unexpected color interpolation
                        interpolation="CONSTANT",
                    )

    def bake_color_in_frame_range() -> None:
        """Add keyframes only when the color changes."""
        last_colors: list[RGBW | None] = [None] * len(drones)
        last_frames: list[int | None] = [None] * len(drones)
        for frame in tqdm(
            itertools.chain([frame_end], range(frame_start, frame_end, frame_step)),
            total=(frame_end - 1 - frame_start) // frame_step + 2,
            desc="Baking color",
            unit="frame",
        ):
            # Update the scene frame
            context.scene.frame_set(frame)
            # Get the data of the current frame used to get the color
            frame_data = get_frame_data_fn()
            for index, (drone, rgbw_fcurves, last_color, last_frame) in enumerate(
                zip(drones, drones_rgbw_fcurves, last_colors, last_frames, strict=True)
            ):
                # Get the drone color
                color = get_drone_color_fn(drone, frame_data)
                # Add a new keyframe only if
                # - No previous keyframe exists
                # - The previous color is different from the current one
                # - This is the last frame
                if (
                    last_color is None
                    or not is_color_close(color, last_color)
                    or frame == frame_end
                ):
                    if last_color is not None and last_frame is not None:
                        add_color_keyframe(rgbw_fcurves, last_frame, last_color)
                    add_color_keyframe(rgbw_fcurves, frame, color)
                    last_colors[index] = color
                    last_frames[index] = None
                # The color is the same as the previous one
                else:
                    # Update the last frame the color should be added at
                    last_frames[index] = frame

    def update_color_fcurves() -> None:
        """Update the color fcurves after manually adding keyframes.

        This is required by Blender.
        """
        for rgbw_fcurves in drones_rgbw_fcurves:
            for fcurve in rgbw_fcurves:
                fcurve.update()

    scene = context.scene
    lightshow = get_lightshow(scene)

    # Work directly on the per-drone Object.color F-curves. Unlike the old
    # material-based implementation, the location/fire animation remains in
    # the same Action and is never copied or replaced.
    drones_rgbw_fcurves = [get_color_fcurves_or_create(drone) for drone in drones]

    remove_old_keyframes()
    add_pre_and_post_color_keyframes()
    bake_color_in_frame_range()
    update_color_fcurves()
    return
