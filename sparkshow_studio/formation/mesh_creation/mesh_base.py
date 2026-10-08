from typing import TYPE_CHECKING, cast

import bpy
import numpy as np

from ...base import BaseOperator, BasePanelHideIfNoDrone
from ...setup import get_lightshow
from ...tools.collection_tools import (
    add_anchor,
    get_collection_by_object,
    get_selected_others,
    is_anchor,
    is_drone,
)
from ...tools.geometry_tools import get_anchors_min_distance
from ...tools.tutorial_links_tools import draw_tutorial_button, link

if TYPE_CHECKING:
    from ...setup import Lightshow


class LIGHTSHOW_PT_mesh_base(BasePanelHideIfNoDrone):
    bl_label = "Mesh"
    bl_idname = "LIGHTSHOW_PT_mesh_base"
    bl_parent_id = "LIGHTSHOW_PT_formation"
    bl_order = 0

    def draw(self, context: bpy.types.Context) -> None:  # noqa: C901, PLR0912
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        lightshow = get_lightshow(context.scene)

        props = getattr(context.scene, "mesh_properties", None)
        if props is None:
            layout.label(text="Mesh properties not found", icon="ERROR")
            return

        draw_tutorial_button(
            layout,
            context,
            main_button_fn=None,
            section=link.formation.mesh,
        )

        obj = context.active_object
        if (
            obj is not None
            and obj.select_get()
            and not is_drone(obj)
            and obj.type in ["MESH", "CURVE"]
        ):
            if not any(is_anchor(child) for child in obj.children):
                if obj.type == "MESH":
                    assert obj.data is not None, "Mesh data is None"
                    nb_vertices = len(cast("bpy.types.Mesh", obj.data).vertices)
                else:  # CURVE
                    assert obj.data is not None, "Curve data is None"
                    nb_vertices = sum(
                        [
                            len(cast("bpy.types.Spline", spline).points)
                            for spline in cast("bpy.types.Curve", obj.data).splines
                        ]
                    )
                if nb_vertices > lightshow.nb_drones:
                    layout.label(
                        text="Many anchors will be created",
                        icon="ERROR",
                    )
                    layout.label(
                        text=f"{nb_vertices} anchors selected for {lightshow.nb_drones} drones.",
                    )
                draw_tutorial_button(
                    layout,
                    context,
                    lambda col: col.operator("lightshow.add_anchors", text="Add anchors"),
                    section=link.mesh,
                )

            anchors_min_distance = get_anchors_min_distance(obj)
            if anchors_min_distance is not None:
                if anchors_min_distance <= lightshow.collision_distance:
                    layout.label(text="Collision", icon="ERROR")
                elif anchors_min_distance <= lightshow.collision_distance * np.sqrt(2):
                    layout.label(text="Possible future collisions during transitions", icon="ERROR")

                if np.isclose(anchors_min_distance, lightshow.min_anchors_distance):
                    layout.prop(lightshow, "min_anchors_distance")
                else:
                    layout.operator("lightshow.refresh_min_anchors_distance")

            if get_selected_others(context):
                layout.operator("lightshow.set_position")
        else:
            row = layout.row()
            row.label(text="Select a mesh object to continue", icon="ERROR")
        layout.prop(props, "mesh_types", text="Creation Mode")


def update_min_anchors_distance(obj: bpy.types.Object, lightshow: "Lightshow") -> None:
    """Update the minimum distance between anchors of the object in the lightshow property group."""
    anchors_min_distance = get_anchors_min_distance(obj)
    if anchors_min_distance is not None:
        lightshow.min_anchors_distance = anchors_min_distance


class LIGHTSHOW_OT_add_anchors(BaseOperator):
    bl_label = "Add anchors"
    bl_description = """\
Add anchors on the vertices / points of the active object (mesh or curve).
In Object mode, anchors will be added on all vertices / points of the object.
In Edit mode, anchors will be added on selected vertices / points.
The anchors will be used as targets for the drones
The active object will be scaled to respect the minimum distance between anchors"""
    bl_idname = "lightshow.add_anchors"

    def execute(self, context: bpy.types.Context) -> set[str]:  # noqa: C901
        scene = context.scene
        lightshow = get_lightshow(scene)
        obj = context.active_object
        assert obj is not None
        if is_drone(obj):
            return {"CANCELLED"}

        associated_collection = get_collection_by_object(scene.collection, obj)
        if associated_collection is None:
            return {"CANCELLED"}

        in_object_mode = obj.mode == "OBJECT"

        if obj.type == "MESH":
            if in_object_mode:
                bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.remove_doubles()
            bpy.ops.object.mode_set(mode="OBJECT")

            for v in cast("bpy.types.Mesh", obj.data).vertices:
                if in_object_mode or v.select:
                    add_anchor(obj, associated_collection, parent_vertex_index=v.index)
        elif obj.type == "CURVE":
            if not in_object_mode:
                bpy.ops.object.mode_set(mode="OBJECT")

            index = 0
            # Do not add points for non-bezier splines because the points of the spline are not on the spline
            for spline in cast("bpy.types.Curve", obj.data).splines:
                if spline.type != "BEZIER":
                    index += len(spline.points)
                for bp in spline.bezier_points:
                    if in_object_mode or bp.select_control_point:
                        add_anchor(obj, associated_collection, parent_vertex_index=index)
                    index += 1

        update_min_anchors_distance(obj, lightshow)

        return {"FINISHED"}


class LIGHTSHOW_OT_refresh_min_anchors_distance(BaseOperator):
    bl_label = "Refresh min distance"
    bl_description = """\
Refresh the minimum distance between anchors of the active object (mesh or curve)."""
    bl_idname = "lightshow.refresh_min_anchors_distance"

    def execute(self, context: bpy.types.Context) -> set[str]:
        obj = context.active_object
        assert obj is not None
        lightshow = get_lightshow(context.scene)
        update_min_anchors_distance(obj, lightshow)

        return {"FINISHED"}


class LIGHTSHOW_OT_set_position(BaseOperator):
    bl_label = "Set position"
    bl_description = """\
Keyframe the position, rotation, and scale of selected objects other than drones"""
    bl_idname = "lightshow.set_position"

    def execute(self, context: bpy.types.Context) -> set[str]:
        for obj in get_selected_others(context):
            obj.keyframe_insert(data_path="location")
            rotation_mode = obj.rotation_mode
            if rotation_mode == "QUATERNION":
                obj.keyframe_insert(data_path="rotation_quaternion")
            elif rotation_mode == "AXIS_ANGLE":
                obj.keyframe_insert(data_path="rotation_axis_angle")
            else:
                obj.keyframe_insert(data_path="rotation_euler")
            obj.keyframe_insert(data_path="scale")

        return {"FINISHED"}


class LIGHTSHOW_OT_delete_anchors(BaseOperator):
    bl_label = "Delete anchors"
    bl_description = """\
Delete all anchors of the active object"""
    bl_idname = "lightshow.delete_anchors"

    def execute(self, context: bpy.types.Context) -> set[str]:
        lightshow = get_lightshow(context.scene)
        obj = lightshow.mesh_converter_object
        if is_drone(obj):
            return {"CANCELLED"}

        for child in obj.children:
            if is_anchor(child):
                bpy.data.objects.remove(child, do_unlink=True)

        return {"FINISHED"}


class MeshBasePanel(BasePanelHideIfNoDrone):
    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        scene = context.scene
        props = getattr(scene, "mesh_properties", None)
        return props and cls.bl_idname == "LIGHTSHOW_PT_" + props.mesh_types.lower().replace(
            " ", "_"
        )


classes = (
    LIGHTSHOW_PT_mesh_base,
    LIGHTSHOW_OT_add_anchors,
    LIGHTSHOW_OT_refresh_min_anchors_distance,
    LIGHTSHOW_OT_set_position,
    LIGHTSHOW_OT_delete_anchors,
)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
