import bpy


class LightShowPreferences(bpy.types.AddonPreferences):
    bl_idname = "sparkshow_studio"

    help_enable: bpy.props.BoolProperty(  # pyright: ignore
        name="Enable Help Mode",
        description="Simplify the interface and show helpful tips for new users",
        default=True,
    )

    def draw(self, context: bpy.types.Context) -> None:  # noqa: ARG002
        layout = self.layout
        assert layout is not None, "Layout should not be None"
        layout.prop(self, "help_enable")


def register() -> None:
    bpy.utils.register_class(LightShowPreferences)


def unregister() -> None:
    bpy.utils.unregister_class(LightShowPreferences)
