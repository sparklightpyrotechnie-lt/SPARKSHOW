from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal, cast

import bpy
import numpy as np

from sparkshow_studio._loader.parameters import IOSTAR_PHYSIC_PARAMETERS_MAX as PHYSIC_PARAMETERS_MAX
from sparkshow_studio._loader.parameters import (
    IOSTAR_PHYSIC_PARAMETERS_RECOMMENDATION as PHYSIC_PARAMETERS_RECOMMENDATION,
)
from sparkshow_studio._loader.parameters import TAKEOFF_PARAMETERS, IostarPhysicParameters
from sparkshow_studio._loader.schemas import Metadata

from . import bl_info
from .tools.collection_tools import get_drones, get_nb_drones_per_family, is_drone
from .tools.drone_tools import update_drone
from .tools.geometry_tools import get_anchors_min_distance
from .tools.grid_tools import update_drone_grid
from .tools.math_tools import get_filtered_divisors
from .tools.mesh_tools import update_mesh_converter_node
from .tools.picture_tools import get_picture_meshes, update_picture_info
from .tools.proximity_lines_tools import update_proximity_warning_lines

# TODO(jonathan): Use the value from the loader
FPS = 24
POSITION_FRAME_STEP = 6
GAP_BETWEEN_PLATFORMS = 0.5

MAX_NB_X_Y = 50

KEYFRAME_TYPE = [
    ("KEYFRAME", "Keyframe", "", "KEYTYPE_KEYFRAME_VEC", 0),
    ("BREAKDOWN", "Breakdown", "", "KEYTYPE_BREAKDOWN_VEC", 1),
    ("MOVING_HOLD", "Moving Hold", "", "KEYTYPE_MOVING_HOLD_VEC", 2),
    ("EXTREME", "Extreme", "", "KEYTYPE_EXTREME_VEC", 3),
    ("JITTER", "Jitter", "", "KEYTYPE_JITTER_VEC", 4),
]

INTERPOLATION = [
    ("CONSTANT", "Constant", "The color change is instantaneous", "IPO_CONSTANT", 0),
    ("LINEAR", "Linear", "The color change is linear", "IPO_LINEAR", 1),
    ("BEZIER", "Bezier", "The color change is smooth", "IPO_BEZIER", 2),
]


def execute_operator(
    self: "Lightshow",  # noqa: ARG001
    context: bpy.types.Context | None,  # noqa: ARG001
) -> list[tuple[str, str, str, int]]:
    effector_name_list: list[tuple[str, str, str, int]] = []
    for collection in bpy.data.collections:
        if collection.name == "Effector":
            for cpt, obj in enumerate(collection.all_objects):
                effector_name_list.append((obj.name, obj.name, "", cpt))
    return effector_name_list


def update_fire_preview(self: "Lightshow", context: bpy.types.Context) -> None:  # noqa: ARG001
    """Refresh Fire viewport preview after a preview setting changes."""
    try:
        from .fire.preview import refresh_preview

        refresh_preview(context.scene)
    except (ImportError, RuntimeError):
        # Keep property editing safe during addon registration/reload and headless use.
        pass


def update_property_factory(
    property_name: str,
    *callbacks: Callable[..., Any],
) -> Callable[["Lightshow", bpy.types.Context], None]:
    """Run the callbacks after the property is updated and lock the property after the show init."""

    def update_property(self: "Lightshow", context: bpy.types.Context) -> None:
        drones = get_drones(context.scene.collection)
        old_property_name = "old_" + property_name
        if len(drones) == 0:
            for callback in callbacks:
                callback(self, context)
            setattr(self, old_property_name, getattr(self, property_name))
        elif getattr(self, property_name) != getattr(self, old_property_name):
            setattr(self, property_name, getattr(self, old_property_name))

    return update_property


def get_drone_repartitions(
    nb_drones: int,
    nb_drones_per_family: int,
) -> list[tuple[int, int]] | None:
    """Get the possible drone repartitions for the specified number of drones and drones per family."""
    if nb_drones % nb_drones_per_family != 0:
        return None

    nb_families = nb_drones // nb_drones_per_family
    filtered_divisors = get_filtered_divisors(nb_families, MAX_NB_X_Y)

    if not filtered_divisors:
        return None

    return [
        (filtered_divisor, nb_families // filtered_divisor)
        for filtered_divisor in filtered_divisors
    ]


def set_drone_repartition(self: "Lightshow", drone_repartition: tuple[int, int]) -> None:
    """Set the drone repartition to the specified value.

    Avoid triggering the recalculate_nb_drones callback.
    """
    nb_x, nb_y = drone_repartition
    self.old_nb_x = self.nb_x = nb_x
    self.old_nb_y = self.nb_y = nb_y


def set_closest_drone_repartition(self: "Lightshow", ratio: float | None = None) -> None:
    """Set the closest repartition to the current ratio or the specified ratio."""
    if ratio is None:
        ratio = self.nb_y / self.nb_x
    drone_repartitions = get_drone_repartitions(self.nb_drones, self.nb_drones_per_family)
    if drone_repartitions is None:
        return
    drone_repartitions_ratio = [
        drone_repartition[1] / drone_repartition[0] for drone_repartition in drone_repartitions
    ]
    closest_drone_repartition_index = int(
        np.argmin(
            np.abs(np.array(drone_repartitions_ratio) - ratio),
        ),
    )
    self.drone_repartition_index = closest_drone_repartition_index
    drone_repartition = drone_repartitions[closest_drone_repartition_index]
    if (self.nb_x, self.nb_y) != drone_repartition:
        set_drone_repartition(self, drone_repartition)


def update_nb_drones(self: "Lightshow", context: bpy.types.Context) -> None:  # noqa: ARG001
    """Handle the number of drones change."""
    if self.nb_drones == self.old_nb_drones:
        return

    if (
        self.nb_drones <= self.nb_drones_per_family
        and self.takeoff_mode != "using all in one platform"
    ):
        self.nb_drones_per_family = self.nb_drones
        return

    # Round the number of drones to the nearest multiple of the number of drones per family
    # in the direction of the change
    rest = self.nb_drones % self.nb_drones_per_family
    if rest != 0:
        if self.nb_drones > self.old_nb_drones:
            self.nb_drones += self.nb_drones_per_family - rest
        else:
            self.nb_drones -= rest
    else:
        # Only update the repartition if the number of drones has not changed in the callback
        set_closest_drone_repartition(self, ratio=1)


def recalculate_nb_drones(self: "Lightshow", context: bpy.types.Context) -> None:  # noqa: ARG001
    """Recalculate the number of drones."""
    # Avoid triggering the update_nb_drones callback when set_drone_repartition() has been used
    if self.nb_x == self.old_nb_x and self.nb_y == self.old_nb_y:
        return

    nb_drones = self.nb_x * self.nb_y * self.nb_drones_per_family
    if nb_drones != self.nb_drones:
        self.old_nb_drones = self.nb_drones = self.nb_x * self.nb_y * self.nb_drones_per_family
        drone_repartitions = get_drone_repartitions(self.nb_drones, self.nb_drones_per_family)
        if drone_repartitions is None:
            return
        self.drone_repartition_index = drone_repartitions.index((self.nb_x, self.nb_y))


def update_takeoff_mode(self: "Lightshow", context: bpy.types.Context) -> None:
    if self.takeoff_mode == "using all in one platform":
        self.nb_drones_per_family = TAKEOFF_PARAMETERS.nb_drones_per_platform
        self.step_x = TAKEOFF_PARAMETERS.platform_length
        self.step_y = TAKEOFF_PARAMETERS.platform_width

        if get_lightshow(context.scene).installation_gap == "COLUMN":
            self.step_x += GAP_BETWEEN_PLATFORMS
        else:
            self.step_y += GAP_BETWEEN_PLATFORMS
    elif self.takeoff_mode == "standard_takeoff":
        # trigger the update_step callback
        self.step_x = max(self.step_x, PHYSIC_PARAMETERS_RECOMMENDATION.minimum_distance)
        self.step_y = self.step_x
    else:
        raise ValueError(f"Unknown takeoff mode: {self.takeoff_mode}")


def update_nb_drones_per_family(self: "Lightshow", context: bpy.types.Context) -> None:
    """Handle the number of drones per family change."""
    drones = get_drones(context.scene.collection)
    if len(drones) != 0:
        self.nb_drones_per_family = get_nb_drones_per_family(context.scene.collection)

    # Special case for one family
    # The number of drones is set to the number of drones per family
    if self.nb_x == self.nb_y == 1 and self.nb_drones != self.nb_drones_per_family:
        self.nb_drones = self.nb_drones_per_family
        update_drone_grid(self, context)
        return

    set_closest_drone_repartition(self)
    update_drone_grid(self, context)


def update_step(self: "Lightshow", context: bpy.types.Context) -> None:
    """Handle the step change."""
    if (
        self.takeoff_mode == "standard_takeoff"
        and self.step_x < PHYSIC_PARAMETERS_RECOMMENDATION.minimum_distance
    ):
        self.step_x = max(self.step_x, PHYSIC_PARAMETERS_RECOMMENDATION.minimum_distance)
    if self.takeoff_mode == "standard_takeoff" and self.step_x != self.step_y:
        self.step_y = self.step_x
    update_property_factory("step_x", update_drone_grid)(self, context)


def update_emission_strength(self: "Lightshow", context: bpy.types.Context) -> None:
    """Apply a Blender-only visual intensity to RGBW Emission shaders.

    This property is intentionally render/viewport-only. The show/export
    pipeline reads RGBW color keyframes, not the emission Strength socket,
    and this callback never creates or edits color keyframes.
    """
    scene = getattr(context, "scene", None)
    if scene is None:
        return

    materials: set[bpy.types.Material] = set()
    for obj in scene.objects:
        try:
            for slot in obj.material_slots:
                material = slot.material
                if material is not None:
                    materials.add(material)
        except (AttributeError, RuntimeError):
            pass

        try:
            material = obj.active_material
            if material is not None:
                materials.add(material)
        except (AttributeError, RuntimeError):
            pass

    strength = max(0.0, float(self.emission_strength))
    for material in materials:
        try:
            node = material.node_tree.nodes.get("RGBW Emission")
            if node is None:
                continue
            socket = node.inputs.get("Strength")
            if socket is not None:
                socket.default_value = strength
        except (AttributeError, RuntimeError, KeyError):
            pass


def update_min_anchors_distance(self: "Lightshow", context: bpy.types.Context) -> None:
    """Handle the minimal anchors distance change.

    Scale the active object to respect the minimal anchors distance if possible.
    """
    if np.isclose(self.min_anchors_distance, 0):
        return
    obj = context.active_object
    if obj is None or is_drone(obj):
        return
    anchors_min_distance = get_anchors_min_distance(obj)
    if (
        anchors_min_distance is None
        or np.isclose(anchors_min_distance, self.min_anchors_distance)
        or np.isclose(anchors_min_distance, 0)
    ):
        return
    obj.scale *= self.min_anchors_distance / anchors_min_distance


class LightshowSetup(bpy.types.PropertyGroup):
    """Global Lightshow properties."""

    nb_drones: bpy.props.IntProperty(  # pyright: ignore
        name="Nb drones",
        description="The number of drones in the show",
        min=1,
        soft_min=1,
        default=1,
        update=update_property_factory("nb_drones", update_nb_drones, update_drone_grid),
    )
    old_nb_drones: bpy.props.IntProperty(  # pyright: ignore
        name="Old Nb drones",
        description="The old number of drones in the show",
        min=1,
        soft_min=1,
        default=1,
    )
    drone_repartition_index: bpy.props.IntProperty(  # pyright: ignore
        name="drone repartition",
        description="The state of the drone repartion",
        default=1,
    )
    nb_x: bpy.props.IntProperty(  # pyright: ignore
        name="Nb X",
        description="The number of drones in the X axis (West-East)",
        min=1,
        soft_min=1,
        max=MAX_NB_X_Y,
        soft_max=MAX_NB_X_Y,
        default=1,
        update=update_property_factory("nb_x", recalculate_nb_drones, update_drone_grid),
    )
    nb_y: bpy.props.IntProperty(  # pyright: ignore
        name="Nb Y",
        description="The number of drones in the Y axis (South-North)",
        min=1,
        soft_min=1,
        max=MAX_NB_X_Y,
        soft_max=MAX_NB_X_Y,
        default=1,
        update=update_property_factory("nb_y", recalculate_nb_drones, update_drone_grid),
    )
    nb_drones_per_family: bpy.props.IntProperty(  # pyright: ignore
        name="Nb per family",
        description="The number of drones per family",
        min=1,
        soft_min=1,
        max=9,
        soft_max=9,
        default=1,
        update=update_nb_drones_per_family,
    )
    step: bpy.props.FloatProperty(  # pyright: ignore
        max=10,
        soft_max=10,
        default=2,
    )
    step_x: bpy.props.FloatProperty(  # pyright: ignore
        name="Step",
        description="The distance between the families (x axis)",
        subtype="DISTANCE",
        min=TAKEOFF_PARAMETERS.platform_length,
        soft_min=PHYSIC_PARAMETERS_RECOMMENDATION.minimum_distance,
        max=10,
        soft_max=10,
        default=2,
        update=update_step,
        get=lambda self: self.step,
        set=lambda self, value: setattr(self, "step", value),
    )
    step_y: bpy.props.FloatProperty(  # pyright: ignore
        name="Step y",
        description="The distance between the families (y axis)",
        subtype="DISTANCE",
        min=TAKEOFF_PARAMETERS.platform_width,
        soft_min=PHYSIC_PARAMETERS_RECOMMENDATION.minimum_distance,
        max=10,
        soft_max=10,
        default=2,
        update=update_property_factory("step_y", update_drone_grid),
    )
    angle_takeoff: bpy.props.FloatProperty(  # pyright: ignore
        name="Angle",
        description="""The takeoff angle""",
        subtype="ANGLE",
        default=0,
        precision=0,
        update=update_property_factory("angle_takeoff", update_drone_grid),
    )
    old_nb_x: bpy.props.IntProperty(  # pyright: ignore
        name="Old Nb X",
        description="The old number of drones in the X axis (West-East)",
        min=1,
        soft_min=1,
        max=MAX_NB_X_Y,
        soft_max=MAX_NB_X_Y,
        default=1,
    )
    old_nb_y: bpy.props.IntProperty(  # pyright: ignore
        name="Old Nb Y",
        description="The old number of drones in the Y axis (South-North)",
        min=1,
        soft_min=1,
        max=MAX_NB_X_Y,
        soft_max=MAX_NB_X_Y,
        default=1,
    )
    old_step_x: bpy.props.FloatProperty(  # pyright: ignore
        name="Old Step",
        description="The old distance between the families",
        subtype="DISTANCE",
        min=PHYSIC_PARAMETERS_RECOMMENDATION.minimum_distance,
        soft_min=PHYSIC_PARAMETERS_RECOMMENDATION.minimum_distance,
        max=10,
        soft_max=10,
        default=2,
    )
    old_step_y: bpy.props.FloatProperty(  # pyright: ignore
        name="Old Step",
        description="The old distance between the families",
        subtype="DISTANCE",
        min=PHYSIC_PARAMETERS_RECOMMENDATION.minimum_distance,
        soft_min=PHYSIC_PARAMETERS_RECOMMENDATION.minimum_distance,
        max=10,
        soft_max=10,
        default=2,
    )
    old_angle_takeoff: bpy.props.FloatProperty(  # pyright: ignore
        name="Old Angle",
        description="The old takeoff angle",
        subtype="ANGLE",
        default=0,
        precision=0,
    )
    color: bpy.props.FloatVectorProperty(  # pyright: ignore
        name="Color",
        description="""\
Set color: The color to set on the drones
Swap color: The color to swap from""",
        subtype="COLOR",
        min=0,
        max=1,
        soft_min=0,
        soft_max=1,
        size=4,
        default=(1.0, 1.0, 1.0, 0.0),
    )
    new_color: bpy.props.FloatVectorProperty(  # pyright: ignore
        name="New Color",
        description="Swap color: The color to swap to",
        subtype="COLOR",
        min=0,
        max=1,
        soft_min=0,
        soft_max=1,
        size=4,
        default=(1.0, 1.0, 1.0, 0.0),
    )
    color_duration: bpy.props.FloatProperty(  # pyright: ignore
        name="Duration",
        description="The duration of the color change",
        subtype="TIME_ABSOLUTE",
        min=0,
        soft_min=0,
        default=0,
    )
    brightness: bpy.props.FloatProperty(  # pyright: ignore
        name="Brightness",
        description="The brightness to apply on keyframes",
        subtype="PERCENTAGE",
        min=0.0,
        soft_min=0.0,
        max=100.0,
        soft_max=100.0,
        default=100.0,
    )
    duration_mode: bpy.props.EnumProperty(  # pyright: ignore
        name="Duration Mode",
        description="The duration mode to use for the transition",
        items=[
            ("MANUAL", "Manual", "The duration is set by the user", "", 0),
            ("OPTIMAL", "Optimal", "The duration is calculated to be the shortest possible", "", 1),
        ],
        default="MANUAL",
    )
    formation_duration: bpy.props.FloatProperty(  # pyright: ignore
        name="Duration",
        description="The transition duration between formations",
        subtype="TIME_ABSOLUTE",
        min=0,
        soft_min=0,
        default=0,
        step=10,
    )
    transition_mode: bpy.props.EnumProperty(  # pyright: ignore
        name="Transition Mode",
        description="The transition mode",
        items=[
            ("TOGETHER", "Together", "The drones start and end their transition together", "", 0),
            (
                "STAGGERED",
                "Staggered",
                "The drones start their transition one after the other",
                "",
                1,
            ),
        ],
    )
    staggered_frame_step: bpy.props.IntProperty(  # pyright: ignore
        name="Frame step",
        description="The number of frames between drone transition starts",
        subtype="TIME",
        min=1,
        soft_min=1,
        default=1,
    )
    min_anchors_distance: bpy.props.FloatProperty(  # pyright: ignore
        name="Min distance",
        description="The minimal distance between the anchors on the active object",
        subtype="DISTANCE",
        min=0,
        soft_min=0,
        default=2,
        update=update_min_anchors_distance,
    )
    interpolation: bpy.props.EnumProperty(  # pyright: ignore
        name="Interpolation",
        description="The interpolation to use for the transition",
        items=INTERPOLATION,
        default="CONSTANT",
    )
    mesh_image_mode: bpy.props.EnumProperty(  # pyright: ignore
        name="Mode",
        description="The mode to use for the mesh image",
        items=[
            ("Fast", "Fast", "Rapid mode, useful for visualization"),
            (
                "Balanced",
                "Balanced",
                "Balanced mode, slower but vertices will be reparted better",
            ),
        ],
        default="Balanced",
    )
    mesh_text_mode: bpy.props.EnumProperty(  # pyright: ignore
        name="Mode",
        description="The mode to use for the mesh text",
        items=[
            ("Fast", "Fast", "Rapid mode, useful for visualization"),
            (
                "Balanced",
                "Balanced",
                "Balanced mode, slower but vertices will be reparted better",
            ),
        ],
        default="Balanced",
    )
    adjustment: bpy.props.FloatProperty(  # pyright: ignore
        name="Adjustment",
        description="If the number of anchors is far from expected number, you can try to increase this value to get a better result.",
        min=1,
        soft_min=1,
        default=1,
        max=10,
        soft_max=5,
    )
    selected_mesh: bpy.props.EnumProperty(  # pyright: ignore
        name="Mesh",
        description="Select a mesh from the Picture collection",
        items=get_picture_meshes,  # pyright: ignore
        update=update_picture_info,
    )
    nb_vertices: bpy.props.IntProperty(  # pyright: ignore
        name="Nb vertices max",
        description="Set the maximum number of vertices to create",
        min=1,
        soft_min=1,
        max=1000,
        soft_max=1000,
        default=200,
    )
    fire_duration: bpy.props.FloatProperty(  # pyright: ignore
        name="Duration",
        description="The fire duration",
        subtype="TIME_ABSOLUTE",
        min=0,
        soft_min=0,
        max=0.255,
        soft_max=0.255,
        default=0.04,
    )
    fire_vdl: bpy.props.StringProperty(  # pyright: ignore
        name="VDL",
        description="The fire VDL",
        default="",
    )
    fire_preview_enabled: bpy.props.BoolProperty(  # pyright: ignore
        name="Viewport preview",
        description="Show procedural pyrotechnic effects in the 3D viewport without changing fire export data",
        update=update_fire_preview,
        default=True,
    )
    fire_preview_light_mode: bpy.props.BoolProperty(  # pyright: ignore
        name="Light Preview",
        description="Use a reduced particle/mesh budget for faster Pyro viewport playback. Disable for full preview quality.",
        update=update_fire_preview,
        default=True,
    )
    fire_preview_renderer: bpy.props.EnumProperty(  # pyright: ignore
        name="Renderer",
        description="Viewport rendering engine for Pyro preview. Auto selects the lightest suitable mode.",
        items=[
            ("AUTO", "Auto", "GPU Points in Light Preview, Instanced Mesh otherwise"),
            ("GPU_POINTS", "GPU Points", "Fastest preview: GPU points, no particle objects"),
            ("INSTANCED_MESH", "Instanced Mesh", "Low-poly instanced mesh points"),
            ("PARTICLES", "Particle Emitters", "Blender 4.1 native emitter particle systems"),
            ("CURVES", "Curves", "Current detailed curve-based preview"),
        ],
        update=update_fire_preview,
        default="AUTO",
    )
    fire_pyro_bake_step: bpy.props.IntProperty(  # pyright: ignore
        name="Bake step",
        description="Bake every N frames. 1 = every frame; higher values reduce bake size and memory.",
        min=1,
        max=8,
        default=1,
    )
    fire_preview_active_pyro: bpy.props.EnumProperty(  # pyright: ignore
        name="Active Pyro",
        description="Pyro profile edited below",
        items=[
            ("0", "Pyro 1", "Edit Pyro 1"),
            ("1", "Pyro 2", "Edit Pyro 2"),
            ("2", "Pyro 3", "Edit Pyro 3"),
        ],
        update=update_fire_preview,
        default="0",
    )
    fire_preview_fire0_pyro: bpy.props.EnumProperty(  # pyright: ignore
        name="Fire 1 Pyro",
        description="Pyro profile assigned to Fire 1",
        items=[("0", "Pyro 1", "Use Pyro 1 profile"), ("1", "Pyro 2", "Use Pyro 2 profile"), ("2", "Pyro 3", "Use Pyro 3 profile")],
        update=update_fire_preview,
        default="0",
    )
    fire_preview_fire1_pyro: bpy.props.EnumProperty(  # pyright: ignore
        name="Fire 2 Pyro",
        description="Pyro profile assigned to Fire 2",
        items=[("0", "Pyro 1", "Use Pyro 1 profile"), ("1", "Pyro 2", "Use Pyro 2 profile"), ("2", "Pyro 3", "Use Pyro 3 profile")],
        update=update_fire_preview,
        default="1",
    )
    fire_preview_fire2_pyro: bpy.props.EnumProperty(  # pyright: ignore
        name="Fire 3 Pyro",
        description="Pyro profile assigned to Fire 3",
        items=[("0", "Pyro 1", "Use Pyro 1 profile"), ("1", "Pyro 2", "Use Pyro 2 profile"), ("2", "Pyro 3", "Use Pyro 3 profile")],
        update=update_fire_preview,
        default="2",
    )
    fire_preview_channel0_effect: bpy.props.EnumProperty(  # pyright: ignore
        name="Pyro 1 effect",
        description="Viewport effect used for fire channel 1",
        items=[
            ("FOUNTAIN", "Cascade / Fountain", "Upward fountain with falling sparks"),
            ("CRACKLING", "Crackling", "Irregular radial crackling burst"),
            ("DAY_SMOKE", "Day Smoke", "Slow expanding rising smoke cloud"),
            ("FALLING_STARS", "Falling Stars", "Bright descending comet-like sparks"),
        ],
        update=update_fire_preview,
        default="FOUNTAIN",
    )
    fire_preview_channel0_color: bpy.props.FloatVectorProperty(  # pyright: ignore
        name="Pyro 1 color",
        description="Preview color for fire channel 1",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        update=update_fire_preview,
        default=(1.0, 0.24, 0.02, 1.0),
    )
    fire_preview_channel0_duration: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 1 duration",
        description="Preview effect duration for fire channel 1",
        subtype="TIME_ABSOLUTE",
        min=0.05,
        max=30.0,
        update=update_fire_preview,
        default=1.5,
    )
    fire_preview_channel0_size: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 1 size",
        description="World-space size of the fire channel 1 preview",
        subtype="DISTANCE",
        min=0.05,
        max=100.0,
        update=update_fire_preview,
        default=2.0,
    )
    fire_preview_channel1_effect: bpy.props.EnumProperty(  # pyright: ignore
        name="Pyro 2 effect",
        description="Viewport effect used for fire channel 2",
        items=[
            ("FOUNTAIN", "Cascade / Fountain", "Upward fountain with falling sparks"),
            ("CRACKLING", "Crackling", "Irregular radial crackling burst"),
            ("DAY_SMOKE", "Day Smoke", "Slow expanding rising smoke cloud"),
            ("FALLING_STARS", "Falling Stars", "Bright descending comet-like sparks"),
        ],
        update=update_fire_preview,
        default="CRACKLING",
    )
    fire_preview_channel1_color: bpy.props.FloatVectorProperty(  # pyright: ignore
        name="Pyro 2 color",
        description="Preview color for fire channel 2",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        update=update_fire_preview,
        default=(0.25, 0.65, 1.0, 1.0),
    )
    fire_preview_channel1_duration: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 2 duration",
        description="Preview effect duration for fire channel 2",
        subtype="TIME_ABSOLUTE",
        min=0.05,
        max=30.0,
        update=update_fire_preview,
        default=1.2,
    )
    fire_preview_channel1_size: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 2 size",
        description="World-space size of the fire channel 2 preview",
        subtype="DISTANCE",
        min=0.05,
        max=100.0,
        update=update_fire_preview,
        default=1.8,
    )
    fire_preview_channel2_effect: bpy.props.EnumProperty(  # pyright: ignore
        name="Pyro 3 effect",
        description="Viewport effect used for fire channel 3",
        items=[
            ("FOUNTAIN", "Cascade / Fountain", "Upward fountain with falling sparks"),
            ("CRACKLING", "Crackling", "Irregular radial crackling burst"),
            ("DAY_SMOKE", "Day Smoke", "Slow expanding rising smoke cloud"),
            ("FALLING_STARS", "Falling Stars", "Bright descending comet-like sparks"),
        ],
        update=update_fire_preview,
        default="DAY_SMOKE",
    )
    fire_preview_channel2_color: bpy.props.FloatVectorProperty(  # pyright: ignore
        name="Pyro 3 color",
        description="Preview color for fire channel 3",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        update=update_fire_preview,
        default=(0.8, 0.8, 0.8, 1.0),
    )
    fire_preview_channel2_duration: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 3 duration",
        description="Preview effect duration for fire channel 3",
        subtype="TIME_ABSOLUTE",
        min=0.05,
        max=30.0,
        update=update_fire_preview,
        default=2.5,
    )
    fire_preview_channel2_size: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 3 size",
        description="World-space size of the fire channel 3 preview",
        subtype="DISTANCE",
        min=0.05,
        max=100.0,
        update=update_fire_preview,
        default=3.0,
    )
    # Pyrotechnic preview controls (4.1.14): common and effect-specific physical parameters.
    fire_preview_channel0_lifetime: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 1 lifetime", description="Lifetime of individual pyrotechnic particles or smoke puffs", subtype="TIME_ABSOLUTE", min=0.05, max=60.0, default=1.8, update=update_fire_preview,
    )
    fire_preview_channel0_intensity: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 1 intensity", description="Preview brightness multiplier", min=0.1, max=20.0, default=2.5, update=update_fire_preview,
    )
    fire_preview_channel0_gpu_particle_size: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 1 particle size",
        description="GPU preview particle diameter in viewport pixels",
        min=1.0, max=48.0, default=9.0,
        update=update_fire_preview,
    )
    fire_preview_channel0_gpu_glow: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 1 glow",
        description="GPU preview glow halo strength",
        min=0.0, max=4.0, default=1.0,
        update=update_fire_preview,
    )
    fire_preview_channel0_gravity: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 1 gravity", description="Preview gravity in m/s²", min=0.0, max=40.0, default=9.81, update=update_fire_preview,
    )
    fire_preview_channel0_fountain_jets: bpy.props.IntProperty(  # pyright: ignore
        name="Pyro 1 jets", description="Number of fountain jets", min=1, max=32, default=12, update=update_fire_preview,
    )
    fire_preview_channel0_fountain_particles: bpy.props.IntProperty(  # pyright: ignore
        name="Pyro 1 density", description="Number of visible fountain particles per emission budget", min=10, max=500, default=120, update=update_fire_preview,
    )
    fire_preview_channel0_fountain_velocity: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 1 velocity", description="Initial fountain particle speed", min=0.2, max=30.0, default=8.0, update=update_fire_preview,
    )
    fire_preview_channel0_fountain_spread: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 1 spread", description="Fountain angular spread in degrees", subtype="ANGLE", min=0.0, max=1.570796, default=0.6108652381980153, update=update_fire_preview,
    )
    fire_preview_channel0_fountain_trail: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 1 trail", description="Fountain trail lifetime in seconds", min=0.0, max=2.0, default=0.28, update=update_fire_preview,
    )
    fire_preview_channel0_fountain_direction: bpy.props.FloatVectorProperty(  # pyright: ignore
        name="Pyro 1 diffusion direction",
        description="Local diffusion axis for fountain/cascade. Default is downward Z-.",
        subtype="DIRECTION", size=3, min=-1.0, max=1.0,
        default=(0.0, 0.0, -1.0), update=update_fire_preview,
    )
    fire_preview_channel0_crackle_stars: bpy.props.IntProperty(  # pyright: ignore
        name="Pyro 1 stars", description="Number of crackling stars", min=4, max=500, default=80, update=update_fire_preview,
    )
    fire_preview_channel0_crackle_velocity: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 1 burst speed", description="Initial crackling burst speed", min=0.2, max=30.0, default=7.0, update=update_fire_preview,
    )
    fire_preview_channel0_crackle_spread: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 1 radius", description="Crackling burst radius multiplier", min=0.1, max=10.0, default=1.5, update=update_fire_preview,
    )
    fire_preview_channel0_crackle_gravity: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 1 gravity", description="Crackling gravity in m/s²", min=0.0, max=40.0, default=7.5, update=update_fire_preview,
    )
    fire_preview_channel0_crackle_branches: bpy.props.IntProperty(  # pyright: ignore
        name="Pyro 1 crackles", description="Secondary crackle branches per burst", min=0, max=12, default=3, update=update_fire_preview,
    )
    fire_preview_channel0_crackle_branch_length: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 1 branch", description="Secondary crackle branch length", min=0.0, max=2.0, default=0.38, update=update_fire_preview,
    )
    fire_preview_channel0_crackle_trail: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 1 trail", description="Crackling trail lifetime in seconds", min=0.0, max=1.0, default=0.16, update=update_fire_preview,
    )
    fire_preview_channel0_smoke_puffs: bpy.props.IntProperty(  # pyright: ignore
        name="Pyro 1 puffs", description="Number of smoke puffs", min=2, max=60, default=16, update=update_fire_preview,
    )
    fire_preview_channel0_smoke_rise: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 1 rise speed", description="Smoke rise speed", min=0.0, max=15.0, default=1.4, update=update_fire_preview,
    )
    fire_preview_channel0_smoke_expansion: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 1 expansion", description="Horizontal smoke expansion", min=0.0, max=5.0, default=1.0, update=update_fire_preview,
    )
    fire_preview_channel0_smoke_turbulence: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 1 turbulence", description="Smoke turbulence amount", min=0.0, max=3.0, default=0.45, update=update_fire_preview,
    )
    fire_preview_channel0_smoke_dissipation: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 1 dissipation", description="Smoke fade rate", min=0.1, max=5.0, default=1.0, update=update_fire_preview,
    )
    fire_preview_channel0_smoke_opacity: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 1 opacity", description="Maximum smoke opacity", min=0.05, max=1.0, default=0.72, update=update_fire_preview,
    )
    fire_preview_channel0_smoke_mesh_resolution: bpy.props.IntProperty(  # pyright: ignore
        name="Pyro 1 mesh definition",
        description="Low to high polygon definition of smoke puffs", min=6, max=24, default=10, update=update_fire_preview,
    )
    fire_preview_channel0_falling_stars: bpy.props.IntProperty(  # pyright: ignore
        name="Pyro 1 stars", description="Number of falling stars", min=3, max=300, default=36, update=update_fire_preview,
    )
    fire_preview_channel0_falling_velocity: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 1 velocity", description="Initial falling-star speed", min=0.2, max=30.0, default=7.0, update=update_fire_preview,
    )
    fire_preview_channel0_falling_spread: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 1 spread", description="Falling-star spread angle", subtype="ANGLE", min=0.0, max=1.570796, default=0.6632251157578452, update=update_fire_preview,
    )
    fire_preview_channel0_falling_gravity: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 1 gravity", description="Falling-star gravity in m/s²", min=0.0, max=40.0, default=9.0, update=update_fire_preview,
    )
    fire_preview_channel0_falling_trail: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 1 trail", description="Falling-star trail length", min=0.0, max=2.0, default=0.42, update=update_fire_preview,
    )
    fire_preview_channel0_falling_twinkle: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 1 twinkle", description="Falling-star brightness variation", min=0.0, max=1.0, default=0.5, update=update_fire_preview,
    )
    fire_preview_channel1_lifetime: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 2 lifetime", description="Lifetime of individual pyrotechnic particles or smoke puffs", subtype="TIME_ABSOLUTE", min=0.05, max=60.0, default=1.6, update=update_fire_preview,
    )
    fire_preview_channel1_intensity: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 2 intensity", description="Preview brightness multiplier", min=0.1, max=20.0, default=2.2, update=update_fire_preview,
    )
    fire_preview_channel1_gpu_particle_size: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 2 particle size",
        description="GPU preview particle diameter in viewport pixels",
        min=1.0, max=48.0, default=9.0,
        update=update_fire_preview,
    )
    fire_preview_channel1_gpu_glow: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 2 glow",
        description="GPU preview glow halo strength",
        min=0.0, max=4.0, default=1.0,
        update=update_fire_preview,
    )
    fire_preview_channel1_gravity: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 2 gravity", description="Preview gravity in m/s²", min=0.0, max=40.0, default=9.81, update=update_fire_preview,
    )
    fire_preview_channel1_fountain_jets: bpy.props.IntProperty(  # pyright: ignore
        name="Pyro 2 jets", description="Number of fountain jets", min=1, max=32, default=12, update=update_fire_preview,
    )
    fire_preview_channel1_fountain_particles: bpy.props.IntProperty(  # pyright: ignore
        name="Pyro 2 density", description="Number of visible fountain particles per emission budget", min=10, max=500, default=120, update=update_fire_preview,
    )
    fire_preview_channel1_fountain_velocity: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 2 velocity", description="Initial fountain particle speed", min=0.2, max=30.0, default=8.0, update=update_fire_preview,
    )
    fire_preview_channel1_fountain_spread: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 2 spread", description="Fountain angular spread in degrees", subtype="ANGLE", min=0.0, max=1.570796, default=0.6108652381980153, update=update_fire_preview,
    )
    fire_preview_channel1_fountain_trail: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 2 trail", description="Fountain trail lifetime in seconds", min=0.0, max=2.0, default=0.28, update=update_fire_preview,
    )
    fire_preview_channel1_fountain_direction: bpy.props.FloatVectorProperty(  # pyright: ignore
        name="Pyro 2 diffusion direction",
        description="Local diffusion axis for fountain/cascade. Default is downward Z-.",
        subtype="DIRECTION", size=3, min=-1.0, max=1.0,
        default=(0.0, 0.0, -1.0), update=update_fire_preview,
    )
    fire_preview_channel1_crackle_stars: bpy.props.IntProperty(  # pyright: ignore
        name="Pyro 2 stars", description="Number of crackling stars", min=4, max=500, default=80, update=update_fire_preview,
    )
    fire_preview_channel1_crackle_velocity: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 2 burst speed", description="Initial crackling burst speed", min=0.2, max=30.0, default=7.0, update=update_fire_preview,
    )
    fire_preview_channel1_crackle_spread: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 2 radius", description="Crackling burst radius multiplier", min=0.1, max=10.0, default=1.5, update=update_fire_preview,
    )
    fire_preview_channel1_crackle_gravity: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 2 gravity", description="Crackling gravity in m/s²", min=0.0, max=40.0, default=7.5, update=update_fire_preview,
    )
    fire_preview_channel1_crackle_branches: bpy.props.IntProperty(  # pyright: ignore
        name="Pyro 2 crackles", description="Secondary crackle branches per burst", min=0, max=12, default=3, update=update_fire_preview,
    )
    fire_preview_channel1_crackle_branch_length: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 2 branch", description="Secondary crackle branch length", min=0.0, max=2.0, default=0.38, update=update_fire_preview,
    )
    fire_preview_channel1_crackle_trail: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 2 trail", description="Crackling trail lifetime in seconds", min=0.0, max=1.0, default=0.16, update=update_fire_preview,
    )
    fire_preview_channel1_smoke_puffs: bpy.props.IntProperty(  # pyright: ignore
        name="Pyro 2 puffs", description="Number of smoke puffs", min=2, max=60, default=16, update=update_fire_preview,
    )
    fire_preview_channel1_smoke_rise: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 2 rise speed", description="Smoke rise speed", min=0.0, max=15.0, default=1.4, update=update_fire_preview,
    )
    fire_preview_channel1_smoke_expansion: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 2 expansion", description="Horizontal smoke expansion", min=0.0, max=5.0, default=1.0, update=update_fire_preview,
    )
    fire_preview_channel1_smoke_turbulence: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 2 turbulence", description="Smoke turbulence amount", min=0.0, max=3.0, default=0.45, update=update_fire_preview,
    )
    fire_preview_channel1_smoke_dissipation: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 2 dissipation", description="Smoke fade rate", min=0.1, max=5.0, default=1.0, update=update_fire_preview,
    )
    fire_preview_channel1_smoke_opacity: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 2 opacity", description="Maximum smoke opacity", min=0.05, max=1.0, default=0.72, update=update_fire_preview,
    )
    fire_preview_channel1_smoke_mesh_resolution: bpy.props.IntProperty(  # pyright: ignore
        name="Pyro 2 mesh definition",
        description="Low to high polygon definition of smoke puffs", min=6, max=24, default=10, update=update_fire_preview,
    )
    fire_preview_channel1_falling_stars: bpy.props.IntProperty(  # pyright: ignore
        name="Pyro 2 stars", description="Number of falling stars", min=3, max=300, default=36, update=update_fire_preview,
    )
    fire_preview_channel1_falling_velocity: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 2 velocity", description="Initial falling-star speed", min=0.2, max=30.0, default=7.0, update=update_fire_preview,
    )
    fire_preview_channel1_falling_spread: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 2 spread", description="Falling-star spread angle", subtype="ANGLE", min=0.0, max=1.570796, default=0.6632251157578452, update=update_fire_preview,
    )
    fire_preview_channel1_falling_gravity: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 2 gravity", description="Falling-star gravity in m/s²", min=0.0, max=40.0, default=9.0, update=update_fire_preview,
    )
    fire_preview_channel1_falling_trail: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 2 trail", description="Falling-star trail length", min=0.0, max=2.0, default=0.42, update=update_fire_preview,
    )
    fire_preview_channel1_falling_twinkle: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 2 twinkle", description="Falling-star brightness variation", min=0.0, max=1.0, default=0.5, update=update_fire_preview,
    )
    fire_preview_channel2_lifetime: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 3 lifetime", description="Lifetime of individual pyrotechnic particles or smoke puffs", subtype="TIME_ABSOLUTE", min=0.05, max=60.0, default=3.5, update=update_fire_preview,
    )
    fire_preview_channel2_intensity: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 3 intensity", description="Preview brightness multiplier", min=0.1, max=20.0, default=1.6, update=update_fire_preview,
    )
    fire_preview_channel2_gpu_particle_size: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 3 particle size",
        description="GPU preview particle diameter in viewport pixels",
        min=1.0, max=48.0, default=9.0,
        update=update_fire_preview,
    )
    fire_preview_channel2_gpu_glow: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 3 glow",
        description="GPU preview glow halo strength",
        min=0.0, max=4.0, default=1.0,
        update=update_fire_preview,
    )
    fire_preview_channel2_gravity: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 3 gravity", description="Preview gravity in m/s²", min=0.0, max=40.0, default=9.81, update=update_fire_preview,
    )
    fire_preview_channel2_fountain_jets: bpy.props.IntProperty(  # pyright: ignore
        name="Pyro 3 jets", description="Number of fountain jets", min=1, max=32, default=12, update=update_fire_preview,
    )
    fire_preview_channel2_fountain_particles: bpy.props.IntProperty(  # pyright: ignore
        name="Pyro 3 density", description="Number of visible fountain particles per emission budget", min=10, max=500, default=120, update=update_fire_preview,
    )
    fire_preview_channel2_fountain_velocity: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 3 velocity", description="Initial fountain particle speed", min=0.2, max=30.0, default=8.0, update=update_fire_preview,
    )
    fire_preview_channel2_fountain_spread: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 3 spread", description="Fountain angular spread in degrees", subtype="ANGLE", min=0.0, max=1.570796, default=0.6108652381980153, update=update_fire_preview,
    )
    fire_preview_channel2_fountain_trail: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 3 trail", description="Fountain trail lifetime in seconds", min=0.0, max=2.0, default=0.28, update=update_fire_preview,
    )
    fire_preview_channel2_fountain_direction: bpy.props.FloatVectorProperty(  # pyright: ignore
        name="Pyro 3 diffusion direction",
        description="Local diffusion axis for fountain/cascade. Default is downward Z-.",
        subtype="DIRECTION", size=3, min=-1.0, max=1.0,
        default=(0.0, 0.0, -1.0), update=update_fire_preview,
    )
    fire_preview_channel2_crackle_stars: bpy.props.IntProperty(  # pyright: ignore
        name="Pyro 3 stars", description="Number of crackling stars", min=4, max=500, default=80, update=update_fire_preview,
    )
    fire_preview_channel2_crackle_velocity: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 3 burst speed", description="Initial crackling burst speed", min=0.2, max=30.0, default=7.0, update=update_fire_preview,
    )
    fire_preview_channel2_crackle_spread: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 3 radius", description="Crackling burst radius multiplier", min=0.1, max=10.0, default=1.5, update=update_fire_preview,
    )
    fire_preview_channel2_crackle_gravity: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 3 gravity", description="Crackling gravity in m/s²", min=0.0, max=40.0, default=7.5, update=update_fire_preview,
    )
    fire_preview_channel2_crackle_branches: bpy.props.IntProperty(  # pyright: ignore
        name="Pyro 3 crackles", description="Secondary crackle branches per burst", min=0, max=12, default=3, update=update_fire_preview,
    )
    fire_preview_channel2_crackle_branch_length: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 3 branch", description="Secondary crackle branch length", min=0.0, max=2.0, default=0.38, update=update_fire_preview,
    )
    fire_preview_channel2_crackle_trail: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 3 trail", description="Crackling trail lifetime in seconds", min=0.0, max=1.0, default=0.16, update=update_fire_preview,
    )
    fire_preview_channel2_smoke_puffs: bpy.props.IntProperty(  # pyright: ignore
        name="Pyro 3 puffs", description="Number of smoke puffs", min=2, max=60, default=16, update=update_fire_preview,
    )
    fire_preview_channel2_smoke_rise: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 3 rise speed", description="Smoke rise speed", min=0.0, max=15.0, default=1.4, update=update_fire_preview,
    )
    fire_preview_channel2_smoke_expansion: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 3 expansion", description="Horizontal smoke expansion", min=0.0, max=5.0, default=1.0, update=update_fire_preview,
    )
    fire_preview_channel2_smoke_turbulence: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 3 turbulence", description="Smoke turbulence amount", min=0.0, max=3.0, default=0.45, update=update_fire_preview,
    )
    fire_preview_channel2_smoke_dissipation: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 3 dissipation", description="Smoke fade rate", min=0.1, max=5.0, default=1.0, update=update_fire_preview,
    )
    fire_preview_channel2_smoke_opacity: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 3 opacity", description="Maximum smoke opacity", min=0.05, max=1.0, default=0.72, update=update_fire_preview,
    )
    fire_preview_channel2_smoke_mesh_resolution: bpy.props.IntProperty(  # pyright: ignore
        name="Pyro 3 mesh definition",
        description="Low to high polygon definition of smoke puffs", min=6, max=24, default=10, update=update_fire_preview,
    )
    fire_preview_channel2_falling_stars: bpy.props.IntProperty(  # pyright: ignore
        name="Pyro 3 stars", description="Number of falling stars", min=3, max=300, default=36, update=update_fire_preview,
    )
    fire_preview_channel2_falling_velocity: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 3 velocity", description="Initial falling-star speed", min=0.2, max=30.0, default=7.0, update=update_fire_preview,
    )
    fire_preview_channel2_falling_spread: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 3 spread", description="Falling-star spread angle", subtype="ANGLE", min=0.0, max=1.570796, default=0.6632251157578452, update=update_fire_preview,
    )
    fire_preview_channel2_falling_gravity: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 3 gravity", description="Falling-star gravity in m/s²", min=0.0, max=40.0, default=9.0, update=update_fire_preview,
    )
    fire_preview_channel2_falling_trail: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 3 trail", description="Falling-star trail length", min=0.0, max=2.0, default=0.42, update=update_fire_preview,
    )
    fire_preview_channel2_falling_twinkle: bpy.props.FloatProperty(  # pyright: ignore
        name="Pyro 3 twinkle", description="Falling-star brightness variation", min=0.0, max=1.0, default=0.5, update=update_fire_preview,
    )
    collision_distance: bpy.props.FloatProperty(  # pyright: ignore
        name="Min distance",
        description="The minimal distance between drones",
        subtype="DISTANCE",
        min=PHYSIC_PARAMETERS_MAX.minimum_distance,
        soft_min=PHYSIC_PARAMETERS_MAX.minimum_distance,
        default=PHYSIC_PARAMETERS_RECOMMENDATION.minimum_distance,
        update=update_proximity_warning_lines,
    )
    takeoff_altitude: bpy.props.FloatProperty(  # pyright: ignore
        name="Takeoff alt",
        description="The takeoff altitude",
        subtype="DISTANCE",
        default=TAKEOFF_PARAMETERS.takeoff_altitude_meter_min + 0.01,
        min=TAKEOFF_PARAMETERS.takeoff_altitude_meter_min + 0.01,
        soft_min=TAKEOFF_PARAMETERS.takeoff_altitude_meter_min + 0.01,
        max=TAKEOFF_PARAMETERS.takeoff_altitude_meter_max,
        soft_max=TAKEOFF_PARAMETERS.takeoff_altitude_meter_max,
    )
    angle_export: bpy.props.FloatProperty(  # pyright: ignore
        name="Export angle",
        description="""\
The show is rotated by this angle before exporting
When modifying the show, you should set this angle to 0""",
        subtype="ANGLE",
        default=0,
        precision=0,
        update=update_drone,
    )
    scale_export: bpy.props.IntProperty(  # pyright: ignore
        name="Scale",
        description="""\
The scale multiply the initial range of the show (-327, 327) by this value
The initial position precision of 1 cm is multiplied by this value
This value should not be changed if the show fits in the initial range""",
        min=1,
        soft_min=1,
        max=4,
        soft_max=4,
        default=1,
    )
    magic_number: bpy.props.EnumProperty(  # pyright: ignore
        name="Export version",
        description="The minimal version of the autopilot to use for the export",
        items=[
            (
                "V1",
                "v1",
                """\
Both IO Star 1 and IO Star 2 are supported.
The format is optimized in size.
The color has a real interpolation during transitions.
Minimal drone autopilot version: v2.6.0.""",
                1,
            ),
            (
                "V2",
                "v2",
                """\
Only IO Star 2 is supported.
This version add the possibility to use the scale and the land type.""",
                2,
            ),
        ],
        default="V1",
    )
    effector_intensity: bpy.props.FloatProperty(  # pyright: ignore
        name="Intensity",
        description="The fading intensity (how luminous the effector is)",
        min=0.0,
        soft_min=0.0,
        default=1.0,
    )
    effector_frame_rate: bpy.props.IntProperty(  # pyright: ignore
        name="Frame step",
        description="The number of frames between random color changes",
        min=1,
        soft_min=1,
        default=1,
    )
    effector_priority: bpy.props.FloatProperty(  # pyright: ignore
        name="Priority",
        description="The priority of the effector",
        min=0.0,
        soft_min=0.0,
        default=1.0,
    )
    baking_frame_step: bpy.props.IntProperty(  # pyright: ignore
        name="Frame step",
        description="The number of frames between color keyframes when registering",
        min=1,
        soft_min=1,
        default=2,
    )
    effector_name: bpy.props.EnumProperty(  # pyright: ignore
        name="Name",
        description="The name of the effector to use",
        items=execute_operator,
    )
    effector_type: bpy.props.EnumProperty(  # pyright: ignore
        name="Type",
        description="The type of the effector",
        items=[
            ("FIXED", "Fixed", "The drones inside the effector take its color", 0),
            (
                "RANDOM",
                "Random",
                "The drones inside the effector randomly take one of its color",
                1,
            ),
            (
                "FADED",
                "Faded",
                "The drones will take on the color of the effector the nearer they are",
                2,
            ),
        ],
        default="FIXED",
    )
    baking_interpolation: bpy.props.EnumProperty(  # pyright: ignore
        name="Interpolation",
        description="The interpolation to use for the keyframes during the registration",
        items=INTERPOLATION,
        default="LINEAR",
    )
    used_characters: bpy.props.StringProperty(  # pyright: ignore
        name="Text", description="The mesh text to create", default=""
    )
    nb_drones_text: bpy.props.IntProperty(  # pyright: ignore
        name="Nb drone mesh text",
        description="The number of drones to represent the mesh text",
        min=1,
        soft_min=1,
        max=1000,
        soft_max=1000,
        default=1,
    )
    text_font: bpy.props.StringProperty(  # pyright: ignore
        name="Font",
        description="The font to use for the mesh text (.ttf or .otf)",
        default="",
        subtype="FILE_PATH",
    )
    vel_hor_max: bpy.props.FloatProperty(  # pyright: ignore
        name="Velocity Horizontal Maximal",
        description="The maximal horizontal velocity of the drones",
        unit="VELOCITY",
        min=0.0,
        soft_min=0.0,
        max=PHYSIC_PARAMETERS_MAX.horizontal_velocity_max,
        soft_max=PHYSIC_PARAMETERS_MAX.horizontal_velocity_max,
        default=PHYSIC_PARAMETERS_RECOMMENDATION.horizontal_velocity_max,
    )
    vel_up_max: bpy.props.FloatProperty(  # pyright: ignore
        name="Velocity Up Maximal",
        description="The maximal vertical up velocity of the drones",
        unit="VELOCITY",
        min=0.0,
        soft_min=0.0,
        max=PHYSIC_PARAMETERS_MAX.velocity_up_max,
        soft_max=PHYSIC_PARAMETERS_MAX.velocity_up_max,
        default=PHYSIC_PARAMETERS_RECOMMENDATION.velocity_up_max,
    )
    vel_down_max: bpy.props.FloatProperty(  # pyright: ignore
        name="Velocity Down Maximal",
        description="The maximal vertical down velocity of the drones",
        unit="VELOCITY",
        min=0.0,
        soft_min=0.0,
        max=PHYSIC_PARAMETERS_MAX.velocity_down_max,
        soft_max=PHYSIC_PARAMETERS_MAX.velocity_down_max,
        default=PHYSIC_PARAMETERS_RECOMMENDATION.velocity_down_max,
    )
    acc_max: bpy.props.FloatProperty(  # pyright: ignore
        name="Acceleration Maximal",
        description="The maximal acceleration of the drones",
        unit="ACCELERATION",
        min=0.0,
        soft_min=0.0,
        max=PHYSIC_PARAMETERS_MAX.acceleration_max,
        soft_max=PHYSIC_PARAMETERS_MAX.acceleration_max,
        default=PHYSIC_PARAMETERS_RECOMMENDATION.acceleration_max,
    )
    emission_strength: bpy.props.FloatProperty(  # pyright: ignore
        name="Intensité simulation",
        description="Intensité visuelle du viewport et du rendu Blender uniquement. N'affecte jamais les données RGBW du show ni l'export.",
        min=0.0,
        soft_min=0.0,
        max=50.0,
        soft_max=10.0,
        default=5.0,
        precision=2,
        update=update_emission_strength,
    )
    takeoff_keyframe: bpy.props.EnumProperty(  # pyright: ignore
        name="Takeoff",
        description="The type of keyframe to use for the takeoff",
        items=KEYFRAME_TYPE,
        default="EXTREME",
        update=update_property_factory("takeoff_keyframe"),
    )
    land_keyframe: bpy.props.EnumProperty(  # pyright: ignore
        name="Land",
        description="The type of keyframe to use for the land",
        items=KEYFRAME_TYPE,
        default="EXTREME",
        update=update_property_factory("land_keyframe"),
    )
    go_to_target_keyframe: bpy.props.EnumProperty(  # pyright: ignore
        name="Go to target",
        description="The type of keyframe to use for the go to target",
        items=KEYFRAME_TYPE,
        default="BREAKDOWN",
        update=update_property_factory("go_to_target_keyframe"),
    )
    set_color_keyframe: bpy.props.EnumProperty(  # pyright: ignore
        name="Set color",
        description="The type of keyframe to use for the set color",
        items=KEYFRAME_TYPE,
        default="JITTER",
        update=update_property_factory("set_color_keyframe"),
    )
    magic_color_keyframe: bpy.props.EnumProperty(  # pyright: ignore
        name="Magic color",
        description="The type of keyframe to use for the magic color",
        items=KEYFRAME_TYPE,
        default="JITTER",
        update=update_property_factory("magic_color_keyframe"),
    )
    fire_keyframe: bpy.props.EnumProperty(  # pyright: ignore
        name="Fire",
        description="The type of keyframe to use for the fire",
        items=KEYFRAME_TYPE,
        default="MOVING_HOLD",
        update=update_property_factory("fire_keyframe"),
    )
    old_takeoff_keyframe: bpy.props.EnumProperty(  # pyright: ignore
        name="Takeoff",
        description="The old type of keyframe to use for the takeoff",
        items=KEYFRAME_TYPE,
        default="EXTREME",
    )
    old_land_keyframe: bpy.props.EnumProperty(  # pyright: ignore
        name="Land",
        description="The old type of keyframe to use for the land",
        items=KEYFRAME_TYPE,
        default="EXTREME",
    )
    old_go_to_target_keyframe: bpy.props.EnumProperty(  # pyright: ignore
        name="Go to target",
        description="The old type of keyframe to use for the go to target",
        items=KEYFRAME_TYPE,
        default="BREAKDOWN",
    )
    old_set_color_keyframe: bpy.props.EnumProperty(  # pyright: ignore
        name="Set color",
        description="The old type of keyframe to use for the set color",
        items=KEYFRAME_TYPE,
        default="JITTER",
    )
    old_magic_color_keyframe: bpy.props.EnumProperty(  # pyright: ignore
        name="Magic color",
        description="The old type of keyframe to use for the magic color",
        items=KEYFRAME_TYPE,
        default="JITTER",
    )
    old_fire_keyframe: bpy.props.EnumProperty(  # pyright: ignore
        name="Fire",
        description="The old type of keyframe to use for the fire",
        items=KEYFRAME_TYPE,
        default="MOVING_HOLD",
    )
    takeoff_marker: bpy.props.BoolProperty(  # pyright: ignore
        name="Takeoff marker",
        description="Enable or disable automatic takeoff marker creation",
        default=True,
    )
    land_marker: bpy.props.BoolProperty(  # pyright: ignore
        name="Land marker",
        description="Enable or disable automatic land marker creation",
        default=True,
    )
    go_to_target_marker: bpy.props.BoolProperty(  # pyright: ignore
        name="Go to target marker",
        description="Enable or disable automatic go to target marker creation",
        default=True,
    )
    set_color_marker: bpy.props.BoolProperty(  # pyright: ignore
        name="Set color marker",
        description="Enable or disable automatic set color marker creation",
        default=True,
    )
    magic_color_marker: bpy.props.BoolProperty(  # pyright: ignore
        name="Magic color marker",
        description="Enable or disable automatic magic color marker creation",
        default=True,
    )
    fire_marker: bpy.props.BoolProperty(  # pyright: ignore
        name="Fire marker",
        description="Enable or disable automatic fire marker creation",
        default=True,
    )
    follow_path_duration: bpy.props.FloatProperty(  # pyright: ignore
        name="Duration",
        description="The duration of the follow path animation",
        subtype="TIME_ABSOLUTE",
        min=0,
        soft_min=0,
        default=0,
    )
    follow_path_time_delta: bpy.props.FloatProperty(  # pyright: ignore
        name="Time delta",
        description="The time delta of the follow path animation",
        subtype="TIME_ABSOLUTE",
        min=0,
        soft_min=0,
        default=0,
    )
    follow_path_nb_anchors: bpy.props.IntProperty(  # pyright: ignore
        name="Nb anchors",
        description="The number of anchors of the follow path animation",
        min=0,
        soft_min=0,
        default=0,
    )
    dev_mode: bpy.props.BoolProperty(  # pyright: ignore
        name="Dev mode",
        description="Enable or disable the dev mode",
        default=False,
    )
    export_with_yaw: bpy.props.BoolProperty(  # pyright: ignore
        name="With yaw",
        description="Enable or disable the export with drone yaw",
        default=False,
    )
    takeoff_end_frame: bpy.props.IntProperty(  # pyright: ignore
        name="Takeoff end frame",
        description="The end frame of the takeoff",
        default=-1,
    )
    rtl_start_frame: bpy.props.IntProperty(  # pyright: ignore
        name="RTL start frame",
        description="The start frame of the RTL",
        default=-1,
    )
    rtl_land_altitude: bpy.props.FloatProperty(  # pyright: ignore
        name="RTL landing altitude",
        description="Altitude at which drones reach their original launch XY before the final landing",
        subtype="DISTANCE",
        min=0.1,
        soft_min=1.0,
        default=2.0,
    )
    rtl_min_distance: bpy.props.FloatProperty(  # pyright: ignore
        name="RTL minimum distance",
        description="Minimum 3-D distance to preserve between drones during RTL",
        subtype="DISTANCE",
        min=PHYSIC_PARAMETERS_MAX.minimum_distance,
        soft_min=PHYSIC_PARAMETERS_MAX.minimum_distance,
        default=PHYSIC_PARAMETERS_RECOMMENDATION.minimum_distance,
    )
    rtl_reposition_duration: bpy.props.FloatProperty(  # pyright: ignore
        name="RTL reposition duration",
        description="Time spent at the original launch XY before the final landing sequence",
        subtype="TIME_ABSOLUTE",
        min=0.0,
        soft_min=1.0,
        default=1.0,
    )
    rtl_speed: bpy.props.FloatProperty(  # pyright: ignore
        name="RTL cruise speed",
        description="Maximum horizontal/vertical cruise speed used by the RTL planner",
        unit="VELOCITY",
        min=0.1,
        soft_min=1.0,
        max=PHYSIC_PARAMETERS_MAX.velocity_down_max,
        soft_max=PHYSIC_PARAMETERS_MAX.velocity_down_max,
        default=2.0,
    )
    rtl_min_cruise_percent: bpy.props.FloatProperty(  # pyright: ignore
        name="RTL minimum cruise speed (%) [legacy]",
        description="Legacy compatibility field. Synchronized RTL now chooses the required speed range automatically and ignores this value.",
        subtype="PERCENTAGE",
        min=20.0,
        soft_min=40.0,
        max=100.0,
        soft_max=100.0,
        default=55.0,
        options={"HIDDEN"},
    )
    rtl_synchronized_departure: bpy.props.BoolProperty(  # pyright: ignore
        name="Synchronized departure",
        description="Force every drone to start RTL on the same frame. Collision avoidance is performed by varying each drone's cruise speed; if the geometry cannot be resolved safely, RTL stops instead of staggering the departure.",
        default=True,
    )
    rtl_frame_delta: bpy.props.IntProperty(  # pyright: ignore
        name="RTL frame interval",
        description="Frame interval between drone RTL starts. Higher values calculate faster but schedule coarser timing",
        subtype="TIME",
        min=1,
        soft_min=6,
        default=6,
    )
    disable_magic_color: bpy.props.BoolProperty(  # pyright: ignore
        name="Disable magic color",
        description="Disable the magic color, this is useful for the color baking",
        default=False,
    )
    bypass_export_checks: bpy.props.BoolProperty(  # pyright: ignore
        name="Bypass export checks",
        description="Bypass the export checks",
        default=False,
    )
    takeoff_mode: bpy.props.EnumProperty(  # pyright: ignore
        name="Takeoff mode",
        description="Takeoff used method",
        items=[
            (
                "standard_takeoff",
                "Standard",
                "Placing drones on the ground, grouped or not by family and respecting security distances",
            ),
            (
                "using all in one platform",
                "All in one platform",
                "Using the platforms to takeoff drones, platforms are placed gathered on the ground",
            ),
        ],
        default="standard_takeoff",
        update=update_takeoff_mode,
    )
    installation_gap: bpy.props.EnumProperty(  # pyright: ignore
        name="Installation gap",
        description="Choose between Column or Line",
        items=[
            ("COLUMN", "Column", "Keep space between drones in the same column"),
            ("LINE", "Line", "Keep space between drones in the same line"),
        ],
        default="COLUMN",
        update=update_takeoff_mode,
    )
    enable_proximity_warning: bpy.props.BoolProperty(  # pyright: ignore
        name="Proximity lines",
        description="Enable or disable the proximity warning lines",
        default=False,
        update=update_proximity_warning_lines,
    )
    proximity_line_collection: bpy.props.PointerProperty(  # pyright: ignore
        name="Proximity Line Collection",
        type=bpy.types.Collection,
        description="Collection for proximity warning lines",
    )
    proximity_line_object: bpy.props.PointerProperty(  # pyright: ignore
        name="Proximity Line Object",
        type=bpy.types.Object,
        description="Object for proximity warning lines",
        update=update_proximity_warning_lines,
    )
    mesh_converter_object: bpy.props.PointerProperty(  # pyright: ignore
        name="Object",
        type=bpy.types.Object,
        description="Object for the mesh converter",
    )
    mesh_converter_static_object: bpy.props.PointerProperty(  # pyright: ignore
        name="Static Object",
        type=bpy.types.Object,
        description="Static object for the mesh converter",
        update=update_mesh_converter_node,
    )
    mesh_converter_distance: bpy.props.FloatProperty(  # pyright: ignore
        name="Distance",
        description="Distance for the mesh converter",
        subtype="DISTANCE",
        min=0,
        soft_min=0.1,
        default=1.5,
        update=update_mesh_converter_node,
    )
    mesh_converter_seed: bpy.props.IntProperty(  # pyright: ignore
        name="Seed",
        description="Seed for the mesh converter",
        default=0,
        update=update_mesh_converter_node,
    )
    mesh_converter_is_rigged: bpy.props.BoolProperty(  # pyright: ignore
        name="Is rigged",
        description="Is the mesh converter rigged",
        default=False,
        update=update_mesh_converter_node,
    )


def get_lightshow(scene: bpy.types.Scene) -> "Lightshow":
    return scene.lightshow  # pyright: ignore


def get_physic_parameters(lightshow: "Lightshow") -> IostarPhysicParameters:
    # TODO(jonathan): use the same name everywhere
    return IostarPhysicParameters(
        velocity_up_max=lightshow.vel_up_max,
        velocity_down_max=lightshow.vel_down_max,
        horizontal_velocity_max=lightshow.vel_hor_max,
        acceleration_max=lightshow.acc_max,
        minimum_distance=lightshow.collision_distance,
    )


def set_physic_parameters(
    lightshow: "Lightshow", physic_parameters: IostarPhysicParameters
) -> None:
    lightshow.vel_up_max = physic_parameters.velocity_up_max
    lightshow.vel_down_max = physic_parameters.velocity_down_max
    lightshow.vel_hor_max = physic_parameters.horizontal_velocity_max
    lightshow.acc_max = physic_parameters.acceleration_max
    lightshow.collision_distance = physic_parameters.minimum_distance


def get_metadata() -> Metadata:
    return Metadata(
        sparkshow_creator_version=".".join(map(str, bl_info["version"])),
        blender_version=bpy.app.version_string,
    )


if TYPE_CHECKING:
    DurationMode = Literal["MANUAL", "OPTIMAL"]
    TransitionMode = Literal["TOGETHER", "STAGGERED"]
    MeshImageMode = Literal["Fast", "Balanced"]
    MeshTextMode = Literal["Fast", "Balanced"]
    MagicNumber = Literal["V1", "V2"]
    EffectorType = Literal["FIXED", "RANDOM", "FADED"]
    TakeoffMode = Literal["standard_takeoff", "using all in one platform"]
    InstallationGap = Literal["COLUMN", "LINE"]
    KeyframeType = Literal["KEYFRAME", "BREAKDOWN", "MOVING_HOLD", "EXTREME", "JITTER"]
    Interpolation = Literal["CONSTANT", "LINEAR", "BEZIER"]

    class Lightshow(bpy.types.AnyType):
        nb_drones: int
        old_nb_drones: int
        drone_repartition_index: int
        nb_x: int
        nb_y: int
        nb_drones_per_family: int
        step: float
        step_x: float
        step_y: float
        angle_takeoff: float
        old_nb_x: int
        old_nb_y: int
        old_step_x: float
        old_step_y: float
        old_angle_takeoff: float
        color: tuple[float, float, float, float]
        new_color: tuple[float, float, float, float]
        color_duration: float
        brightness: float
        duration_mode: DurationMode
        formation_duration: float
        transition_mode: TransitionMode
        staggered_frame_step: int
        min_anchors_distance: float
        interpolation: Interpolation
        mesh_image_mode: MeshImageMode
        mesh_text_mode: MeshTextMode
        adjustment: float
        selected_mesh: str
        nb_vertices: int
        fire_duration: float
        fire_vdl: str
        fire_preview_enabled: bool
        fire_preview_light_mode: bool
        fire_pyro_bake_step: int
        fire_preview_fire0_pyro: str
        fire_preview_fire1_pyro: str
        fire_preview_fire2_pyro: str
        fire_preview_channel0_effect: str
        fire_preview_channel0_color: tuple[float, float, float, float]
        fire_preview_channel0_duration: float
        fire_preview_channel0_size: float
        fire_preview_channel1_effect: str
        fire_preview_channel1_color: tuple[float, float, float, float]
        fire_preview_channel1_duration: float
        fire_preview_channel1_size: float
        fire_preview_channel2_effect: str
        fire_preview_channel2_color: tuple[float, float, float, float]
        fire_preview_channel2_duration: float
        fire_preview_channel2_size: float
        fire_preview_channel0_intensity: float
        fire_preview_channel0_gpu_particle_size: float
        fire_preview_channel0_gpu_glow: float
        fire_preview_channel0_gravity: float
        fire_preview_channel0_fountain_jets: int
        fire_preview_channel0_fountain_particles: int
        fire_preview_channel0_fountain_velocity: float
        fire_preview_channel0_fountain_spread: float
        fire_preview_channel0_fountain_trail: float
        fire_preview_channel0_fountain_direction: tuple[float, float, float]
        fire_preview_channel0_crackle_stars: int
        fire_preview_channel0_crackle_velocity: float
        fire_preview_channel0_crackle_spread: float
        fire_preview_channel0_crackle_gravity: float
        fire_preview_channel0_crackle_branches: int
        fire_preview_channel0_crackle_branch_length: float
        fire_preview_channel0_crackle_trail: float
        fire_preview_channel0_smoke_puffs: int
        fire_preview_channel0_smoke_rise: float
        fire_preview_channel0_smoke_expansion: float
        fire_preview_channel0_smoke_turbulence: float
        fire_preview_channel0_smoke_dissipation: float
        fire_preview_channel0_smoke_opacity: float
        fire_preview_channel0_smoke_mesh_resolution: int
        fire_preview_channel0_falling_stars: int
        fire_preview_channel0_falling_velocity: float
        fire_preview_channel0_falling_spread: float
        fire_preview_channel0_falling_gravity: float
        fire_preview_channel0_falling_trail: float
        fire_preview_channel0_falling_twinkle: float
        fire_preview_channel1_intensity: float
        fire_preview_channel1_gpu_particle_size: float
        fire_preview_channel1_gpu_glow: float
        fire_preview_channel1_gravity: float
        fire_preview_channel1_fountain_jets: int
        fire_preview_channel1_fountain_particles: int
        fire_preview_channel1_fountain_velocity: float
        fire_preview_channel1_fountain_spread: float
        fire_preview_channel1_fountain_trail: float
        fire_preview_channel1_fountain_direction: tuple[float, float, float]
        fire_preview_channel1_crackle_stars: int
        fire_preview_channel1_crackle_velocity: float
        fire_preview_channel1_crackle_spread: float
        fire_preview_channel1_crackle_gravity: float
        fire_preview_channel1_crackle_branches: int
        fire_preview_channel1_crackle_branch_length: float
        fire_preview_channel1_crackle_trail: float
        fire_preview_channel1_smoke_puffs: int
        fire_preview_channel1_smoke_rise: float
        fire_preview_channel1_smoke_expansion: float
        fire_preview_channel1_smoke_turbulence: float
        fire_preview_channel1_smoke_dissipation: float
        fire_preview_channel1_smoke_opacity: float
        fire_preview_channel1_smoke_mesh_resolution: int
        fire_preview_channel1_falling_stars: int
        fire_preview_channel1_falling_velocity: float
        fire_preview_channel1_falling_spread: float
        fire_preview_channel1_falling_gravity: float
        fire_preview_channel1_falling_trail: float
        fire_preview_channel1_falling_twinkle: float
        fire_preview_channel2_intensity: float
        fire_preview_channel2_gpu_particle_size: float
        fire_preview_channel2_gpu_glow: float
        fire_preview_channel2_gravity: float
        fire_preview_channel2_fountain_jets: int
        fire_preview_channel2_fountain_particles: int
        fire_preview_channel2_fountain_velocity: float
        fire_preview_channel2_fountain_spread: float
        fire_preview_channel2_fountain_trail: float
        fire_preview_channel2_fountain_direction: tuple[float, float, float]
        fire_preview_channel2_crackle_stars: int
        fire_preview_channel2_crackle_velocity: float
        fire_preview_channel2_crackle_spread: float
        fire_preview_channel2_crackle_gravity: float
        fire_preview_channel2_crackle_branches: int
        fire_preview_channel2_crackle_branch_length: float
        fire_preview_channel2_crackle_trail: float
        fire_preview_channel2_smoke_puffs: int
        fire_preview_channel2_smoke_rise: float
        fire_preview_channel2_smoke_expansion: float
        fire_preview_channel2_smoke_turbulence: float
        fire_preview_channel2_smoke_dissipation: float
        fire_preview_channel2_smoke_opacity: float
        fire_preview_channel2_smoke_mesh_resolution: int
        fire_preview_channel2_falling_stars: int
        fire_preview_channel2_falling_velocity: float
        fire_preview_channel2_falling_spread: float
        fire_preview_channel2_falling_gravity: float
        fire_preview_channel2_falling_trail: float
        fire_preview_channel2_falling_twinkle: float
        collision_distance: float
        takeoff_altitude: float
        angle_export: float
        scale_export: int
        magic_number: MagicNumber
        effector_intensity: float
        effector_frame_rate: int
        effector_priority: float
        baking_frame_step: int
        effector_name: str
        effector_type: EffectorType
        baking_interpolation: Interpolation
        used_characters: str
        nb_drones_text: int
        text_font: str
        vel_hor_max: float
        vel_up_max: float
        vel_down_max: float
        acc_max: float
        emission_strength: float
        takeoff_keyframe: KeyframeType
        land_keyframe: KeyframeType
        go_to_target_keyframe: KeyframeType
        set_color_keyframe: KeyframeType
        magic_color_keyframe: KeyframeType
        fire_keyframe: KeyframeType
        old_takeoff_keyframe: KeyframeType
        old_land_keyframe: KeyframeType
        old_go_to_target_keyframe: KeyframeType
        old_set_color_keyframe: KeyframeType
        old_magic_color_keyframe: KeyframeType
        old_fire_keyframe: KeyframeType
        takeoff_marker: bool
        land_marker: bool
        go_to_target_marker: bool
        set_color_marker: bool
        magic_color_marker: bool
        fire_marker: bool
        follow_path_duration: float
        follow_path_time_delta: float
        follow_path_nb_anchors: int
        dev_mode: bool
        export_with_yaw: bool
        takeoff_end_frame: int
        rtl_start_frame: int
        rtl_land_altitude: float
        rtl_min_distance: float
        rtl_reposition_duration: float
        rtl_speed: float
        rtl_min_cruise_percent: float
        rtl_synchronized_departure: bool
        rtl_frame_delta: int
        disable_magic_color: bool
        bypass_export_checks: bool
        takeoff_mode: TakeoffMode
        installation_gap: InstallationGap
        enable_proximity_warning: bool
        proximity_line_collection: Any
        proximity_line_object: Any
        mesh_converter_object: Any
        mesh_converter_static_object: Any
        mesh_converter_distance: float
        mesh_converter_seed: int
        mesh_converter_is_rigged: bool


def register() -> None:
    bpy.utils.register_class(LightshowSetup)
    bpy.types.Scene.lightshow = bpy.props.PointerProperty(type=LightshowSetup)  # pyright: ignore


def unregister() -> None:
    del bpy.types.Scene.lightshow  # pyright: ignore
    bpy.utils.unregister_class(LightshowSetup)
