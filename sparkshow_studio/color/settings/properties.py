import bpy


class ColorSettingsProperties(bpy.types.PropertyGroup):
    enabled: bpy.props.BoolProperty(
        name="Enabled",
        description="Enable or disable color settings",
        default=False,
    )
    previous_background_color: bpy.props.FloatVectorProperty(
        name="Previous Background Color",
        description="Previous color of the background",
        subtype="COLOR",
        size=4,
        default=(0.1, 0.1, 0.1, 1.0),
        min=0.0,
        max=1.0,
    )
    previous_shading_type: bpy.props.StringProperty(
        name="Previous Shading Type",
        description="Previous shading type used in the viewport",
        default="MATERIAL",
    )
    previous_use_compositor: bpy.props.StringProperty(
        name="Use Compositor",
        description="Previous use of compositor in the viewport",
        default="Disabled",
    )


classes = [
    ColorSettingsProperties,
]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.color_settings = bpy.props.PointerProperty(type=ColorSettingsProperties)


def unregister() -> None:
    del bpy.types.Scene.color_settings
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
