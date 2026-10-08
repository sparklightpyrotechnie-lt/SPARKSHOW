import bpy
import numpy as np

from sparkshow_studio._loader.parameters import IOSTAR_PHYSIC_PARAMETERS_RECOMMENDATION

from ...base import BaseOperator, BasePanelHideIfNoDrone
from ...setup import get_lightshow
from ...tools.collection_tools import add_collection
from ...tools.tutorial_links_tools import draw_tutorial_button, link
from .utils import get_grids


class LIGHTSHOW_PT_land_panel(BasePanelHideIfNoDrone):
    bl_label = "🪂 Land"
    bl_idname = "LIGHTSHOW_PT_land_panel"
    bl_parent_id = "LIGHTSHOW_PT_take_off_land_main_panel"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        scene = context.scene
        lightshow = get_lightshow(scene)
        return lightshow is not None

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        props = getattr(context.scene, "land_properties", None)
        lightshow = get_lightshow(context.scene)

        if props is None:
            layout.label(text="Land properties not found", icon="ERROR")
            return
        land_type_list = (
            "land_types_standard"
            if lightshow.takeoff_mode == "standard_takeoff"
            else "land_types_all_in_one"
        )
        layout.prop(props, land_type_list, text="Mode")

        if (
            lightshow.takeoff_mode == "standard_takeoff" and props.land_types_standard != "NONE"
        ) or (
            lightshow.takeoff_mode == "using all in one platform"
            and props.land_types_all_in_one != "NONE"
        ):
            draw_tutorial_button(
                layout,
                context,
                main_button_fn=lambda col: col.operator("lightshow.add_family_grids", icon="GRID"),
                section=link.takeoff_and_land,
                option="family_grids",
            )


class LandBasePanel(BasePanelHideIfNoDrone):
    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        scene = context.scene
        props = getattr(scene, "land_properties", None)
        lightshow = get_lightshow(context.scene)

        land_type = (
            props.land_types_standard
            if lightshow.takeoff_mode == "standard_takeoff"
            else props.land_types_all_in_one
        )
        return props and cls.bl_idname == "LIGHTSHOW_PT_" + land_type.lower().replace(" ", "_")


class LIGHTSHOW_OT_add_family_grids(BaseOperator):
    bl_label = "Add family grids"
    bl_description = """\
Add one grid per family to the scene.
The grids will be proportionally placed between the takeoff altitude and the ground"""
    bl_idname = "lightshow.add_family_grids"

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.distance_between_grids = 2.0

    def execute(self, context: bpy.types.Context) -> set[str]:
        scene = context.scene
        lightshow = get_lightshow(scene)

        collection = add_collection("Family Grids", scene.collection)
        step: float = lightshow.step_x
        if lightshow.takeoff_mode == "using all in one platform":
            self.report_print(
                {"INFO"},
                f"Using the minimum distance = {IOSTAR_PHYSIC_PARAMETERS_RECOMMENDATION.minimum_distance}m for grids",
            )
        elif step < IOSTAR_PHYSIC_PARAMETERS_RECOMMENDATION.minimum_distance:
            self.report_print(
                {"WARNING"},
                f"{round(step, 2)}m is too small, using the minimum distance = {IOSTAR_PHYSIC_PARAMETERS_RECOMMENDATION.minimum_distance}m instead",
            )
            step = IOSTAR_PHYSIC_PARAMETERS_RECOMMENDATION.minimum_distance

        altitudes = np.linspace(
            lightshow.nb_drones_per_family * self.distance_between_grids,
            lightshow.takeoff_altitude / lightshow.nb_drones_per_family,
            lightshow.nb_drones_per_family,
        )

        for grid, altitude in zip(get_grids(lightshow, step), altitudes, strict=True):
            grid.location.z = altitude
            collection.objects.link(grid)

        return {"FINISHED"}


classes = (LIGHTSHOW_PT_land_panel, LIGHTSHOW_OT_add_family_grids)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in classes:
        bpy.utils.unregister_class(cls)
