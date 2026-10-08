import bpy

from ....base import BaseOperator
from ....setup import get_lightshow
from ....tools.collection_tools import is_drone
from ....tools.tutorial_links_tools import draw_tutorial_button, link
from ..mesh_base import MeshBasePanel
from .utils import (
    add_anchors_to_rigged_mesh,
    apply_mesh_to_points,
    cancel_mesh_to_points,
    preview_mesh_to_points,
)


class LIGHTSHOW_PT_mesh_converter(MeshBasePanel):
    bl_label = "Mesh Converter"
    bl_idname = "LIGHTSHOW_PT_mesh_converter"
    bl_parent_id = "LIGHTSHOW_PT_mesh_base"
    bl_options = {"HIDE_HEADER"}

    def draw(self, context: bpy.types.Context) -> None:
        lightshow = get_lightshow(context.scene)
        layout = self.layout

        draw_tutorial_button(
            layout,
            context,
            main_button_fn=None,
            section=link.formation.mesh.mesh_converter,
            option="",
            text="Help with Mesh Converter",
        )

        layout.prop(lightshow, "mesh_converter_object")

        obj = lightshow.mesh_converter_object
        if (
            obj is not None
            and obj.modifiers.get("Geometry Nodes") is not None
            and not is_drone(obj)
        ):
            layout.label(
                text=f"Number of vertices: {len(obj.evaluated_get(context.evaluated_depsgraph_get()).data.vertices)}"
            )

            layout.prop(lightshow, "mesh_converter_distance")
            row = layout.row()
            row.prop(lightshow, "mesh_converter_is_rigged")
            row.prop(lightshow, "mesh_converter_seed")
            row = layout.row()
            if lightshow.mesh_converter_is_rigged:
                row.operator("lightshow.mesh_converter_apply_on_rigged_mesh")
                row.operator("lightshow.delete_anchors")
                layout.operator("lightshow.mesh_converter_cancel")
            else:
                row.operator("lightshow.mesh_converter_apply")
                row.operator("lightshow.mesh_converter_cancel")

        else:
            layout.operator("lightshow.mesh_converter_preview")


class LIGHTSHOW_OT_mesh_converter_preview(BaseOperator):
    bl_label = "Preview"
    bl_description = """\
Preview the conversion of the selected 3D mesh to formation"""
    bl_idname = "lightshow.mesh_converter_preview"

    def execute(self, context: bpy.types.Context) -> set[str]:
        lightshow = get_lightshow(context.scene)
        obj = lightshow.mesh_converter_object
        if obj is None or obj.type != "MESH":
            self.report({"ERROR"}, "No mesh object selected")
            return {"CANCELLED"}

        # Preview mesh to points conversion
        preview_mesh_to_points(context)

        return {"FINISHED"}


class LIGHTSHOW_OT_mesh_converter_apply(BaseOperator):
    bl_label = "Apply"
    bl_description = """Apply the conversion of the selected 3D mesh to formation"""
    bl_idname = "lightshow.mesh_converter_apply"

    def execute(self, context: bpy.types.Context) -> set[str]:
        lightshow = get_lightshow(context.scene)
        obj = lightshow.mesh_converter_object
        if obj is None or obj.type != "MESH":
            self.report({"ERROR"}, "No mesh object selected")
            return {"CANCELLED"}

        apply_mesh_to_points(context)

        lightshow.mesh_converter_object = None

        return {"FINISHED"}


class LIGHTSHOW_OT_mesh_converter_apply_on_rigged_mesh(BaseOperator):
    bl_label = "Add anchors"
    bl_description = """Add anchors to the points of the selected rigged 3D mesh within the selected frame range"""
    bl_idname = "lightshow.mesh_converter_apply_on_rigged_mesh"

    def execute(self, context: bpy.types.Context) -> set[str]:
        lightshow = get_lightshow(context.scene)
        obj = lightshow.mesh_converter_object
        if obj is None or obj.type != "MESH":
            self.report({"ERROR"}, "No mesh object selected")
            return {"CANCELLED"}

        add_anchors_to_rigged_mesh(context)

        lightshow.mesh_converter_object = None

        return {"FINISHED"}


class LIGHTSHOW_OT_mesh_converter_cancel(BaseOperator):
    bl_label = "Cancel"
    bl_description = """\
Cancel the conversion of the selected 3D mesh to formation"""
    bl_idname = "lightshow.mesh_converter_cancel"

    def execute(self, context: bpy.types.Context) -> set[str]:
        lightshow = get_lightshow(context.scene)
        obj = lightshow.mesh_converter_object
        if obj is None or obj.type != "MESH":
            self.report({"ERROR"}, "No mesh object selected")
            return {"CANCELLED"}

        # Cancel mesh to points conversion
        cancel_mesh_to_points(context)

        return {"FINISHED"}


classes = [
    LIGHTSHOW_PT_mesh_converter,
    LIGHTSHOW_OT_mesh_converter_preview,
    LIGHTSHOW_OT_mesh_converter_apply,
    LIGHTSHOW_OT_mesh_converter_apply_on_rigged_mesh,
    LIGHTSHOW_OT_mesh_converter_cancel,
]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in classes:
        bpy.utils.unregister_class(cls)
