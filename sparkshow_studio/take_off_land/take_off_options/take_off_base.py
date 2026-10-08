import bpy

from ...base import BasePanelHideIfNoDrone
from ...setup import get_lightshow


class LIGHTSHOW_PT_takeoff_panel(BasePanelHideIfNoDrone):
    bl_label = "🛫 Take off"
    bl_idname = "LIGHTSHOW_PT_take_off_panel"
    bl_parent_id = "LIGHTSHOW_PT_take_off_land_main_panel"

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        scene = context.scene
        lightshow = get_lightshow(scene)
        return lightshow is not None

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        lightshow = get_lightshow(context.scene)

        props = getattr(context.scene, "takeoff_props", None)
        if props is None:
            layout.label(text="Mesh properties not found", icon="ERROR")
            return

        layout.prop(props, "takeoff_type", expand=True, text="Type")

        take_off_option_list = (
            "take_off_options_classic"
            if lightshow.takeoff_mode == "standard_takeoff"
            else "take_off_options_all_in_one"
        )

        layout.prop(props, take_off_option_list, text="Type")


class TakeOffBasePanel(BasePanelHideIfNoDrone):
    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        scene = context.scene
        props = getattr(scene, "takeoff_props", None)
        lightshow = get_lightshow(context.scene)

        take_off_option = (
            props.take_off_options_classic
            if lightshow.takeoff_mode == "standard_takeoff"
            else props.take_off_options_all_in_one
        )

        return props and cls.bl_idname == "LIGHTSHOW_PT_" + take_off_option.lower().replace(
            " ", "_"
        )


classes = (LIGHTSHOW_PT_takeoff_panel,)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in classes:
        bpy.utils.unregister_class(cls)
