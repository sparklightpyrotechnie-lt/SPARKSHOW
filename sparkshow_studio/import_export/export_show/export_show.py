from typing import TYPE_CHECKING

import bpy
import numpy as np

from sparkshow_studio._loader.schemas import IostarJsonGcs

from ...setup import GAP_BETWEEN_PLATFORMS, TAKEOFF_PARAMETERS, get_lightshow
from ...tools.collection_tools import get_drones
from ...tools.takeoff_land_tools import has_drone_land, has_drone_takeoff
from ...tools.tutorial_links_tools import draw_tutorial_button, link
from ..import_export_base import ExportBase, ImportExportBasePanel, are_drones_initialized
from ..utils import add_date_to_path, check_show_user, get_show_user

if TYPE_CHECKING:
    from ...setup import Lightshow


class LIGHTSHOW_PT_export(ImportExportBasePanel):
    bl_label = "Export show"
    bl_idname = "LIGHTSHOW_PT_export_show"
    bl_parent_id = "LIGHTSHOW_PT_import_export_group"
    bl_options = {"HIDE_HEADER"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return super().poll(context) and are_drones_initialized(context.scene.collection)

    def draw(self, context: bpy.types.Context) -> None:
        scene = context.scene
        lightshow = get_lightshow(scene)
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        layout.prop(lightshow, "magic_number", expand=True)
        if lightshow.rtl_start_frame != -1 and lightshow.magic_number == "V1":
            layout.label(
                text="RTL is not supported in V1 format",
                icon="ERROR",
            )
        if lightshow.magic_number == "V2":
            layout.prop(lightshow, "scale_export")
        if lightshow.export_with_yaw:
            layout.prop(lightshow, "export_with_yaw")
        layout.prop(lightshow, "angle_export")
        if lightshow.bypass_export_checks:
            layout.prop(lightshow, "bypass_export_checks")

        draw_tutorial_button(
            layout,
            context,
            main_button_fn=lambda col: col.operator("lightshow.export"),
            section=link.import_and_export.export_show,
            option="",
        )


def check_step_export(lightshow: "Lightshow") -> None:
    if lightshow.takeoff_mode == "using all in one platform":
        expected_value_x = TAKEOFF_PARAMETERS.platform_length
        expected_value_x += GAP_BETWEEN_PLATFORMS if lightshow.installation_gap == "COLUMN" else 0

        expected_value_y = TAKEOFF_PARAMETERS.platform_width
        expected_value_y += GAP_BETWEEN_PLATFORMS if lightshow.installation_gap == "LINE" else 0

        if not np.isclose(lightshow.step_x, expected_value_x, atol=1e-2):
            msg = f"WARNING: step_x is not the expected value ({expected_value_x}) for takeoff mode 'using all in one platform', current value = {lightshow.step_x}"
            raise ValueError(msg)

        if not np.isclose(lightshow.step_y, expected_value_y, atol=1e-2):
            msg = f"WARNING: step_y is not the expected value ({expected_value_y}) for takeoff mode 'using all in one platform', current value = {lightshow.step_y}"
            raise ValueError(msg)


class LIGHTSHOW_OT_export(ExportBase):
    bl_label = "Export"
    bl_description = "Export the complete show"
    bl_idname = "lightshow.export"

    def execute(self, context: bpy.types.Context) -> set[str]:
        filepath = self.get_filepath()

        scene = context.scene
        lightshow = get_lightshow(scene)

        # TODO(<PAG>): refactor this code and find a better way to handle this error
        check_step_export(lightshow)

        angle_export_deg = round(np.rad2deg(lightshow.angle_export))

        if angle_export_deg != 0:
            filepath = filepath.with_stem(
                f"{filepath.stem}_{angle_export_deg}_deg",
            )
        filepath = add_date_to_path(filepath)

        blender_drones = get_drones(scene.collection)

        if not all(has_drone_takeoff(blender_drone) for blender_drone in blender_drones):
            self.report_print(
                {"ERROR"},
                "All drones must have takeoff",
            )
            return {"CANCELLED"}

        if not all(has_drone_land(blender_drone) for blender_drone in blender_drones):
            self.report_print(
                {"ERROR"},
                "All drones must have land",
            )
            return {"CANCELLED"}

        show_user = get_show_user(
            blender_drones,
            scene,
            use_scene_range=False,
            with_yaw=lightshow.export_with_yaw,
        )
        show_user.apply_horizontal_rotation(lightshow.angle_export)
        show_user.scale = lightshow.scale_export

        report_error_message = check_show_user(show_user, filepath)

        if report_error_message is not None:
            self.report_print({"ERROR"}, report_error_message)
            if not lightshow.bypass_export_checks:
                return {"CANCELLED"}

        iostar_json_gcs = IostarJsonGcs.from_show_user(show_user)

        filepath.write_text(iostar_json_gcs.model_dump_json())

        self.report_print(
            {"INFO"},
            f"Exported to {filepath}",
        )

        return {"FINISHED"}


classes = [
    LIGHTSHOW_PT_export,
    LIGHTSHOW_OT_export,
]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in classes:
        bpy.utils.unregister_class(cls)
