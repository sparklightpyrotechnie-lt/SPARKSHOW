import bpy

from sparkshow_studio._loader.schemas.matrix import get_matrix

from ..base import BaseOperator, BasePanel
from ..setup import get_drone_repartitions, get_lightshow, set_drone_repartition
from ..tools.collection_tools import are_drones_initialized
from ..tools.grid_tools import (
    create_drone_grid,
    is_drone_grid_initialized,
    remove_drone_grid,
    update_drone_grid,
)
from ..tools.scene_tools import clean_scene, get_nb_drones_to_create, init_scene, init_show
from ..tools.tutorial_links_tools import draw_tutorial_button, link
from .compass.compass import add_compass_handlers

NB_MAX_DRONES = 10_000


class LIGHTSHOW_PT_init_show(BasePanel):
    bl_parent_id = "SPARKSHOW_STUDIO_PT_show"
    bl_label = "Initialize show"
    bl_idname = "LIGHTSHOW_PT_init_show"
    bl_options = set()

    def draw_header(self, context: bpy.types.Context) -> None:  # noqa: ARG002
        layout: bpy.types.UILayout = self.layout
        layout.label(icon="SEQUENCE")

    def draw(self, context: bpy.types.Context) -> None:  # noqa: PLR0915
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        scene = context.scene
        scene_collection = scene.collection
        lightshow = get_lightshow(scene)
        platform_props = getattr(scene, "platform_props", None)
        assert platform_props is not None, "Platform properties not found in the scene"

        is_in_drone_grid_preview = is_drone_grid_initialized(scene_collection)
        is_show_initialized = are_drones_initialized(scene_collection)

        if is_show_initialized:
            mode = (
                "Standard"
                if lightshow.takeoff_mode == "standard_takeoff"
                else "All in one platform"
            )
            layout.label(text=f"Mode: {mode}", icon="LOCKED")

            row = layout.row()
            row.prop(lightshow, "nb_drones")
            row.operator("lightshow.change_repartion")
            row.enabled = False

            layout.label(
                text=f"Nb Drones Per Family: {lightshow.nb_drones_per_family}", icon="LOCKED"
            )
            if lightshow.takeoff_mode != "using all in one platform":
                layout.label(text=f"Step: {lightshow.step_x}", icon="LOCKED")

            layout.label(text=f"Nb X: {lightshow.nb_x}", icon="LOCKED")

            layout.label(text=f"Nb Y: {lightshow.nb_y}", icon="LOCKED")
            layout.label(
                text=f"Angle Takeoff: {(lightshow.angle_takeoff * 180 / 3.141592):.2f}°",
                icon="LOCKED",
            )
        elif is_in_drone_grid_preview:
            draw_tutorial_button(
                layout,
                context,
                lambda col: col.prop(lightshow, "takeoff_mode"),
                section=link.initialize_the_show,
                option="takeoff_mode",
            )
            row = layout.row()
            row.prop(lightshow, "nb_drones")
            row.operator("lightshow.change_repartion")
            if lightshow.takeoff_mode == "using all in one platform":
                layout.label(
                    text=f"Nb Drones Per Family: {platform_props.nb_drones_per_platform}",
                    icon="LOCKED",
                )
                row = layout.row()
                row.prop(lightshow, "installation_gap")
            else:
                draw_tutorial_button(
                    layout,
                    context,
                    lambda col: col.prop(lightshow, "nb_drones_per_family"),
                    section=link.initialize_the_show.family,
                )
                layout.prop(lightshow, "step_x")
            layout.prop(lightshow, "nb_x")
            layout.prop(lightshow, "nb_y")
            layout.prop(lightshow, "angle_takeoff")

            is_drone_repartition_valid = (
                lightshow.nb_drones
                == lightshow.nb_x * lightshow.nb_y * lightshow.nb_drones_per_family
            )

            if not is_drone_repartition_valid:
                layout.label(text="No repartitions found", icon="ERROR")
            elif not is_show_initialized:
                draw_tutorial_button(
                    layout,
                    context,
                    lambda col: col.operator("lightshow.init_show"),
                    section=link.initialize_the_show,
                )
        else:
            col = layout.column()
            col.operator("lightshow.prepare_scene")

        row = layout.row()
        row.prop(lightshow, "takeoff_keyframe")
        row.prop(lightshow, "takeoff_marker", text="")
        row = layout.row()
        row.prop(lightshow, "land_keyframe")
        row.prop(lightshow, "land_marker", text="")
        row = layout.row()
        row.prop(lightshow, "go_to_target_keyframe")
        row.prop(lightshow, "go_to_target_marker", text="")
        row = layout.row()
        row.prop(lightshow, "set_color_keyframe")
        row.prop(lightshow, "set_color_marker", text="")
        row = layout.row()
        row.prop(lightshow, "magic_color_keyframe")
        row.prop(lightshow, "magic_color_marker", text="")
        row = layout.row()
        row.prop(lightshow, "fire_keyframe")
        row.prop(lightshow, "fire_marker", text="")
        if is_show_initialized and "Compass" not in bpy.data.objects:
            layout.operator("lightshow.add_compass", text="🧭 Add Compass")


class LIGHTSHOW_OT_prepare_scene(BaseOperator):
    bl_label = "Prepare the scene"
    bl_description = """\
Remove all objects from the scene and create the drone grid"""
    bl_idname = "lightshow.prepare_scene"

    def execute(self, context: bpy.types.Context) -> set[str]:
        scene = context.scene

        clean_scene(scene)
        init_scene(context)
        create_drone_grid(scene.collection)
        update_drone_grid(get_lightshow(scene), context)
        try:
            add_compass_handlers()
        except RuntimeError:
            self.report_print(
                {"ERROR"},
                "Failed to add compass",
            )

        return {"FINISHED"}


class LIGHTSHOW_OT_change_repartion(BaseOperator):
    bl_label = "✱"
    bl_description = """\
Change the drone repartition (Nb X, Nb Y) of the families
The repartition is changed cyclically
If no repartition is found, try changing the number of drones per family or the number of drones"""
    bl_idname = "lightshow.change_repartion"

    def execute(self, context: bpy.types.Context) -> set[str]:
        scene = context.scene
        lightshow = get_lightshow(scene)

        lightshow.drone_repartition_index += 1

        drone_repartitions = get_drone_repartitions(
            lightshow.nb_drones,
            lightshow.nb_drones_per_family,
        )

        if drone_repartitions is None:
            self.report_print({"ERROR"}, "No repartitions found")
            return {"CANCELLED"}

        lightshow.drone_repartition_index = lightshow.drone_repartition_index % len(
            drone_repartitions,
        )
        set_drone_repartition(lightshow, drone_repartitions[lightshow.drone_repartition_index])

        return {"FINISHED"}


class LIGHTSHOW_OT_init_show(BaseOperator):
    bl_label = "Initialize the show"
    bl_description = """\
Initialize the show with the current parameters
Once the show is initialized, the parameters can't be changed"""
    bl_idname = "lightshow.init_show"

    def execute(self, context: bpy.types.Context) -> set[str]:
        scene = context.scene
        lightshow = get_lightshow(scene)

        if (nb_drones_to_create := get_nb_drones_to_create(lightshow)) > NB_MAX_DRONES:
            self.report_print(
                {"ERROR"},
                f"Too many drones to create ({nb_drones_to_create} > {NB_MAX_DRONES})",
            )
            return {"CANCELLED"}

        init_show(
            scene,
            get_matrix(
                nb_x=lightshow.nb_x,
                nb_y=lightshow.nb_y,
                nb_drones_per_family=lightshow.nb_drones_per_family,
            ),
        )
        remove_drone_grid(scene.collection)
        lightshow.takeoff_altitude = lightshow.nb_drones_per_family * 2

        return {"FINISHED"}


classes = [
    LIGHTSHOW_PT_init_show,
    LIGHTSHOW_OT_prepare_scene,
    LIGHTSHOW_OT_change_repartion,
    LIGHTSHOW_OT_init_show,
]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in classes:
        bpy.utils.unregister_class(cls)
