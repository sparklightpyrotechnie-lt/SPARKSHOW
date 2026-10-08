from math import ceil
from typing import ClassVar

import bpy

from ..base import BaseOperator, BasePanelHideIfNoDrone
from ..setup import FPS, get_lightshow
from ..tools.collection_tools import get_selected_drones
from ..tools.fcurve_tools import find_fcurve_or_none, get_frame, get_len
from ..tools.tutorial_links_tools import draw_tutorial_button, link
from .utils import keyframe_fire


class FireBase(BaseOperator):
    fire_index: ClassVar[int]

    def execute(self, context: bpy.types.Context) -> set[str]:
        scene = context.scene
        lightshow = get_lightshow(scene)
        duration_ms = round(lightshow.fire_duration * 1000)
        duration_frame = ceil(duration_ms * FPS / 1000)

        frame = scene.frame_current

        drones = get_selected_drones(context)
        if not drones:
            self.report_print({"ERROR"}, "No drone selected")
            return {"CANCELLED"}

        # TODO(jonathan): Check if there is no fire event during the duration of the fire
        for drone in drones:
            taken_frames: set[int] = set()
            for i in range(3):
                fcurve = find_fcurve_or_none(drone, '["fire"]', i)
                if fcurve is not None:
                    for j in range(get_len(fcurve)):
                        taken_frames.add(get_frame(fcurve, j))

            if frame in taken_frames:
                self.report_print(
                    {"ERROR"},
                    f"There is already a fire event on the frame {frame}",
                )
                while frame in taken_frames:
                    frame += 1
                scene.frame_set(frame)
                return {"CANCELLED"}

        for drone in drones:
            keyframe_fire(
                drone,
                self.fire_index,
                frame,
                duration_ms,
                lightshow.fire_keyframe,
                lightshow.fire_vdl,
            )

            self.report_print(
                {"INFO"},
                f"{drone.name} Fire {self.fire_index} from frame {frame} to {frame + duration_frame}",
            )

        if lightshow.fire_marker and len(drones) > 1:
            scene.timeline_markers.new(f"Fire {self.fire_index}", frame=frame)

        frame += max(1, duration_frame)
        scene.frame_set(frame)

        # Refresh after moving the timeline so the freshly created Fire event is
        # visible immediately at the destination frame.
        try:
            from .preview import refresh_preview
            refresh_preview(scene)
        except (ImportError, RuntimeError):
            pass

        return {"FINISHED"}


class LIGHTSHOW_OT_refresh_pyro_preview(bpy.types.Operator):
    bl_label = "Rebuild Pyro Preview"
    bl_description = "Rebuild all visible pyrotechnic preview objects at the current frame"
    bl_idname = "lightshow.refresh_pyro_preview"

    def execute(self, context: bpy.types.Context) -> set[str]:
        try:
            from .preview import refresh_preview
            refresh_preview(context.scene)
        except Exception as exc:  # pragma: no cover - Blender operator safety
            self.report({"ERROR"}, f"Pyro preview: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, "Pyro preview rebuilt")
        return {"FINISHED"}


class LIGHTSHOW_PT_fire(BasePanelHideIfNoDrone):
    bl_parent_id = "SPARKSHOW_STUDIO_PT_pyro"
    bl_label = "🔥 Fire"
    bl_idname = "LIGHTSHOW_PT_fire"

    def draw(self, context: bpy.types.Context) -> None:
        lightshow = get_lightshow(context.scene)
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        draw_tutorial_button(
            layout,
            context,
            lambda col: col.prop(lightshow, "fire_duration"),
            section=link.fire,
        )
        layout.prop(lightshow, "fire_vdl")

        fire_row = layout.row(align=True)
        fire_row.operator("lightshow.fire0", text="Fire 1")
        fire_row.operator("lightshow.fire1", text="Fire 2")
        fire_row.operator("lightshow.fire2", text="Fire 3")

        box = layout.box()
        box.label(text="Pyro Preview", icon="LIGHT")
        box.label(text="Pyro color/physics are independent from Drone Lighting", icon="INFO")
        row = box.row(align=True)
        row.prop(lightshow, "fire_preview_enabled", text="Preview")
        row.prop(lightshow, "fire_preview_light_mode", text="Light Preview")
        box.prop(lightshow, "fire_preview_renderer", text="Renderer")

        if lightshow.fire_preview_light_mode:
            box.label(text="Light mode: reduced particles / mesh", icon="INFO")
        else:
            box.label(text="Full mode: maximum preview detail", icon="INFO")

        mapping = box.box()
        mapping.label(text="Fire → Pyro")
        for fire_channel in range(3):
            row = mapping.row(align=True)
            row.label(text=f"Fire {fire_channel + 1}")
            row.prop(lightshow, f"fire_preview_fire{fire_channel}_pyro", text="")

        profiles = box.box()
        profiles.label(text="Pyro profile")
        profiles.prop(lightshow, "fire_preview_active_pyro", expand=True)
        pyro = int(lightshow.fire_preview_active_pyro)
        prefix = f"fire_preview_channel{pyro}_"

        common = profiles.box()
        common.label(text=f"Pyro {pyro + 1} — common")
        common.prop(lightshow, prefix + "effect", text="Effect")
        common.prop(lightshow, prefix + "color", text="Color")
        row = common.row(align=True)
        row.prop(lightshow, prefix + "duration", text="Duration")
        row.prop(lightshow, prefix + "lifetime", text="Lifetime")
        row = common.row(align=True)
        row.prop(lightshow, prefix + "size", text="Size")
        row.prop(lightshow, prefix + "intensity", text="Intensity")
        common.prop(lightshow, prefix + "gravity", text="Gravity")
        if str(getattr(lightshow, "fire_preview_renderer", "AUTO")) in {"AUTO", "GPU_POINTS"}:
            gpu_box = profiles.box()
            gpu_box.label(text="GPU particle appearance")
            row = gpu_box.row(align=True)
            row.prop(lightshow, prefix + "gpu_particle_size", text="Particle size")
            row.prop(lightshow, prefix + "gpu_glow", text="Glow")

        effect = getattr(lightshow, prefix + "effect")
        specific = profiles.box()

        if effect == "FOUNTAIN":
            specific.label(text="Cascade / Fountain")
            row = specific.row(align=True)
            row.prop(lightshow, prefix + "fountain_jets", text="Jets")
            row.prop(lightshow, prefix + "fountain_particles", text="Density")
            row = specific.row(align=True)
            row.prop(lightshow, prefix + "fountain_velocity", text="Initial speed")
            row.prop(lightshow, prefix + "fountain_spread", text="Diffusion angle")
            specific.prop(lightshow, prefix + "fountain_direction", text="Diffusion direction")
            specific.prop(lightshow, prefix + "fountain_trail", text="Trail length")

        elif effect == "CRACKLING":
            specific.label(text="Crackling")
            row = specific.row(align=True)
            row.prop(lightshow, prefix + "crackle_stars", text="Stars")
            row.prop(lightshow, prefix + "crackle_spread", text="Radius")
            row = specific.row(align=True)
            row.prop(lightshow, prefix + "crackle_velocity", text="Velocity")
            row.prop(lightshow, prefix + "crackle_gravity", text="Gravity")
            row = specific.row(align=True)
            row.prop(lightshow, prefix + "crackle_branches", text="Crackles")
            row.prop(lightshow, prefix + "crackle_branch_length", text="Branch")
            specific.prop(lightshow, prefix + "crackle_trail", text="Trail")

        elif effect == "DAY_SMOKE":
            specific.label(text="Day Smoke")
            row = specific.row(align=True)
            row.prop(lightshow, prefix + "smoke_puffs", text="Puffs")
            row.prop(lightshow, prefix + "smoke_opacity", text="Opacity")
            row = specific.row(align=True)
            row.prop(lightshow, prefix + "smoke_rise", text="Rise")
            row.prop(lightshow, prefix + "smoke_expansion", text="Expansion")
            row = specific.row(align=True)
            row.prop(lightshow, prefix + "smoke_turbulence", text="Turbulence")
            row.prop(lightshow, prefix + "smoke_dissipation", text="Dissipation")
            specific.prop(lightshow, prefix + "smoke_mesh_resolution", text="Mesh definition")

        else:
            specific.label(text="Falling Stars")
            row = specific.row(align=True)
            row.prop(lightshow, prefix + "falling_stars", text="Stars")
            row.prop(lightshow, prefix + "falling_twinkle", text="Twinkle")
            row = specific.row(align=True)
            row.prop(lightshow, prefix + "falling_velocity", text="Velocity")
            row.prop(lightshow, prefix + "falling_spread", text="Spread")
            row = specific.row(align=True)
            row.prop(lightshow, prefix + "falling_gravity", text="Gravity")
            row.prop(lightshow, prefix + "falling_trail", text="Trail")

        info = box.row()
        info.label(text="Preview collection: Sparkshow Pyrotechnics", icon="OUTLINER_COLLECTION")
        action = box.row(align=True)
        action.operator("lightshow.refresh_pyro_preview", text="Rebuild Preview", icon="FILE_REFRESH")
        action.operator("sparkshow_studio.bake_pyro", text="Bake Pyro", icon="REC")
        action.operator("sparkshow_studio.clear_pyro_bake", text="Clear Bake", icon="TRASH")
        try:
            from .preview import event_count
            action.label(text=f"{event_count(context.scene)} event(s)")
        except Exception:
            pass
        bake_box = box.box()
        bake_box.label(text="Pyro Bake")
        bake_box.label(text=f"Scene range: {context.scene.frame_start} → {context.scene.frame_end}")
        bake_box.prop(lightshow, "fire_pyro_bake_step", text="Frame step")
        if context.scene.get("sparkshow_pyro_bake_active", False):
            bake_box.label(text="Baked cache active", icon="CHECKMARK")



class LIGHTSHOW_OT_fire0(FireBase):
    bl_label = "Fire 1"
    bl_description = "Fire the channel 1 of the selected drones"
    bl_idname = "lightshow.fire0"
    fire_index = 0


class LIGHTSHOW_OT_fire1(FireBase):
    bl_label = "Fire 2"
    bl_description = "Fire the channel 2 of the selected drones"
    bl_idname = "lightshow.fire1"
    fire_index = 1


class LIGHTSHOW_OT_fire2(FireBase):
    bl_label = "Fire 3"
    bl_description = "Fire the channel 3 of the selected drones"
    bl_idname = "lightshow.fire2"
    fire_index = 2


classes = [
    LIGHTSHOW_PT_fire,
    LIGHTSHOW_OT_refresh_pyro_preview,
    LIGHTSHOW_OT_fire0,
    LIGHTSHOW_OT_fire1,
    LIGHTSHOW_OT_fire2,
]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in classes:
        bpy.utils.unregister_class(cls)
