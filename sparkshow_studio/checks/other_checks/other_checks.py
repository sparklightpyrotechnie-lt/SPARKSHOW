import bpy

from ...tools.collection_tools import is_collection_empty
from ...tools.tutorial_links_tools import draw_tutorial_button, link
from ..check import CheckBase, CheckBasePanel
from ..check_algorithm import (
    apply_autopilot_format_check,
    apply_dance_size_check,
    apply_takeoff_check,
    get_dance_size_informations,
)


class LIGHTSHOW_PT_other_checks(CheckBasePanel):
    bl_label = "Other Checks"
    bl_idname = "LIGHTSHOW_PT_other_checks"
    bl_parent_id = "LIGHTSHOW_PT_check_group"
    bl_options = {"HIDE_HEADER"}

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        draw_tutorial_button(
            layout,
            context,
            main_button_fn=None,
            section=link.check.others,
            text="Help with Other Checks",
        )
        layout.operator("lightshow.check_takeoff")
        layout.operator("lightshow.check_autopilot_format")
        layout.operator("lightshow.check_dance_size")


class LIGHTSHOW_OT_check_dance_size(CheckBase):
    bl_label = "Check dance size"
    bl_description = "Check if the selected drones respect the dance size"
    bl_idname = "lightshow.check_dance_size"

    def execute(self, context: bpy.types.Context) -> set[str]:
        scene = context.scene
        effector_collection = context.scene.collection.children.get("Effector")
        if effector_collection is not None and not is_collection_empty(effector_collection):
            self.report_print(
                {"ERROR"},
                "You must disable all the effectors to apply this check",
            )
            return {"CANCELLED"}

        drones = self.get_taken_off_drones(context, 1)
        if not drones:
            return {"CANCELLED"}

        dance_size_report = apply_dance_size_check(drones, scene)

        self.report_print(
            {"ERROR"} if len(dance_size_report) else {"INFO"},
            get_dance_size_informations(dance_size_report),
        )
        return {"FINISHED"}


class LIGHTSHOW_OT_check_takeoff(CheckBase):
    bl_label = "Check takeoff"
    bl_description = "Check if the selected drones take off correctly"
    bl_idname = "lightshow.check_takeoff"

    def execute(self, context: bpy.types.Context) -> set[str]:
        scene = context.scene

        drones = self.get_taken_off_drones(context, 1)
        if not drones:
            return {"CANCELLED"}

        check_result = apply_takeoff_check(drones, scene)
        if check_result is not None:
            self.report_print({"ERROR"}, check_result)
            return {"CANCELLED"}

        self.report_print({"INFO"}, "The takeoff check has successfully passed")
        return {"FINISHED"}


class LIGHTSHOW_OT_check_autopilot_format(CheckBase):
    bl_label = "Check autopilot format"
    bl_description = "Check if the selected drones respect the autopilot format"
    bl_idname = "lightshow.check_autopilot_format"

    def execute(self, context: bpy.types.Context) -> set[str]:
        scene = context.scene

        drones = self.get_taken_off_drones(context, 1)
        if not drones:
            return {"CANCELLED"}

        check_result = apply_autopilot_format_check(drones, scene)
        if check_result is not None:
            self.report_print({"ERROR"}, check_result)
            return {"CANCELLED"}

        self.report_print({"INFO"}, "The autopilot format check has successfully passed")
        return {"FINISHED"}


classes = [
    LIGHTSHOW_PT_other_checks,
    LIGHTSHOW_OT_check_dance_size,
    LIGHTSHOW_OT_check_takeoff,
    LIGHTSHOW_OT_check_autopilot_format,
]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in classes:
        bpy.utils.unregister_class(cls)
