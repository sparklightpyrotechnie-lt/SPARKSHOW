from typing import TYPE_CHECKING, cast

import bpy

from ...base import BaseOperator, BasePanelHideIfNoDrone
from ...setup import get_lightshow
from ...tools.collection_tools import get_visible_drones
from ...tools.color_tools import RGBW, bake_color
from ...tools.tutorial_links_tools import draw_tutorial_button, link
from ..color import ColorBasePanel
from .tools import disable_color_effect_preview, is_color_effect_preview_enabled

if TYPE_CHECKING:
    from ...setup import Lightshow


class ColorEffectPanel(BasePanelHideIfNoDrone):
    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        scene = context.scene
        props = getattr(scene, "color_effect_properties", None)
        return props and cls.bl_idname == "LIGHTSHOW_PT_" + props.color_effect.lower().replace(
            " ", "_"
        )

    @staticmethod
    def draw_color_ramp(
        geometry_nodes: bpy.types.NodesModifier, layout: bpy.types.UILayout, bl_idname: str
    ) -> None:
        node_group = geometry_nodes.node_group
        node_name = " ".join(bl_idname.split("_")[2:]).upper()
        if not node_group or not node_group.name.endswith(node_name):
            layout.label(text=f"No '{node_name}' node group found in the Geometry Nodes modifier.")
        else:
            color_ramp_name = "Color Ramp"
            for name in node_group.nodes.keys():  # noqa: SIM118
                if name.lower().startswith("color ramp"):
                    color_ramp_name = name
                    break

            color_ramp_node = node_group.nodes.get(color_ramp_name)
            if not color_ramp_node:
                layout.label(text="ColorRamp not found in the node group.")
            else:
                layout.template_color_ramp(color_ramp_node, "color_ramp", expand=True)

    @staticmethod
    def draw_color_effect_controls(
        layout: bpy.types.UILayout,
        context: bpy.types.Context,
        lightshow: "Lightshow",
    ) -> None:
        layout.use_property_split = True
        layout.use_property_decorate = False

        if not is_color_effect_preview_enabled(context):
            draw_tutorial_button(
                layout,
                context,
                lambda col: col.operator("lightshow.preview_color_effect"),
                section=link.color_effect,
            )
        else:
            layout.prop(lightshow, "baking_frame_step")
            layout.prop(lightshow, "baking_interpolation")
            layout.operator("lightshow.save_color_effect")
            layout.operator("lightshow.cancel_preview_color_effect")

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        scene = context.scene
        lightshow = get_lightshow(scene)
        props = context.scene.color_effect_properties

        color_effect_object = bpy.data.objects.get(props.color_effect)
        geometry_nodes = None
        if color_effect_object:
            geometry_nodes = cast(
                bpy.types.NodesModifier | None, color_effect_object.modifiers.get("Geometry Nodes")
            )

        if geometry_nodes:
            self.draw_color_ramp(geometry_nodes, layout, self.bl_idname)

        self.draw_color_effect_controls(layout, context, lightshow)


class LIGHTSHOW_PT_color_effect_base(ColorBasePanel):
    bl_label = "Color effect"
    bl_idname = "LIGHTSHOW_PT_color_effect"
    bl_parent_id = "LIGHTSHOW_PT_color"
    bl_options = {"HIDE_HEADER"}

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        scene = context.scene
        props = scene.color_effect_properties

        layout.use_property_split = True
        layout.use_property_decorate = False

        if props.color_effect == "NONE":
            draw_tutorial_button(
                layout,
                context,
                main_button_fn=lambda col: col.prop(props, "color_effect"),
                section=link.color.color_effect,
                option="",
            )


class LIGHTSHOW_OT_cancel_preview_color_effect(BaseOperator):
    bl_label = "Cancel preview"
    bl_description = """\
Disable the color effect preview mode without registering the color.
"""
    bl_idname = "lightshow.cancel_preview_color_effect"

    def execute(self, context: bpy.types.Context) -> set[str]:
        disable_color_effect_preview(context)

        props = context.scene.color_effect_properties
        if props:
            props.color_effect = "NONE"

        return {"FINISHED"}


class LIGHTSHOW_OT_save_color_effect(BaseOperator):
    bl_label = "Register LED"
    bl_description = """\
Keyframe the color of the drones obtained from the Geometry Nodes.
Once the registration is done, the Geometry Nodes modifier is removed from the drones.
"""
    bl_idname = "lightshow.save_color_effect"

    def execute(self, context: bpy.types.Context) -> set[str]:
        scene = context.scene
        lightshow = get_lightshow(scene)
        drones = get_visible_drones(scene.collection)

        bake_color(
            context,
            drones,
            frame_start=scene.frame_start,
            frame_end=scene.frame_end,
            frame_step=lightshow.baking_frame_step,
            interpolation="LINEAR",
            keyframe_type=lightshow.magic_color_keyframe,
            get_frame_data_fn=lambda: context.evaluated_depsgraph_get(),
            get_drone_color_fn=lambda drone, depsgraph: cast(
                RGBW,
                tuple(
                    cast(
                        bpy.types.FloatColorAttribute,
                        cast(
                            bpy.types.Mesh,
                            cast(bpy.types.Object, drone.evaluated_get(depsgraph)).data,
                        ).attributes["Color"],
                    )
                    .data[0]
                    .color
                ),
            ),
        )

        disable_color_effect_preview(context)
        props = context.scene.color_effect_properties
        if props:
            props.color_effect = "NONE"

        return {"FINISHED"}


classes = [
    LIGHTSHOW_PT_color_effect_base,
    LIGHTSHOW_OT_cancel_preview_color_effect,
    LIGHTSHOW_OT_save_color_effect,
]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in classes:
        bpy.utils.unregister_class(cls)
