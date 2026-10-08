import bpy

CHECK_TYPES_ITEMS = [
    ("PROXIMITY", "Proximity", "Check if the light is within a certain distance from an object"),
    ("SPEED ACCEL", "Speed & Acceleration", "Check the speed and acceleration of the light"),
    ("OTHER CHECKS", "Other", "Other checks that do not fit into the above categories"),
]


class CheckProperties(bpy.types.PropertyGroup):
    check_type: bpy.props.EnumProperty(
        name=" ",
        description="Type of check to perform",
        items=CHECK_TYPES_ITEMS,
        default="PROXIMITY",
    )


classes = (CheckProperties,)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)  # type: ignore
    bpy.types.Scene.check_properties = bpy.props.PointerProperty(type=CheckProperties)  # type: ignore


def unregister() -> None:
    del bpy.types.Scene.check_properties  # pyright: ignore
    for cls in classes:
        bpy.utils.unregister_class(cls)  # type: ignore
