import bpy

from .color_effect_base import ColorEffectPanel
from .color_effects_list import color_effects, color_effects_beta


def make_color_effect_panels(effects: list[str]) -> list[type]:
    classes = []
    for effect_label in effects:
        cls_name = f"LIGHTSHOW_PT_{effect_label.replace(' ', '_')}_color_effect"
        bl_idname = cls_name
        attrs = {
            "bl_label": effect_label,
            "bl_idname": bl_idname,
            "bl_parent_id": "LIGHTSHOW_PT_color_effect",
            "bl_options": {"HIDE_HEADER"},
        }
        panel_cls = type(cls_name, (ColorEffectPanel,), attrs)
        classes.append(panel_cls)
    return classes


_color_effect_panels = make_color_effect_panels(color_effects + color_effects_beta)


def register() -> None:
    for cls in _color_effect_panels:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(_color_effect_panels):
        bpy.utils.unregister_class(cls)
