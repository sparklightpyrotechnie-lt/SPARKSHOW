import bpy

from ..base import BaseOperator
from ..setup import get_lightshow
from ..tools.collection_tools import add_collection, get_selected_mesh, get_visible_drones
from ..tools.color_tools import bake_color, create_emission_material, get_active_material_color
from ..tools.effector_tools import change_effector, register_update_effector_handler
from ..tools.scene_tools import refresh_scene
from ..tools.tutorial_links_tools import draw_tutorial_button, link
from .color import ColorBasePanel


class LIGHTSHOW_PT_magic_color(ColorBasePanel):
    bl_label = "Magic color"
    bl_idname = "LIGHTSHOW_PT_magic_color"
    bl_parent_id = "LIGHTSHOW_PT_color"
    bl_options = {"HIDE_HEADER"}

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        lightshow = get_lightshow(context.scene)

        draw_tutorial_button(
            layout,
            context,
            lambda col: col.operator("lightshow.add_emission_material"),
            section=link.color.magic_color,
        )

        layout.prop(lightshow, "effector_name")
        layout.prop(lightshow, "effector_type")
        if lightshow.effector_type == "FADED":
            layout.prop(lightshow, "effector_intensity")
        if lightshow.effector_type == "RANDOM":
            layout.prop(lightshow, "effector_frame_rate")
        layout.prop(lightshow, "effector_priority")
        layout.operator("lightshow.update_effector")
        layout.prop(lightshow, "baking_frame_step")
        layout.prop(lightshow, "baking_interpolation")
        layout.operator("lightshow.register_led")

        add_collection(
            "Effector", context.scene.collection
        )  # TODO(<PAG>): code à la mauvaise place, sortir de l'UI
        register_update_effector_handler()


class LIGHTSHOW_OT_add_emission_material(BaseOperator):
    bl_label = "Add emission material"
    bl_description = "Add an emission material to selected meshes"
    bl_idname = "lightshow.add_emission_material"

    def execute(self, context: bpy.types.Context) -> set[str]:
        scene = context.scene
        lightshow = get_lightshow(scene)
        for mesh in get_selected_mesh(context):
            create_emission_material(mesh, lightshow)
        return {"FINISHED"}


class LIGHTSHOW_OT_update_effector(BaseOperator):
    bl_label = "Update effector"
    bl_description = """\
Update the effector with the selected parameters
The effector will only be applied on the frame range of the scene
Without this update, the effector will not be applied on the drones"""
    bl_idname = "lightshow.update_effector"

    def execute(self, context: bpy.types.Context) -> set[str]:
        scene = context.scene
        lightshow = get_lightshow(scene)
        if lightshow.effector_name == "":
            self.report_print(
                {"ERROR"},
                "There is no selected name",
            )
            return {"CANCELLED"}
        change_effector(
            lightshow.effector_name,
            lightshow.effector_type,
            lightshow.effector_intensity,
            lightshow.effector_frame_rate,
            lightshow.effector_priority,
        )
        refresh_scene(scene)
        return {"FINISHED"}


class LIGHTSHOW_OT_register_led(BaseOperator):
    bl_label = "Register LED"
    bl_description = """\
Keyframe the color of the drones obtained from the effector
Without this registration, the color of the drones will not be preserved during the export
After the registration, the effectors should be moved off from Effector collection"""
    bl_idname = "lightshow.register_led"

    def execute(self, context: bpy.types.Context) -> set[str]:
        scene = context.scene
        lightshow = get_lightshow(scene)

        drones = get_visible_drones(scene.collection)

        if not drones:
            self.report_print({"ERROR"}, "No drone visible")
            return {"CANCELLED"}

        bake_color(
            context,
            drones,
            frame_start=scene.frame_start,
            frame_end=scene.frame_end,
            frame_step=lightshow.baking_frame_step,
            interpolation=lightshow.baking_interpolation,
            keyframe_type=lightshow.magic_color_keyframe,
            get_frame_data_fn=lambda: None,
            get_drone_color_fn=lambda drone, _: get_active_material_color(drone),
        )

        if lightshow.magic_color_marker and len(drones) > 1:
            scene.timeline_markers.new("Magic color start", frame=scene.frame_start)
            scene.timeline_markers.new("Magic color end", frame=scene.frame_end)

        return {"FINISHED"}


classes = [
    LIGHTSHOW_OT_update_effector,
    LIGHTSHOW_OT_register_led,
    LIGHTSHOW_OT_add_emission_material,
    LIGHTSHOW_PT_magic_color,
]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in classes:
        bpy.utils.unregister_class(cls)
