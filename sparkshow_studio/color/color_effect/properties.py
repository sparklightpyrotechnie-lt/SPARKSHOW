import bpy

from .color_effects_list import color_effects, color_effects_beta
from .tools import enable_color_effect_preview

COLOR_EFFECT_ITEMS = [("NONE", "--", "No color effect")]
for effect in color_effects:
    identifier = f"{effect.upper()} COLOR EFFECT"
    label = effect.replace("_", " ").title()
    COLOR_EFFECT_ITEMS.append((identifier, label, f"{label} color effect"))

for effect in color_effects_beta:
    identifier = f"{effect.upper()} COLOR EFFECT"
    label = effect.replace("_", " ").title() + " (Beta)"
    COLOR_EFFECT_ITEMS.append((identifier, label, f"{label} color effect (beta)"))


class ColorEffectProperties(bpy.types.PropertyGroup):
    color_effect: bpy.props.EnumProperty(  # pyright: ignore
        name="Color Effect",
        description="Type of color effect to apply",
        items=COLOR_EFFECT_ITEMS,
        default="NONE",
        update=enable_color_effect_preview,
    )


classes = (ColorEffectProperties,)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)  # type: ignore
    bpy.types.Scene.color_effect_properties = bpy.props.PointerProperty(type=ColorEffectProperties)  # type: ignore


def unregister() -> None:
    del bpy.types.Scene.color_effect_properties  # pyright: ignore
    for cls in classes:
        bpy.utils.unregister_class(cls)  # type: ignore
