import bpy
import numpy as np
from mathutils import Color

from ..base import BaseOperator
from ..setup import FPS, get_lightshow
from ..tools.collection_tools import get_selected_drones, get_selected_drones_or_all
from ..tools.color_tools import (
    animate_emission_color,
    check_color_keyframes_consistency,
    get_color_fcurves,
    get_colors_keyframes,
    get_keyframes_color,
    pick_color,
    set_keyframes_color,
    swap_color,
)
from ..tools.fcurve_tools import change_interpolation
from ..tools.tutorial_links_tools import draw_tutorial_button, link
from .color import ColorBasePanel


class LIGHTSHOW_PT_set_color(ColorBasePanel):
    bl_label = "Set color"
    bl_idname = "LIGHTSHOW_PT_set_color"
    bl_parent_id = "LIGHTSHOW_PT_color"
    bl_options = {"HIDE_HEADER"}

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        scene = context.scene
        lightshow = get_lightshow(scene)

        row = layout.row()
        row.prop(lightshow, "color")
        pick_color = row.operator("lightshow.pick_color", icon="EYEDROPPER", text="")
        pick_color.color_prop_name = "color"  # pyright: ignore

        draw_tutorial_button(
            layout,
            context,
            main_button_fn=lambda col: col.prop(lightshow, "color_duration", slider=True),
            section=link.color.set_color,
            option="duration",
        )

        draw_tutorial_button(
            layout,
            context,
            main_button_fn=lambda col: col.prop(lightshow, "interpolation"),
            section=link.color.set_color,
            option="interpolation",
        )

        layout.operator("lightshow.set_color")

        layout.operator("lightshow.change_interpolation")

        row = layout.row()
        row.prop(lightshow, "new_color")
        pick_color = row.operator("lightshow.pick_color", icon="EYEDROPPER", text="")
        pick_color.color_prop_name = "new_color"  # pyright: ignore

        draw_tutorial_button(
            layout,
            context,
            main_button_fn=lambda col: col.operator("lightshow.swap_color"),
            section=link.color.set_color,
            option="swap_color",
        )

        layout.prop(lightshow, "brightness")
        draw_tutorial_button(
            layout,
            context,
            main_button_fn=lambda col: col.operator("lightshow.apply_brightness"),
            section=link.color.set_color,
            option="brightness",
        )

        draw_tutorial_button(
            layout,
            context,
            main_button_fn=lambda col: col.operator("lightshow.remove_white"),
            section=link.color.set_color,
            option="remove_white",
        )


class LIGHTSHOW_OT_set_color(BaseOperator):
    bl_label = "Set color"
    bl_description = "Set color of selected drones"
    bl_idname = "lightshow.set_color"

    def execute(self, context: bpy.types.Context) -> set[str]:
        scene = context.scene
        lightshow = get_lightshow(scene)

        # Add color transition
        frame_delta = round(lightshow.color_duration * FPS)

        drones = get_selected_drones(context)

        if len(drones) == 0:
            self.report_print({"ERROR"}, "No drone selected")
            return {"CANCELLED"}

        for drone in drones:
            animate_emission_color(
                drone,
                lightshow.color,
                frame_delta,
                lightshow.interpolation,
                lightshow.set_color_keyframe,
            )

        if not lightshow.set_color_marker or len(drones) <= 1:
            return {"FINISHED"}

        if frame_delta == 0:
            scene.timeline_markers.new("Set color", frame=scene.frame_current)
        else:
            scene.timeline_markers.new("Set color start", frame=scene.frame_current)
            scene.timeline_markers.new("Set color end", frame=scene.frame_current + frame_delta)

        return {"FINISHED"}


class LIGHTSHOW_OT_pick_color(BaseOperator):
    bl_label = "Pick color"
    bl_idname = "lightshow.pick_color"
    bl_description = """\
Pick color of the selected drone
The current frame must be on the color keyframe to pick the color"""

    color_prop_name: bpy.props.StringProperty()  # pyright: ignore

    def execute(self, context: bpy.types.Context) -> set[str]:
        scene = context.scene
        lightshow = get_lightshow(scene)

        drones = get_selected_drones(context)
        if len(drones) != 1:
            self.report_print({"ERROR"}, "Select one drone to pick color")
            return {"CANCELLED"}

        color = pick_color(drones[0], frame_current=scene.frame_current)
        if color is None:
            self.report_print({"WARNING"}, "No color keyframe found at current frame")
            return {"CANCELLED"}

        setattr(lightshow, self.color_prop_name, color)

        self.report_print({"INFO"}, "Color picked")

        return {"FINISHED"}


class LIGHTSHOW_OT_change_interpolation(BaseOperator):
    bl_label = "Change interpolation"
    bl_description = """\
Change the color interpolation on the current frame of the selected drones"""
    bl_idname = "lightshow.change_interpolation"

    def execute(self, context: bpy.types.Context) -> set[str]:
        scene = context.scene
        lightshow = get_lightshow(scene)
        for drone in get_selected_drones(context):
            rgbw_fcurves = get_color_fcurves(drone)
            if rgbw_fcurves is None:
                continue
            for fcurve in rgbw_fcurves:
                change_interpolation(fcurve, lightshow.interpolation, scene.frame_current)
        return {"FINISHED"}


class LIGHTSHOW_OT_swap_color(BaseOperator):
    bl_label = "Swap color"
    bl_idname = "lightshow.swap_color"
    bl_description = "Swap the color of selected drones"

    def execute(self, context: bpy.types.Context) -> set[str]:
        scene = context.scene
        lightshow = get_lightshow(scene)

        drones = get_selected_drones(context)

        if len(drones) == 0:
            self.report_print({"ERROR"}, "No drone selected")
            return {"CANCELLED"}

        nb_swapped = 0
        for drone in drones:
            nb_swapped += swap_color(
                drone,
                lightshow.color,
                lightshow.new_color,
                scene.frame_start,
                scene.frame_end,
            )

        if nb_swapped:
            self.report_print({"INFO"}, f"Swapped color {nb_swapped} times")
        else:
            self.report_print({"WARNING"}, "No color swapped")

        return {"FINISHED"}


class LIGHTSHOW_OT_remove_white(BaseOperator):
    bl_label = "Remove white"
    bl_description = """\
Set the white channel to 0.
Only for the selected drones (or all if none selected) on the keyframes inside the scene frame range"""
    bl_idname = "lightshow.remove_white"

    def execute(self, context: bpy.types.Context) -> set[str]:
        scene = context.scene
        drones = get_selected_drones_or_all(context)

        if len(drones) == 0:
            self.report_print({"ERROR"}, "No drone selected")
            return {"CANCELLED"}

        has_removed_white = False

        for drone in drones:
            rgbw_fcurves = get_color_fcurves(drone)
            if rgbw_fcurves is None:
                continue

            rgbw_keyframes = get_colors_keyframes(rgbw_fcurves)
            if rgbw_keyframes is None:
                continue

            for rgbw_keyframe in rgbw_keyframes:
                frame, _ = check_color_keyframes_consistency(rgbw_keyframe)
                if frame < scene.frame_start:
                    continue
                if frame > scene.frame_end:
                    break

                rgbw = get_keyframes_color(rgbw_keyframe)
                if np.isclose(rgbw[3], 0):
                    continue

                has_removed_white = True
                set_keyframes_color(rgbw_keyframe, (rgbw[0], rgbw[1], rgbw[2], 0))

        if has_removed_white:
            self.report_print({"INFO"}, "White removed")
        else:
            self.report_print({"INFO"}, "No white to removed")

        return {"FINISHED"}


class LIGHTSHOW_OT_apply_brightness(BaseOperator):
    bl_label = "Apply brightness"
    bl_description = """\
Apply a brightness on the selected drones color keyframes in the scene range.
The brightness is the V of the HSV color space.
WARNING: as the brightness maximum is 1, after applying the factor the relative brightness between color could be different"""
    bl_idname = "lightshow.apply_brightness"

    def execute(self, context: bpy.types.Context) -> set[str]:
        scene = context.scene
        lightshow = get_lightshow(scene)
        drones = get_selected_drones_or_all(context)

        if len(drones) == 0:
            self.report_print({"ERROR"}, "No drone selected")
            return {"CANCELLED"}

        has_brightness_been_clamped = False
        for drone in drones:
            rgbw_fcurves = get_color_fcurves(drone)
            if rgbw_fcurves is None:
                continue

            rgbw_keyframes = get_colors_keyframes(rgbw_fcurves)
            if rgbw_keyframes is None:
                continue

            for rgbw_keyframe in rgbw_keyframes:
                frame, _ = check_color_keyframes_consistency(rgbw_keyframe)
                if frame < scene.frame_start:
                    continue
                if frame > scene.frame_end:
                    break

                rgbw = get_keyframes_color(rgbw_keyframe)

                color = Color(rgbw[:3])
                brightness = 0.1 if lightshow.brightness == 0 else lightshow.brightness
                new_v = brightness / 100
                color.v = new_v
                if new_v > 1:
                    has_brightness_been_clamped = True

                set_keyframes_color(rgbw_keyframe, (color[0], color[1], color[2], rgbw[3]))

        if has_brightness_been_clamped:
            self.report_print(
                {"WARNING"},
                "Applied brightness, but the brightness was clamped for some keyframes",
            )
        else:
            self.report_print({"INFO"}, "Successfully applied brightness")

        return {"FINISHED"}


classes = [
    LIGHTSHOW_PT_set_color,
    LIGHTSHOW_OT_set_color,
    LIGHTSHOW_OT_pick_color,
    LIGHTSHOW_OT_change_interpolation,
    LIGHTSHOW_OT_swap_color,
    LIGHTSHOW_OT_remove_white,
    LIGHTSHOW_OT_apply_brightness,
]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in classes:
        bpy.utils.unregister_class(cls)
