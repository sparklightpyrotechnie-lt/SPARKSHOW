import bpy

from sparkshow_studio._loader.schemas import ShowUser

from ...base import BaseOperator
from ...tools.collection_tools import get_linkable_drones_couples, get_nb_import_drones
from ...tools.fcurve_tools import (
    RGBW_EMISSION_MATERIAL_DATA_PATH,
    copy_keyframe,
    find_fcurve,
    find_fcurve_or_create,
    find_fcurve_or_none,
    get_frame,
)
from ...tools.tutorial_links_tools import draw_tutorial_button, link
from ..import_export_base import ImportExportBasePanel, SelectFileBase
from ..utils import check_show_user, import_show_user


class LIGHTSHOW_PT_import_range(ImportExportBasePanel):
    bl_label = "Import range"
    bl_idname = "LIGHTSHOW_PT_import_range"
    bl_parent_id = "LIGHTSHOW_PT_import_export_group"
    bl_options = {"HIDE_HEADER"}

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        draw_tutorial_button(
            layout,
            context,
            main_button_fn=lambda col: col.operator("lightshow.import_range"),
            section=link.import_and_export.import_and_export_range,
            option="import_range",
        )

        draw_tutorial_button(
            layout,
            context,
            main_button_fn=lambda col: col.operator("lightshow.link_import", icon="LINKED"),
            section=link.import_and_export.import_and_export_range,
            option="link_import",
        )


class LIGHTSHOW_OT_import_range(SelectFileBase):
    bl_label = "Import range"
    bl_description = "Import a show range to link with the current show"
    bl_idname = "lightshow.import_range"

    def execute(self, context: bpy.types.Context) -> set[str]:
        filepath = self.get_filepath()

        show_user = ShowUser.model_validate_json(filepath.read_text())

        report_error_message = check_show_user(show_user, filepath, is_partial=True)

        if report_error_message is not None:
            self.report_print({"ERROR"}, report_error_message)

        import_show_user(show_user, context, is_range_import=True)

        return {"FINISHED"}


class LIGHTSHOW_OT_link_import(BaseOperator):
    bl_label = "Link import"
    bl_description = """\
Link the imported drones to the drones of the current show
The linking will transfer the color and fire events of the imported drones to the drones of the current show
For the link to work, the drones of the current show must do a Go to target on the imported drones
Once the link is done, the imported drones will be hidden"""
    bl_idname = "lightshow.link_import"

    def execute(self, context: bpy.types.Context) -> set[str]:  # noqa: C901
        scene = context.scene
        nb_import_drones = get_nb_import_drones(scene.collection)
        couples = get_linkable_drones_couples(scene.collection)

        if nb_import_drones == 0:
            self.report_print({"WARNING"}, "No import drones")
            return {"CANCELLED"}

        if nb_import_drones != len(couples):
            self.report_print({"ERROR"}, "Not all import drones are linked")
            return {"CANCELLED"}

        for _, import_drone in couples:
            import_drone.hide_set(True)
            assert import_drone.parent is not None
            import_drone.parent.hide_set(True)

        for drone, import_drone in couples:
            emission_material = drone.active_material
            import_emission_material = import_drone.active_material
            assert emission_material is not None
            assert import_emission_material is not None

            if drone.name.startswith("Drone "):
                fcurves = [
                    (
                        find_fcurve(drone, "color", index),
                        find_fcurve(
                            import_emission_material.node_tree,  # pyright: ignore
                            RGBW_EMISSION_MATERIAL_DATA_PATH,
                            index,
                        ),
                    )
                    for index in range(4)
                ]
            else:
                fcurves = [
                    (
                        find_fcurve(
                            emission_material.node_tree,  # pyright: ignore
                            RGBW_EMISSION_MATERIAL_DATA_PATH,
                            index,
                        ),
                        find_fcurve(
                            import_emission_material.node_tree,  # pyright: ignore
                            RGBW_EMISSION_MATERIAL_DATA_PATH,
                            index,
                        ),
                    )
                    for index in range(4)
                ]
            fcurves += [
                (
                    find_fcurve_or_create(drone, '["fire"]', index),
                    import_fcurve,
                )
                for index in range(3)
                if (import_fcurve := find_fcurve_or_none(import_drone, '["fire"]', index))
                is not None
            ]
            for index in range(3):
                drone[f"fire_vdl{index}"] = import_drone[f"fire_vdl{index}"]

            for fcurve, import_fcurve in fcurves:
                if len(fcurve.keyframe_points) > 0 and (
                    get_frame(fcurve, -1) >= get_frame(import_fcurve, 0)
                ):
                    msg = "Import drone has keyframes before the last keyframe of the drone to link"
                    self.report_print({"ERROR"}, msg)
                    return {"CANCELLED"}

            for fcurve, import_fcurve in fcurves:
                keyframe_points_length = len(fcurve.keyframe_points)
                if keyframe_points_length > 0:
                    fcurve.keyframe_points[-1].interpolation = "CONSTANT"

                fcurve.keyframe_points.add(len(import_fcurve.keyframe_points))
                for keyframe_point, import_keyframe_point in zip(
                    fcurve.keyframe_points[keyframe_points_length:],
                    import_fcurve.keyframe_points,
                    strict=False,
                ):
                    copy_keyframe(import_keyframe_point, keyframe_point)

        return {"FINISHED"}


classes = [LIGHTSHOW_PT_import_range, LIGHTSHOW_OT_import_range, LIGHTSHOW_OT_link_import]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in classes:
        bpy.utils.unregister_class(cls)
