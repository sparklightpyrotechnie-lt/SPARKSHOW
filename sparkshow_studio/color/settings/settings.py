import bpy

from ...base import BaseOperator, BasePanelHideIfNoDrone
from ...setup import get_lightshow
from ...tools.tutorial_links_tools import draw_tutorial_button, link


class LIGHTSHOW_PT_color_settings(BasePanelHideIfNoDrone):
    bl_label = "Settings"
    bl_idname = "LIGHTSHOW_PT_color_settings"
    bl_parent_id = "LIGHTSHOW_PT_color"

    def draw(self, context: bpy.types.Context) -> None:
        lightshow = get_lightshow(context.scene)
        layout = self.layout
        layout.use_property_decorate = False
        layout.use_property_split = True

        props = getattr(context.scene, "color_settings", None)
        if props is None:
            layout.label(text="Color settings not found!", icon="ERROR")
            layout.label(text="Enable the Sparkshow Creator add-on.")
            return

        row = layout.row(align=True)
        if props.enabled:
            row.operator(
                "lightshow.remove_lights_glow",
                text="Disable Glow",
                icon="X",
            )
        else:
            row.operator("lightshow.set_lights_glow", text="Enable Glow", icon="LIGHT")

        layout.separator()

        draw_tutorial_button(
            layout,
            context,
            lambda col: col.prop(lightshow, "emission_strength", text="Intensité simulation", slider=True),
            section=link.color.color_settings,
        )


def setup_glare_compositor() -> None:
    scene = bpy.context.scene
    scene.use_nodes = True
    tree = scene.node_tree
    nodes = tree.nodes
    links = tree.links
    nodes.clear()

    # Add input/output nodes
    rl = nodes.new(type="CompositorNodeRLayers")
    comp = nodes.new(type="CompositorNodeComposite")
    rl.location = (-300, 0)
    comp.location = (300, 0)

    # Blender 4.1 does not expose the old BLOOM mode.
    # FOG_GLOW is the supported glow mode in CompositorNodeGlare.
    # Blender 4.1 also exposes Size, Threshold and Mix as node properties,
    # not as input sockets.
    glare = nodes.new(type="CompositorNodeGlare")
    glare.location = (0, 0)
    glare.label = "Sparkshow Glow"
    glare.glare_type = "FOG_GLOW"
    glare.quality = "MEDIUM"
    glare.threshold = 0.15
    glare.size = 7
    glare.mix = 0.0
    links.new(rl.outputs["Image"], glare.inputs["Image"])
    links.new(glare.outputs["Image"], comp.inputs["Image"])


def remove_glare_compositor() -> None:
    scene = bpy.context.scene
    if not scene.use_nodes:
        return

    scene.node_tree.nodes.clear()
    scene.use_nodes = False


def enable_viewport_compositor_always(context: "bpy.types.Context") -> None:
    props = getattr(context.scene, "color_settings", None)
    props.previous_shading_type = context.space_data.shading.type
    props.previous_use_compositor = context.space_data.shading.use_compositor

    for area in context.screen.areas:
        if area.type == "VIEW_3D":
            space = area.spaces.active
            space.shading.type = "RENDERED"
            space.shading.use_compositor = "ALWAYS"


def disable_viewport_compositor(context: "bpy.types.Context") -> None:
    props = getattr(context.scene, "color_settings", None)
    if props:
        context.space_data.shading.type = props.previous_shading_type
        context.space_data.shading.use_compositor = props.previous_use_compositor
    else:
        context.space_data.shading.type = "MATERIAL"
        context.space_data.shading.use_compositor = False


def set_background_color(
    context: "bpy.types.Context", color: tuple[float, float, float, float]
) -> None:
    props = getattr(context.scene, "color_settings", None)
    world = context.scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        bpy.context.scene.world = world

    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        props.previous_background_color = bg.inputs[0].default_value
        bg.inputs[0].default_value = color


def reset_background_color(context: "bpy.types.Context") -> None:
    props = getattr(context.scene, "color_settings", None)
    world = context.scene.world
    if world is None:
        return

    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg and props:
        bg.inputs[0].default_value = props.previous_background_color
    else:
        bg.inputs[0].default_value = (0.1, 0.1, 0.1, 1.0)  # Default to a dark gray color


class LIGHTSHOW_OT_set_lights_glow(BaseOperator):
    bl_idname = "lightshow.set_lights_glow"
    bl_label = "Set Lights Glow"
    bl_description = "Set the glow of the lights in the scene"

    def execute(self, context: bpy.types.Context) -> set[str]:
        props = getattr(context.scene, "color_settings", None)
        setup_glare_compositor()
        enable_viewport_compositor_always(context)
        set_background_color(
            context, (0.0, 0.0, 0.0, 1.0)
        )  # Set background color to black with full opacity
        props.enabled = True
        return {"FINISHED"}


class LIGHTSHOW_OT_remove_lights_glow(BaseOperator):
    bl_idname = "lightshow.remove_lights_glow"
    bl_label = "Remove Lights Glow"
    bl_description = "Remove the glow of the lights in the scene"

    def execute(self, context: bpy.types.Context) -> set[str]:
        props = getattr(context.scene, "color_settings", None)
        remove_glare_compositor()
        disable_viewport_compositor(context)
        reset_background_color(context)
        props.enabled = False
        return {"FINISHED"}


classes = [
    LIGHTSHOW_OT_set_lights_glow,
    LIGHTSHOW_OT_remove_lights_glow,
    LIGHTSHOW_PT_color_settings,
]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in classes:
        bpy.utils.unregister_class(cls)
