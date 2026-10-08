from pathlib import Path

import bpy
import numpy as np

from sparkshow_studio._loader.schemas.vviz import PyroPayloadDescription, Vviz, convert_enu_to_vviz

from ...fire.utils import keyframe_fire
from ...setup import FPS, get_lightshow
from ...tools.collection_tools import get_blender_drone_from_drone_index, get_drones
from ...tools.fcurve_tools import find_fcurve_or_none
from ...tools.tutorial_links_tools import draw_tutorial_button, link
from ..import_export_base import (
    BaseOperator,
    ExportBase,
    ImportExportBasePanel,
    are_drones_initialized,
)
from ..utils import add_date_to_path, get_show_user


class LIGHTSHOW_PT_vviz_export(ImportExportBasePanel):
    bl_label = "Import/Export VVIZ"
    bl_idname = "LIGHTSHOW_PT_export_vviz"
    bl_parent_id = "LIGHTSHOW_PT_import_export_group"
    bl_options = {"HIDE_HEADER"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return super().poll(context) and are_drones_initialized(context.scene.collection)

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        props = getattr(context.scene, "import_export_properties", None)
        if props is None:
            layout.label(text="Export properties not found", icon="ERROR")
            return
        draw_tutorial_button(
            layout,
            context,
            main_button_fn=lambda col: col.operator("lightshow.export_vviz"),
            section=link.import_and_export.export_show,
            option="",
        )


class LIGHTSHOW_PT_vviz_import(ImportExportBasePanel):
    bl_label = "Import/Export VVIZ"
    bl_idname = "LIGHTSHOW_PT_import_vviz"
    bl_parent_id = "LIGHTSHOW_PT_import_export_group"
    bl_options = {"HIDE_HEADER"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return super().poll(context) and are_drones_initialized(context.scene.collection)

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        props = getattr(context.scene, "import_export_properties", None)
        if props is None:
            layout.label(text="Import properties not found", icon="ERROR")
            return
        draw_tutorial_button(
            layout,
            context,
            main_button_fn=lambda col: col.operator("lightshow.import_vviz_fire"),
            section=link.import_and_export.import_show,
            option="",
        )


class LIGHTSHOW_OT_export_vviz(ExportBase):
    bl_label = "Export VVIZ"
    bl_description = "Export to the VVIZ format"
    bl_idname = "lightshow.export_vviz"

    def execute(self, context: bpy.types.Context) -> set[str]:
        filepath = self.get_filepath().with_suffix(".vviz")
        filepath = add_date_to_path(filepath)

        scene = context.scene

        blender_drones = get_drones(scene.collection)

        show_user = get_show_user(blender_drones, scene, use_scene_range=False)

        vviz = Vviz.from_show_user(
            show_user,
            performance_name=filepath.stem,
        )

        filepath.write_text(vviz.model_dump_json(exclude_none=True))

        self.report_print({"INFO"}, f"Exported VVIZ to {filepath}")

        return {"FINISHED"}


class LIGHTSHOW_OT_import_vviz_fire(BaseOperator):
    bl_label = "Import VVIZ"
    bl_description = """\
Import the fire events from the VVIZ file"""
    bl_idname = "lightshow.import_vviz_fire"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")  # pyright: ignore

    def execute(self, context: bpy.types.Context) -> set[str]:  # noqa: C901
        scene = context.scene
        lightshow = get_lightshow(scene)
        vviz = Vviz.model_validate_json(Path(self.filepath).read_text())

        try:
            drone_performances = {
                get_blender_drone_from_drone_index(performance.id, scene.collection): performance
                for performance in vviz.performances
            }
        except KeyError:
            self.report_print(
                {"ERROR"},
                "The drone indices in the VVIZ file do not match the drones in the scene",
            )
            return {"CANCELLED"}

        scene.frame_set(1)
        for drone, performance in drone_performances.items():
            vviz_home = (
                performance.agentDescription.homeX,
                performance.agentDescription.homeY,
                performance.agentDescription.homeZ,
            )
            drone_home = convert_enu_to_vviz(drone.matrix_world.to_translation())  # pyright: ignore
            if not np.isclose(vviz_home, drone_home, atol=1e-2).all():
                self.report_print(
                    {"ERROR"},
                    (
                        "The home position of the drone in the VVIZ file does not match the home position in the scene\n"
                        f"VVIZ home: {vviz_home}\n"
                        f"Drone home: {drone_home}"
                    ),
                )
                return {"CANCELLED"}

        for drone in drone_performances:
            for index in range(3):
                fcurve = find_fcurve_or_none(drone, '["fire"]', index)
                if fcurve is not None and len(fcurve.keyframe_points) > 0:
                    self.report_print({"ERROR"}, f"{drone.name} already has fire events")
                    return {"CANCELLED"}

        for performance in drone_performances.values():
            nb_pyro = 0
            for payload in performance.payloadDescription:
                if isinstance(payload, PyroPayloadDescription) and (nb_pyro := nb_pyro + 1) > 3:
                    self.report_print(
                        {"ERROR"},
                        "A drone in the VVIZ file has more than 3 pyro payloads",
                    )
                    return {"CANCELLED"}

        for drone, performance in drone_performances.items():
            fire_index = 0
            for payload in performance.payloadDescription:
                if not isinstance(payload, PyroPayloadDescription):
                    continue

                frame = round(payload.eventTime * FPS)
                duration_ms = round(lightshow.fire_duration * 1000)
                keyframe_fire(
                    drone,
                    fire_index,
                    frame,
                    duration_ms,
                    lightshow.fire_keyframe,
                    payload.vdl,
                )
                fire_index += 1

        try:
            from ...fire.preview import refresh_preview
            refresh_preview(context.scene)
        except (ImportError, RuntimeError):
            pass

        return {"FINISHED"}

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:  # noqa: ARG002
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


classes = [
    LIGHTSHOW_PT_vviz_export,
    LIGHTSHOW_PT_vviz_import,
    LIGHTSHOW_OT_export_vviz,
    LIGHTSHOW_OT_import_vviz_fire,
]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in classes:
        bpy.utils.unregister_class(cls)
