import bpy

COLOR_TYPES_ITEMS = [
    ("SET COLOR", "Set Color", "Set the color of the light"),
    ("COLOR EFFECT", "Color Effect", "Apply a color effect to the light"),
    ("MAGIC COLOR", "Magic Color", "Apply a magic color effect to the light"),
]


class ColorProperties(bpy.types.PropertyGroup):
    color_type: bpy.props.EnumProperty(
        name="Color Mode",
        description="Type of color operation",
        items=COLOR_TYPES_ITEMS,
        default="SET COLOR",
    )


classes = (ColorProperties,)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)  # type: ignore
    bpy.types.Scene.color_properties = bpy.props.PointerProperty(type=ColorProperties)  # type: ignore


def unregister() -> None:
    del bpy.types.Scene.color_properties  # pyright: ignore
    for cls in classes:
        bpy.utils.unregister_class(cls)  # type: ignore
