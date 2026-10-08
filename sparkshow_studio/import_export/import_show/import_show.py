import bpy

from sparkshow_studio._loader.schemas import IostarJsonGcs, ShowUser

from ...tools.grid_tools import create_drone_grid, is_drone_grid_initialized, remove_drone_grid
from ...tools.import_tools import convert_step_to_step_x_and_step_y
from ...tools.scene_tools import clean_scene
from ...tools.tutorial_links_tools import draw_tutorial_button, link
from ..import_export_base import ImportExportBasePanel, SelectFileBase, are_drones_initialized
from ..utils import import_show_user


class LIGHTSHOW_PT_import(ImportExportBasePanel):
    bl_label = "Import show"
    bl_idname = "LIGHTSHOW_PT_import"
    bl_parent_id = "LIGHTSHOW_PT_import_export_group"
    bl_options = {"HIDE_HEADER"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        scene = context.scene
        return not is_drone_grid_initialized(scene.collection) and not are_drones_initialized(
            scene.collection
        )

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        draw_tutorial_button(
            layout,
            context,
            main_button_fn=lambda col: col.operator("lightshow.import"),
            section=link.import_and_export.import_show,
            option="",
        )


class LIGHTSHOW_OT_import(SelectFileBase):
    bl_label = "Import Show"
    bl_description = "Import a complete show"
    bl_idname = "lightshow.import"

    def execute(self, context: bpy.types.Context) -> set[str]:
        filepath = self.get_filepath()

        scene = context.scene

        clean_scene(scene)
        create_drone_grid(scene.collection)
        remove_drone_grid(scene.collection)

        json_content: str = filepath.read_text()
        json_content = convert_step_to_step_x_and_step_y(json_content)
        iostar_json_gcs = IostarJsonGcs.model_validate_json(json_content)
        show_user = ShowUser.from_iostar_json_gcs(iostar_json_gcs)

        import_show_user(show_user, context, is_range_import=False)

        # Match the frame range of the imported show with the scene
        scene.frame_start = 0
        scene.frame_end = show_user.last_frame - 1

        self.report_print({"INFO"}, "Import successful")

        return {"FINISHED"}


classes = [
    LIGHTSHOW_PT_import,
    LIGHTSHOW_OT_import,
]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in classes:
        bpy.utils.unregister_class(cls)
