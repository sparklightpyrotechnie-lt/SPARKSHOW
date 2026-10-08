import bpy

from ..base import BaseOperator, BasePanelHideIfNoDrone
from ..tools.collection_tools import get_selected_drones_or_all
from ..tools.takeoff_land_tools import has_drone_takeoff
from ..tools.tutorial_links_tools import draw_tutorial_button, link


class LIGHTSHOW_PT_check_group(BasePanelHideIfNoDrone):
    bl_parent_id = "SPARKSHOW_STUDIO_PT_safety"
    bl_label = "☑ Checks"
    bl_idname = "LIGHTSHOW_PT_check_group"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "sparkshow"

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        draw_tutorial_button(
            layout,
            context,
            main_button_fn=None,
            section=link.check,
        )
        props = getattr(context.scene, "check_properties", None)
        if props is None:
            layout.label(text="Check properties not found", icon="ERROR")
            return
        layout.prop(props, "check_type", expand=True)


class CheckBase(BaseOperator):
    def get_taken_off_drones(
        self,
        context: bpy.types.Context,
        nb_drones: int,
    ) -> list[bpy.types.Object]:
        selected_drones, filtered_drones = get_selected_drones_or_all(
            context,
            key=has_drone_takeoff,
        )

        if len(selected_drones) < nb_drones:
            self.report_print(
                {"ERROR"},
                f"You must select at least {nb_drones} drone(s) that has taken off.",
            )
            return []

        if filtered_drones:
            self.report_print(
                {"WARNING"},
                "Some selected drones have not taken off, they will be ignored",
            )

        for drone in selected_drones + filtered_drones:
            drone.select_set(False)

        return selected_drones


class CheckBasePanel(BasePanelHideIfNoDrone):
    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        scene = context.scene
        props = getattr(scene, "check_properties", None)
        return props and cls.bl_idname == "LIGHTSHOW_PT_" + props.check_type.lower().replace(
            " ", "_"
        )


classes = [
    LIGHTSHOW_PT_check_group,
]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in classes:
        bpy.utils.unregister_class(cls)
