import bpy

from ...setup import get_lightshow
from ...tools.collection_tools import get_selected_drones_or_all
from ...tools.tutorial_links_tools import draw_tutorial_button, link
from ..import_export_base import ExportBase, ImportExportBasePanel
from ..utils import add_date_to_path, check_show_user, get_show_user


class LIGHTSHOW_PT_export_range(ImportExportBasePanel):
    bl_label = "Export range"
    bl_idname = "LIGHTSHOW_PT_export_range"
    bl_parent_id = "LIGHTSHOW_PT_import_export_group"
    bl_options = {"HIDE_HEADER"}

    def draw(self, context: bpy.types.Context) -> None:
        scene = context.scene
        lightshow = get_lightshow(scene)
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        row = self.layout.row()
        draw_tutorial_button(
            row,
            context,
            main_button_fn=lambda col: col.operator("lightshow.export_range"),
            section=link.import_and_export.import_and_export_range,
            option="export_range",
        )
        if lightshow.bypass_export_checks:
            layout.prop(lightshow, "bypass_export_checks")


class LIGHTSHOW_OT_export_range(ExportBase):
    bl_label = "Export range"
    bl_description = "Export a range of the show"
    bl_idname = "lightshow.export_range"

    def execute(self, context: bpy.types.Context) -> set[str]:
        filepath = self.get_filepath()

        scene = context.scene
        lightshow = get_lightshow(scene)
        filepath = filepath.with_stem(
            f"{filepath.stem}_range_{scene.frame_start}_{scene.frame_end}",
        )
        filepath = add_date_to_path(filepath)

        blender_drones = get_selected_drones_or_all(context)

        show_user = get_show_user(blender_drones, scene, use_scene_range=True)

        report_error_message = check_show_user(show_user, filepath, is_partial=True)

        if report_error_message is not None:
            self.report_print({"ERROR"}, report_error_message)
            if not lightshow.bypass_export_checks:
                return {"CANCELLED"}

        filepath.write_text(show_user.model_dump_json())

        self.report_print(
            {"INFO"},
            f"Exported range to {filepath}",
        )

        return {"FINISHED"}


classes = [
    LIGHTSHOW_PT_export_range,
    LIGHTSHOW_OT_export_range,
]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in classes:
        bpy.utils.unregister_class(cls)
