import bpy


class RTLProperties(bpy.types.PropertyGroup):
    is_running: bpy.props.BoolProperty(  # pyright: ignore
        name="Is Running",
        description="Whether the mesh generation is running.",
        default=False,
    )
    cancelled: bpy.props.BoolProperty(  # pyright: ignore
        name="Cancelled",
        description="Whether the mesh generation was cancelled.",
        default=False,
    )
    current_time_delta: bpy.props.IntProperty(  # pyright: ignore
        name="Time Delta",
        description="The current time delta in the RTL calculation.",
        default=0,
    )
    calculated_trajectories: bpy.props.IntProperty(  # pyright: ignore
        name="Nb Trajectories",
        description="Number of calculated trajectories.",
        default=0,
    )
    nb_drones: bpy.props.IntProperty(  # pyright: ignore
        name="Nb Drones",
        description="Total number of drones.",
        default=0,
    )


classes = [RTLProperties]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.rtl_props = bpy.props.PointerProperty(type=RTLProperties)  # type: ignore


def unregister() -> None:
    del bpy.types.Scene.rtl_props  # pyright: ignore
    for cls in classes:
        bpy.utils.unregister_class(cls)
