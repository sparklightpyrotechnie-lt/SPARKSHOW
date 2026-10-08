from pathlib import Path

import bpy

from ..base import BaseOperator, BasePanel, BasePanelHideIfNoDrone
from ..tools.collection_tools import are_drones_initialized
from ..tools.grid_tools import is_drone_grid_initialized
from ..tools.tutorial_links_tools import draw_tutorial_button, link


class LIGHTSHOW_PT_import_export_group(BasePanel):
    bl_parent_id = "SPARKSHOW_STUDIO_PT_export"
    bl_label = "📥 Import & Export"
    bl_idname = "LIGHTSHOW_PT_import_export_group"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "sparkshow"

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return not is_drone_grid_initialized(context.scene.collection) or are_drones_initialized(
            context.scene.collection
        )

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        draw_tutorial_button(
            layout,
            context,
            main_button_fn=None,
            section=link.import_and_export,
        )

        scene = context.scene
        scene_collection = scene.collection
        is_show_initialized = are_drones_initialized(scene_collection)

        if is_show_initialized:
            props = getattr(context.scene, "import_export_properties", None)
            if props is None:
                layout.label(text="Import/Export properties not found", icon="ERROR")
                return
            layout.prop(props, "import_export_mode", expand=True)

            layout.use_property_split = True
            layout.use_property_decorate = False

            if props.import_export_mode == "EXPORT":
                layout.prop(props, "export_types", text="Mode")
            if props.import_export_mode == "IMPORT":
                layout.prop(props, "import_types", text="Mode")


class SelectFileBase(BaseOperator):
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")  # pyright: ignore

    def set_filepath(self, filepath: Path) -> None:
        self.filepath = str(filepath)

    def get_filepath(self) -> Path:
        filepath = Path(self.filepath)
        filepath = filepath.with_suffix(".json")
        self.set_filepath(filepath)
        return filepath

    def invoke(
        self,
        context: bpy.types.Context,
        event: bpy.types.Event,  # noqa: ARG002
    ) -> set[str]:
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class ExportBase(SelectFileBase):
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")  # pyright: ignore

    def set_filepath(self, filepath: Path) -> None:
        self.filepath = str(filepath.stem)

    def invoke(
        self,
        context: bpy.types.Context,
        event: bpy.types.Event,
    ) -> set[str]:
        if bpy.data.filepath != "" and self.filepath == "":
            self.set_filepath(Path(bpy.data.filepath))
        return super().invoke(context, event)


class ImportExportBasePanel(BasePanelHideIfNoDrone):
    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        scene = context.scene
        props = getattr(scene, "import_export_properties", None)
        export_type = (
            props.import_types
            if props.import_export_mode.lower() == "import"
            else props.export_types
        )
        return (
            props
            and cls.bl_idname == "LIGHTSHOW_PT_" + export_type.lower().replace(" ", "_")
            and props.import_export_mode.lower() in cls.bl_idname
        )


classes = [
    LIGHTSHOW_PT_import_export_group,
]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in classes:
        bpy.utils.unregister_class(cls)
