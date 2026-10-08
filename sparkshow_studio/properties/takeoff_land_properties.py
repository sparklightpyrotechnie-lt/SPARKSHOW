import bpy


class PlatformProperties(bpy.types.PropertyGroup):
    platform_width: bpy.props.FloatProperty(  # pyright: ignore
        name="Platform Width",
        description="Width of the platform in meters.",
        default=0.77,
        min=0.0,
        precision=2,
        unit="LENGTH",
    )
    platform_length: bpy.props.FloatProperty(  # pyright: ignore
        name="Platform Length",
        description="Length of the platform in meters.",
        default=1.16,
        min=0.0,
        precision=2,
        unit="LENGTH",
    )
    nb_drones_per_platform: bpy.props.IntProperty(  # pyright: ignore
        name="Number of Drones per Platform",
        description="Number of drones per platform.",
        default=6,
        min=1,
    )


classes = [PlatformProperties]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.platform_props = bpy.props.PointerProperty(type=PlatformProperties)  # type: ignore


def unregister() -> None:
    del bpy.types.Scene.platform_props  # pyright: ignore
    for cls in classes:
        bpy.utils.unregister_class(cls)
