import bpy
import os
import bpy.utils.previews

from .tools.collection_tools import get_drones

_SECTION = {
    "show":     ("SHOW",     "SEQUENCE"),
    "lighting": ("LIGHTING", "LIGHT"),
    "pyro":     ("PYRO",     "LIGHT_POINT"),
    "synoptic": ("SYNOPTIC", "GRAPH"),
    "safety":   ("SAFETY",   "CHECKMARK"),
    "export":   ("EXPORT",   "EXPORT"),
}
_icons = None


def _icon_path(name: str) -> str:
    return os.path.join(os.path.dirname(__file__), "ui_icons", f"{name}.png")


def _ensure_icons():
    global _icons
    if _icons is not None:
        return _icons
    _icons = bpy.utils.previews.new()
    for key in _SECTION:
        path = _icon_path(key)
        if os.path.exists(path):
            _icons.load(f"sparkshow_{key}", path, 'IMAGE')
    return _icons



def _draw_card(layout, key: str, label: str, icon: str, *, closed=False):
    """Render a fixed Sparkshow section card.

    UI appearance is intentionally not user-configurable for now. The section
    cards and icons remain, but there are no scene controls for changing their
    colours or enabling a visual theme.
    """
    card = layout.box()
    header = card.row(align=True)
    header.scale_y = 1.35

    preview = _ensure_icons().get(f"sparkshow_{key}")
    if preview:
        header.template_icon(icon_value=preview.icon_id, scale=1.2)

    header.label(text=label, icon=icon)

    if closed:
        return card, card.column(align=True)

    body = card.column(align=True)
    body.separator(factor=0.10)
    return card, body


def _collection_count(name: str) -> int:
    col = bpy.data.collections.get(name)
    return len(col.objects) if col else 0


class SPARKSHOW_STUDIO_PT_show(bpy.types.Panel):
    bl_label = "SHOW"
    bl_idname = "SPARKSHOW_STUDIO_PT_show"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "sparkshow"
    bl_parent_id = "LIGHTSHOW_PT_main_panel"
    bl_options = set()

    def draw(self, context):
        scene = context.scene
        drones = get_drones(scene.collection)
        card, body = _draw_card(self.layout, "show", "SHOW", "SEQUENCE")
        body.use_property_split = True
        body.label(text=f"{len(drones):,} drones".replace(",", " "), icon="OBJECT_DATA")
        body.label(text=f"Frame {scene.frame_current}", icon="TIME")
        body.label(text="Formation / Transition / Takeoff / Landing / RTL", icon="OUTLINER_COLLECTION")


class SPARKSHOW_STUDIO_PT_lighting(bpy.types.Panel):
    bl_label = "LIGHTING"
    bl_idname = "SPARKSHOW_STUDIO_PT_lighting"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "sparkshow"
    bl_parent_id = "LIGHTSHOW_PT_main_panel"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        scene = context.scene
        props = getattr(scene, "color_properties", None)
        lightshow = getattr(scene, "lightshow", None)
        card, body = _draw_card(self.layout, "lighting", "LIGHTING", "LIGHT")
        body.label(text="Uniform · Palette · Gradient · Effects", icon="COLOR")
        if props is not None:
            body.label(text=f"Mode: {getattr(props, 'color_type', '—')}")
        preview = getattr(lightshow, "lighting_preview_enabled", None) if lightshow else None
        if preview is None and lightshow:
            preview = getattr(lightshow, "color_preview", False)
        if preview is not None:
            body.label(text=f"Preview: {'ON' if preview else 'OFF'}", icon="HIDE_OFF" if preview else "HIDE_ON")


class SPARKSHOW_STUDIO_PT_pyro(bpy.types.Panel):
    bl_label = "PYRO"
    bl_idname = "SPARKSHOW_STUDIO_PT_pyro"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "sparkshow"
    bl_parent_id = "LIGHTSHOW_PT_main_panel"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        scene = context.scene
        col = bpy.data.collections.get("Sparkshow Pyrotechnics")
        count = len(col.objects) if col else 0
        lightshow = getattr(scene, "lightshow", None)
        enabled = getattr(lightshow, "fire_preview_enabled", False) if lightshow else False
        renderer = getattr(lightshow, "fire_preview_renderer", "AUTO") if lightshow else "AUTO"
        card, body = _draw_card(self.layout, "pyro", "PYRO", "LIGHT_POINT")
        body.label(text=f"{count} preview objects", icon="PARTICLES")
        body.label(text=f"Preview: {'ON' if enabled else 'OFF'}", icon="HIDE_OFF" if enabled else "HIDE_ON")
        body.label(text=f"Engine: {renderer.title().replace('_', ' ')}", icon="GEOMETRY_NODES")
        body.label(text="Pyro is isolated in Sparkshow Pyrotechnics.", icon="COLLECTION_NEW")


class SPARKSHOW_STUDIO_PT_synoptic(bpy.types.Panel):
    bl_label = "SYNOPTIC"
    bl_idname = "SPARKSHOW_STUDIO_PT_synoptic"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "sparkshow"
    bl_parent_id = "LIGHTSHOW_PT_main_panel"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        card, body = _draw_card(self.layout, "synoptic", "SYNOPTIC", "GRAPH")
        body.label(text=f"Pyro events: {_collection_count('Sparkshow Pyrotechnics')}", icon="LIGHT_POINT")
        body.label(text=f"Pyro bake: {_collection_count('Sparkshow Pyro Bake')}", icon="CACHE")
        body.label(text="Independent scene objects; drone families remain untouched.", icon="INFO")


class SPARKSHOW_STUDIO_PT_safety(bpy.types.Panel):
    bl_label = "SAFETY"
    bl_idname = "SPARKSHOW_STUDIO_PT_safety"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "sparkshow"
    bl_parent_id = "LIGHTSHOW_PT_main_panel"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        scene = context.scene
        drones = get_drones(scene.collection)
        card, body = _draw_card(self.layout, "safety", "SAFETY", "CHECKMARK")
        body.label(text=f"Safety checks · {len(drones)} drones", icon="CHECKMARK")
        body.operator("lightshow.check_collisions", text="Run safety checks", icon="CHECKMARK")


class SPARKSHOW_STUDIO_PT_export(bpy.types.Panel):
    bl_label = "EXPORT"
    bl_idname = "SPARKSHOW_STUDIO_PT_export"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "sparkshow"
    bl_parent_id = "LIGHTSHOW_PT_main_panel"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        scene = context.scene
        card, body = _draw_card(self.layout, "export", "EXPORT", "EXPORT")
        body.label(text=f"Timeline: {scene.frame_start} → {scene.frame_end}", icon="TIME")
        body.label(text="Import / Export tools", icon="FILE_FOLDER")


classes = [
    SPARKSHOW_STUDIO_PT_show,
    SPARKSHOW_STUDIO_PT_lighting,
    SPARKSHOW_STUDIO_PT_pyro,
    SPARKSHOW_STUDIO_PT_synoptic,
    SPARKSHOW_STUDIO_PT_safety,
    SPARKSHOW_STUDIO_PT_export,
]


def register() -> None:
    _ensure_icons()
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    global _icons
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    if _icons is not None:
        bpy.utils.previews.remove(_icons)
        _icons = None
