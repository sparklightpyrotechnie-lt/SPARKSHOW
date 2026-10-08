import bpy

from ....base import BaseOperator
from ....setup import get_lightshow
from ....tools.follow_path_tools import add_anchors_with_follow_path
from ....tools.tutorial_links_tools import draw_tutorial_button, link
from ..mesh_base import MeshBasePanel


class LIGHTSHOW_PT_follow_path(MeshBasePanel):
    bl_label = "Follow path"
    bl_idname = "LIGHTSHOW_PT_follow_path"
    bl_parent_id = "LIGHTSHOW_PT_mesh_base"
    bl_options = {"HIDE_HEADER"}

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        scene = context.scene
        lightshow = get_lightshow(scene)

        layout.prop(lightshow, "follow_path_duration")
        layout.prop(lightshow, "follow_path_time_delta")
        layout.prop(lightshow, "follow_path_nb_anchors")
        draw_tutorial_button(
            layout,
            context,
            main_button_fn=lambda col: col.operator("lightshow.follow_path"),
            section=link.formation.mesh.follow_path,
            option="",
        )


class LIGHTSHOW_OT_follow_path(BaseOperator):
    bl_label = "Follow path"
    bl_description = """\
Add the selected number of anchors following the path of the selected curve.
The anchors will take the selected duration to move from the start to the end of the curve.
The time delta is the time between each anchor."""
    bl_idname = "lightshow.follow_path"

    def execute(self, context: bpy.types.Context) -> set[str]:
        scene = context.scene
        lightshow = get_lightshow(scene)

        curve_object = context.active_object

        if curve_object is None:
            self.report_print({"ERROR"}, "No curve selected")
            return {"CANCELLED"}

        if curve_object.type != "CURVE":
            self.report_print({"ERROR"}, f"{curve_object.name} is not a curve")
            return {"CANCELLED"}

        add_anchors_with_follow_path(
            scene,
            curve_object,
            scene.frame_current,
            lightshow.follow_path_duration,
            lightshow.follow_path_time_delta,
            lightshow.follow_path_nb_anchors,
        )

        return {"FINISHED"}


classes = [LIGHTSHOW_PT_follow_path, LIGHTSHOW_OT_follow_path]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
