"""Sparkshow Fire preview using Blender 4.1 legacy particle emitters.

This module is an alternate preview engine. It leaves the existing Fire
keyframes/export untouched and keeps every emitter strictly inside the
``Sparkshow Pyrotechnics`` collection. Emitters are *not* parented to drones;
a single Copy Location constraint makes their emission origin follow the
current drone position without moving the emitter into a drone family.

Particle systems are intentionally used only for viewport preview. The
simulation is handled by Blender's native emitter particle system (Newton
physics, gravity, random velocity, object/line rendering), which gives a much
more natural particle look than rebuilding meshes from Python every frame.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

import bpy
from mathutils import Vector

from ..setup import FPS, get_lightshow
from ..tools.collection_tools import get_drones
from ..tools.fcurve_tools import find_fcurve_or_none

_COLLECTION = "Sparkshow Pyrotechnics"
_ASSET_COLLECTION = "Sparkshow Pyro Particle Assets"
_PREFIX = "Sparkshow_ParticlePyro_"
_ASSET_PREFIX = "Sparkshow_ParticleAsset_"
_CHANNELS = 3


@dataclass(frozen=True, slots=True)
class Event:
    drone_name: str
    channel: int
    frame: int


def _collection(name: str, parent: bpy.types.Collection | None = None) -> bpy.types.Collection:
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
    parent = parent or bpy.context.scene.collection
    if col.name not in {c.name for c in parent.children}:
        try:
            parent.children.link(col)
        except RuntimeError:
            pass
    return col


def _event_key(event: Event) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in event.drone_name)
    return f"{_PREFIX}{safe}_F{event.channel + 1}_{event.frame}"


def _iter_events(scene: bpy.types.Scene) -> list[Event]:
    events: list[Event] = []
    for drone in get_drones(scene.collection):
        for channel in range(_CHANNELS):
            fc = find_fcurve_or_none(drone, '["fire"]', channel)
            if fc is None:
                continue
            for point in fc.keyframe_points:
                events.append(Event(drone.name, channel, int(round(point.co.x))))
    events.sort(key=lambda e: (e.frame, e.channel, e.drone_name))
    return events


def _assigned(lightshow, channel: int) -> int:
    try:
        return max(0, min(2, int(getattr(lightshow, f"fire_preview_fire{channel}_pyro"))))
    except Exception:
        return channel


def _cfg(lightshow, pyro: int) -> dict:
    prefix = f"fire_preview_channel{pyro}_"
    def val(name: str, default):
        try:
            return getattr(lightshow, prefix + name)
        except AttributeError:
            return default
    effect = str(val("effect", "FOUNTAIN"))
    cfg = {
        "effect": effect,
        "color": tuple(float(v) for v in val("color", (1, 0.2, 0.05, 1))),
        "duration": max(0.1, float(val("duration", 1.5))),
        "size": max(0.05, float(val("size", 2.0))),
        "intensity": max(0.1, float(val("intensity", 2.5))),
        "gravity": max(0.0, float(val("gravity", 9.81))),
    }
    for name in (
        "fountain_jets", "fountain_particles", "fountain_velocity", "fountain_spread",
        "fountain_trail", "fountain_direction", "crackle_stars", "crackle_velocity",
        "crackle_spread", "crackle_gravity", "crackle_branches", "crackle_branch_length",
        "crackle_trail", "smoke_puffs", "smoke_rise", "smoke_expansion", "smoke_turbulence",
        "smoke_dissipation", "smoke_opacity", "smoke_mesh_resolution", "falling_stars",
        "falling_velocity", "falling_spread", "falling_gravity", "falling_trail", "falling_twinkle",
    ):
        if hasattr(lightshow, prefix + name):
            cfg[name] = getattr(lightshow, prefix + name)
    return cfg


def _material(name: str, color: tuple[float, float, float, float], strength: float, smoke: bool = False) -> bpy.types.Material:
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.diffuse_color = color
    try:
        mat.blend_method = 'BLEND' if smoke else 'OPAQUE'
    except (AttributeError, TypeError):
        pass
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    if smoke:
        bsdf.inputs["Base Color"].default_value = (*color[:3], 1.0)
        bsdf.inputs["Roughness"].default_value = 1.0
        bsdf.inputs["Alpha"].default_value = max(0.02, min(0.65, color[3]))
        if "Metallic" in bsdf.inputs:
            bsdf.inputs["Metallic"].default_value = 0.0
    else:
        emission = nodes.new("ShaderNodeEmission")
        emission.inputs["Color"].default_value = color
        emission.inputs["Strength"].default_value = max(1.0, strength * 8.0)
        links.new(emission.outputs["Emission"], out.inputs["Surface"])
        return mat
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def _ensure_asset_spark(color: tuple[float, float, float, float], intensity: float) -> bpy.types.Object:
    name = _ASSET_PREFIX + "Spark"
    obj = bpy.data.objects.get(name)
    if obj is None:
        mesh = bpy.data.meshes.new(name + "_Mesh")
        # A short tapered spark, long axis local Z.
        verts = [
            (-0.018, 0.0, -0.10), (0.018, 0.0, -0.10),
            (0.012, 0.012, 0.04), (-0.012, 0.012, 0.04),
            (0.0, 0.0, 0.12),
        ]
        faces = [(0,1,2,3), (3,2,4), (0,4,1), (1,4,2), (2,4,3), (3,4,0)]
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        obj = bpy.data.objects.new(name, mesh)
        _collection(_ASSET_COLLECTION).objects.link(obj)
        obj.location = (0,0,-10000)
        obj.hide_set(False)
        obj.hide_render = True
    mat_name = _ASSET_PREFIX + "SparkMaterial"
    mat = _material(mat_name, color, intensity)
    if len(obj.data.materials) == 0:
        obj.data.materials.append(mat)
    else:
        obj.data.materials[0] = mat
    return obj


def _ensure_asset_smoke(color: tuple[float, float, float, float], opacity: float, resolution: int) -> bpy.types.Object:
    name = _ASSET_PREFIX + f"Smoke_{resolution}"
    obj = bpy.data.objects.get(name)
    if obj is None:
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=max(1, min(4, resolution // 8)), radius=0.5, location=(0,0,-10000))
        obj = bpy.context.object
        obj.name = name
        for c in list(obj.users_collection):
            c.objects.unlink(obj)
        _collection(_ASSET_COLLECTION).objects.link(obj)
        obj.hide_set(False)
        obj.hide_render = True
    mat = _material(_ASSET_PREFIX + "SmokeMaterial", (*color[:3], opacity), 1.0, smoke=True)
    if len(obj.data.materials) == 0:
        obj.data.materials.append(mat)
    else:
        obj.data.materials[0] = mat
    return obj


def _add_emitter_mesh(name: str) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name + "_Mesh")
    verts = [(-0.04,-0.04,0), (0.04,-0.04,0), (0.0,0.04,0)]
    mesh.from_pydata(verts, [(0,1),(1,2),(2,0)], [(0,1,2)])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    _collection(_COLLECTION).objects.link(obj)
    obj.display_type = 'WIRE'
    obj.hide_render = True
    return obj


def _set_direction(obj: bpy.types.Object, direction: Iterable[float]) -> None:
    vec = Vector(tuple(float(v) for v in direction))
    if vec.length < 1e-5:
        vec = Vector((0,0,-1))
    obj.rotation_mode = 'QUATERNION'
    obj.rotation_quaternion = Vector((0,0,1)).rotation_difference(vec.normalized())


def _configure_particle_system(obj: bpy.types.Object, event: Event, cfg: dict, pyro: int, asset_spark: bpy.types.Object | None, asset_smoke: bpy.types.Object | None) -> None:
    # Particle operator needs a mesh object in Object mode.
    view_layer = bpy.context.view_layer
    for o in view_layer.objects:
        o.select_set(False)
    obj.select_set(True)
    view_layer.objects.active = obj
    if obj.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.particle_system_add()
    psys = obj.particle_systems[-1]
    settings = psys.settings
    settings.name = f"Sparkshow Pyro ParticleSettings P{pyro + 1} {event.frame}"
    settings.type = 'EMITTER'
    settings.physics_type = 'NEWTON'
    settings.emit_from = 'FACE'
    settings.use_emit_random = True
    settings.distribution = 'RAND'
    settings.frame_start = float(event.frame)
    if cfg["effect"] == 'FOUNTAIN':
        count = int(cfg.get('fountain_particles', 120))
        settings.frame_end = float(event.frame + max(1, int(FPS * min(0.22, cfg["duration"] * 0.18))))
        settings.normal_factor = float(cfg.get('fountain_velocity', 8.0))
        settings.factor_random = float(cfg.get('fountain_velocity', 8.0)) * 0.18
        settings.lifetime = max(1.0, cfg["duration"] * FPS)
        settings.lifetime_random = 0.28
        settings.effector_weights.gravity = cfg["gravity"] / 9.81 if cfg["gravity"] else 0.0
        settings.damping = 0.02
        settings.drag_factor = 0.025
        settings.count = max(5, min(300, count))
        settings.render_type = 'LINE'
        settings.line_length_head = max(0.004, cfg["size"] * 0.02)
        settings.line_length_tail = max(0.01, float(cfg.get("fountain_trail", 0.28)))
        settings.particle_size = max(0.008, cfg["size"] * 0.024)
        settings.size_random = 0.42
        settings.use_rotation_instance = True
        settings.rotation_mode = 'VEL'
        settings.use_dynamic_rotation = True
    elif cfg["effect"] == 'CRACKLING':
        count = int(cfg.get('crackle_stars', 80))
        settings.frame_end = float(event.frame + 1)
        settings.normal_factor = float(cfg.get('crackle_velocity', 7.0))
        settings.factor_random = settings.normal_factor * 0.55
        settings.lifetime = max(1.0, cfg["duration"] * FPS)
        settings.lifetime_random = 0.38
        settings.effector_weights.gravity = float(cfg.get('crackle_gravity', cfg['gravity'])) / 9.81
        settings.brownian_factor = 0.3
        settings.damping = 0.035
        settings.count = max(6, min(400, count))
        settings.render_type = 'OBJECT'
        settings.instance_object = asset_spark
        settings.particle_size = max(0.008, cfg["size"] * 0.028)
        settings.size_random = 0.55
        settings.use_rotation_instance = True
        settings.rotation_mode = 'VEL'
    elif cfg["effect"] == 'DAY_SMOKE':
        count = int(cfg.get('smoke_puffs', 16))
        settings.frame_end = float(event.frame + max(1, int(FPS * min(0.45, cfg["duration"] * 0.35))))
        settings.normal_factor = float(cfg.get('smoke_rise', 1.4))
        settings.factor_random = settings.normal_factor * 0.55
        settings.lifetime = max(2.0, cfg["duration"] * FPS)
        settings.lifetime_random = 0.3
        settings.effector_weights.gravity = 0.0
        settings.brownian_factor = float(cfg.get('smoke_turbulence', 0.45))
        settings.damping = 0.08
        settings.count = max(2, min(80, count))
        settings.render_type = 'OBJECT'
        settings.instance_object = asset_smoke
        settings.particle_size = max(0.05, cfg["size"] * 0.45)
        settings.size_random = 0.65
        settings.use_dynamic_rotation = True
        settings.rotation_mode = 'RAND'
    else:  # FALLING_STARS
        count = int(cfg.get('falling_stars', 36))
        settings.frame_end = float(event.frame + 1)
        settings.normal_factor = float(cfg.get('falling_velocity', 7.0))
        settings.factor_random = settings.normal_factor * 0.45
        settings.lifetime = max(1.0, cfg["duration"] * FPS)
        settings.lifetime_random = 0.3
        settings.effector_weights.gravity = float(cfg.get('falling_gravity', 9.0)) / 9.81
        settings.damping = 0.01
        settings.count = max(4, min(300, count))
        settings.render_type = 'LINE'
        settings.line_length_head = max(0.004, cfg["size"] * 0.02)
        settings.line_length_tail = max(0.01, float(cfg.get("falling_trail", 0.42)))
        settings.particle_size = max(0.008, cfg["size"] * 0.026)
        settings.size_random = 0.5
        settings.use_rotation_instance = True
        settings.rotation_mode = 'VEL'

    settings.display_method = 'RENDER'
    settings.display_percentage = 100
    settings.display_size = max(0.01, cfg["size"] * 0.05)
    settings.use_adaptive_subframes = True
    settings.courant_target = 0.2

    # Keep the emitter itself out of all drone collections.
    constraint = obj.constraints.get("Sparkshow Follow Drone") or obj.constraints.new('COPY_LOCATION')
    constraint.name = "Sparkshow Follow Drone"
    constraint.target = bpy.data.objects.get(event.drone_name)
    constraint.use_offset = False
    obj["sparkshow_synoptic"] = True
    obj["sparkshow_synoptic_type"] = "pyrotechnic_particle_preview"
    obj["sparkshow_pyro_collection"] = _COLLECTION
    obj["sparkshow_pyro_profile"] = pyro + 1
    obj["sparkshow_pyro_effect"] = cfg["effect"]
    obj["sparkshow_fire_channel"] = event.channel + 1
    obj["sparkshow_fire_frame"] = event.frame
    obj["sparkshow_drone"] = event.drone_name
    obj["sparkshow_particle_engine"] = True
    obj["sparkshow_pyro_duration"] = cfg["duration"]
    obj["sparkshow_pyro_size"] = cfg["size"]
    obj["sparkshow_pyro_gravity"] = cfg["gravity"]
    obj.hide_set(False)


def _cleanup_particle_objects() -> None:
    for obj in list(bpy.data.objects):
        if obj.name.startswith(_PREFIX):
            bpy.data.objects.remove(obj, do_unlink=True)


def _cleanup_old_procedural_objects() -> None:
    for obj in list(bpy.data.objects):
        if obj.name.startswith("Sparkshow_PyroEvent_"):
            bpy.data.objects.remove(obj, do_unlink=True)


def refresh_preview(scene: bpy.types.Scene | None = None) -> None:
    scene = scene or bpy.context.scene
    if scene is None:
        return
    lightshow = get_lightshow(scene)
    if not getattr(lightshow, "fire_preview_enabled", False):
        _cleanup_particle_objects()
        return

    _cleanup_old_procedural_objects()
    _cleanup_particle_objects()
    # Assets live in their own collection and are never linked to a family.
    _collection(_ASSET_COLLECTION)
    preview_col = _collection(_COLLECTION)

    events = _iter_events(scene)
    for event in events:
        pyro = _assigned(lightshow, event.channel)
        cfg = _cfg(lightshow, pyro)
        if cfg["effect"] == 'DAY_SMOKE':
            asset = _ensure_asset_smoke(
                cfg["color"],
                float(cfg.get("smoke_opacity", 0.35)),
                int(cfg.get("smoke_mesh_resolution", 10)),
            )
            spark = None
        else:
            asset = None
            spark = _ensure_asset_spark(cfg["color"], cfg["intensity"])

        obj = _add_emitter_mesh(_event_key(event))
        # Direction is defined by the active effect, while location follows the drone.
        if cfg["effect"] == 'FOUNTAIN':
            _set_direction(obj, cfg.get("fountain_direction", (0.0, 0.0, -1.0)))
        elif cfg["effect"] == 'FALLING_STARS':
            _set_direction(obj, (0.0, 0.0, -1.0))
        elif cfg["effect"] == 'DAY_SMOKE':
            _set_direction(obj, (0.0, 0.0, 1.0))
        else:
            _set_direction(obj, (0.0, 0.0, 1.0))
        _configure_particle_system(obj, event, cfg, pyro, spark, asset)
        # Defensive collection isolation.
        for col in list(obj.users_collection):
            if col != preview_col:
                col.objects.unlink(obj)
        if obj.name not in preview_col.objects:
            preview_col.objects.link(obj)

    scene["sparkshow_particle_pyro_event_count"] = len(events)
    scene["sparkshow_particle_pyro_engine"] = True


def rebuild_preview(context: bpy.types.Context) -> None:
    refresh_preview(context.scene)
    if context.screen:
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
