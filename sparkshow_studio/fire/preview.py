"""Reliable Sparkshow Fire viewport preview for Blender 4.1.

The preview is deliberately isolated from drone-family collections and from Fire
export data. Each Fire keyframe creates one preview object in the dedicated
``Sparkshow Pyrotechnics`` collection. The object is NOT parented to the drone;
its world transform is updated from the drone's evaluated matrix on each frame.

The visual simulation is CPU-generated once per event/profile change and then
updated only while events are active. Sparks use real Blender Curve geometry;
day-smoke uses a single disconnected mesh containing low-poly irregular puffs.
This avoids the fragile Geometry Nodes setup that previously produced no visible
result in Blender 4.1.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from typing import Iterable

import bpy
from mathutils import Matrix, Vector

from bpy.app.handlers import persistent

from ..setup import FPS, get_lightshow
from ..tools.collection_tools import get_drones
from ..tools.fcurve_tools import find_fcurve_or_none


_CHANNEL_COUNT = 3
_PREVIEW_COLLECTION_NAME = "Sparkshow Pyrotechnics"
_PREVIEW_OBJECT_PREFIX = "Sparkshow_PyroEvent_"
_PREVIEW_MATERIAL_PREFIX = "Sparkshow_PyroMaterial_"
_SCENE_REVISION_KEY = "sparkshow_fire_preview_revision"
_RUNTIME_KEY = "sparkshow_pyro_runtime"
_HANDLER_NAME = "_sparkshow_fire_preview_frame_change"

_EVENT_CACHE_SCENE_ID: int | None = None
_EVENT_CACHE_REVISION: int = -1
_EVENT_CACHE: list["FirePreviewEvent"] = []
_RUNTIME: dict[str, "EventRuntime"] = {}


@dataclass(frozen=True, slots=True)
class FirePreviewEvent:
    # Store only the stable Blender object name. Keeping a bpy.types.Object in
    # the cached event/runtime can leave a dead StructRNA reference after a
    # drone is deleted, duplicated or recreated by Initialize Show.
    drone_name: str
    channel: int
    frame: int


@dataclass(frozen=True, slots=True)
class PyroConfig:
    effect: str
    color: tuple[float, float, float, float]
    duration: float
    lifetime: float
    size: float
    intensity: float
    gravity: float
    params: dict[str, float | int]
    light_preview: bool = True


@dataclass(slots=True)
class Particle:
    birth: float
    life: float
    velocity: Vector
    base: Vector
    acceleration: Vector
    trail: float
    radius: float
    brightness: float
    phase: float
    twinkle: float = 0.0


@dataclass(slots=True)
class SmokePuff:
    birth: float
    life: float
    base: Vector
    velocity: Vector
    scale: Vector
    phase: float
    turbulence: float
    opacity: float


@dataclass(slots=True)
class EventRuntime:
    event: FirePreviewEvent
    pyro: int
    config_hash: str
    particles: list[Particle]
    smoke_puffs: list[SmokePuff]
    sample_count: int
    puff_vertex_groups: list[tuple[int, int, SmokePuff, list[Vector]]]


# ---------------------------------------------------------------------------
# Event discovery / configuration
# ---------------------------------------------------------------------------


def _event_key(channel: int, frame: int) -> str:
    return f"sparkshow_pyro_preview:{channel}:{frame}"


def record_event_position(
    drone: bpy.types.Object,
    channel: int,
    frame: int,
    *,
    position: tuple[float, float, float] | None = None,
) -> None:
    """Keep the legacy snapshot hook without using it for positioning."""
    try:
        drone[_event_key(channel, frame)] = (
            tuple(float(v) for v in position) if position is not None else True
        )
    except (TypeError, ReferenceError):
        return

    scene = bpy.context.scene
    if scene is not None:
        scene[_SCENE_REVISION_KEY] = int(scene.get(_SCENE_REVISION_KEY, 0)) + 1


def _iter_fire_events(scene: bpy.types.Scene) -> list[FirePreviewEvent]:
    events: list[FirePreviewEvent] = []
    for drone in get_drones(scene.collection):
        for channel in range(_CHANNEL_COUNT):
            fcurve = find_fcurve_or_none(drone, '["fire"]', channel)
            if fcurve is None:
                continue
            for point in fcurve.keyframe_points:
                events.append(
                    FirePreviewEvent(
                        drone_name=drone.name,
                        channel=channel,
                        frame=int(round(point.co.x)),
                    )
                )
    events.sort(key=lambda e: (e.frame, e.channel, e.drone_name))
    return events


def _cached_fire_events(scene: bpy.types.Scene) -> list[FirePreviewEvent]:
    global _EVENT_CACHE_SCENE_ID, _EVENT_CACHE_REVISION, _EVENT_CACHE
    scene_id = id(scene)
    revision = int(scene.get(_SCENE_REVISION_KEY, 0))
    if scene_id != _EVENT_CACHE_SCENE_ID or revision != _EVENT_CACHE_REVISION:
        _EVENT_CACHE = _iter_fire_events(scene)
        _EVENT_CACHE_SCENE_ID = scene_id
        _EVENT_CACHE_REVISION = revision
    return _EVENT_CACHE


def _assigned_pyro(lightshow, fire_channel: int) -> int:
    try:
        value = int(getattr(lightshow, f"fire_preview_fire{fire_channel}_pyro"))
    except (TypeError, ValueError, AttributeError):
        value = fire_channel
    return max(0, min(_CHANNEL_COUNT - 1, value))


def _pyro_settings(lightshow, pyro: int) -> PyroConfig:
    prefix = f"fire_preview_channel{pyro}_"
    effect = str(getattr(lightshow, prefix + "effect", "FOUNTAIN"))
    color = tuple(float(v) for v in getattr(lightshow, prefix + "color", (1, 0.2, 0.05, 1)))
    duration = max(0.05, float(getattr(lightshow, prefix + "duration", 1.5)))
    lifetime = max(0.05, float(getattr(lightshow, prefix + "lifetime", duration)))
    size = max(0.05, float(getattr(lightshow, prefix + "size", 2.0)))
    intensity = max(0.1, float(getattr(lightshow, prefix + "intensity", 2.5)))
    gravity = max(0.0, float(getattr(lightshow, prefix + "gravity", 9.81)))

    names = (
        "fountain_jets", "fountain_particles", "fountain_velocity", "fountain_spread",
        "fountain_trail", "fountain_direction", "crackle_stars", "crackle_velocity", "crackle_spread",
        "crackle_gravity", "crackle_branches", "crackle_branch_length", "crackle_trail",
        "smoke_puffs", "smoke_rise", "smoke_expansion", "smoke_turbulence",
        "smoke_dissipation", "smoke_opacity", "smoke_mesh_resolution", "falling_stars", "falling_velocity",
        "falling_spread", "falling_gravity", "falling_trail", "falling_twinkle",
        "gpu_particle_size", "gpu_glow",
    )
    params = {key: getattr(lightshow, prefix + key) for key in names if hasattr(lightshow, prefix + key)}
    light_preview = bool(getattr(lightshow, "fire_preview_light_mode", True))
    return PyroConfig(effect, color, duration, lifetime, size, intensity, gravity, params, light_preview)


def event_count(scene: bpy.types.Scene | None = None) -> int:
    scene = scene or bpy.context.scene
    return len(_cached_fire_events(scene)) if scene else 0


# ---------------------------------------------------------------------------
# Collection / materials
# ---------------------------------------------------------------------------


def _ensure_preview_collection(scene: bpy.types.Scene) -> bpy.types.Collection:
    col = bpy.data.collections.get(_PREVIEW_COLLECTION_NAME)
    if col is None:
        col = bpy.data.collections.new(_PREVIEW_COLLECTION_NAME)
    if col.name not in scene.collection.children:
        try:
            scene.collection.children.link(col)
        except RuntimeError:
            pass
    col.hide_render = True
    col.hide_viewport = False
    scene["sparkshow_pyro_preview_collection"] = _PREVIEW_COLLECTION_NAME
    return col


def _unlink_from_other_collections(obj: bpy.types.Object, preview_col: bpy.types.Collection) -> None:
    for collection in list(obj.users_collection):
        if collection != preview_col:
            try:
                collection.objects.unlink(obj)
            except RuntimeError:
                pass
    if obj.name not in preview_col.objects:
        preview_col.objects.link(obj)


def _ensure_spark_material(pyro: int, cfg: PyroConfig) -> bpy.types.Material:
    name = f"{_PREVIEW_MATERIAL_PREFIX}{pyro + 1}_SPARKS"
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    if (
        mat.use_nodes
        and mat.get("sparkshow_material_hash") == _config_hash(pyro, cfg)
    ):
        return mat
    mat.use_nodes = True
    mat.diffuse_color = cfg.color
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out = nodes.new("ShaderNodeOutputMaterial")
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = cfg.color
    emission.inputs["Strength"].default_value = max(1.0, cfg.intensity * 4.0)
    links.new(emission.outputs["Emission"], out.inputs["Surface"])
    mat["sparkshow_material_hash"] = _config_hash(pyro, cfg)
    return mat


def _ensure_smoke_material(pyro: int, cfg: PyroConfig) -> bpy.types.Material:
    """Create a transparent, noise-modulated smoke material for Blender 4.1."""
    name = f"{_PREVIEW_MATERIAL_PREFIX}{pyro + 1}_SMOKE"
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    chash = _config_hash(pyro, cfg)
    if mat.use_nodes and mat.get("sparkshow_material_hash") == chash:
        return mat

    mat.use_nodes = True
    mat.diffuse_color = (*cfg.color[:3], max(0.01, min(1.0, float(cfg.params.get("smoke_opacity", 0.72)))))
    # Blender 4.1 uses the Material Blend Mode UI/API. Keep a guarded fallback
    # for newer Blender builds where surface_render_method is exposed.
    try:
        mat.blend_method = 'BLEND'
    except (AttributeError, TypeError):
        try:
            mat.surface_render_method = 'BLENDED'
        except (AttributeError, TypeError):
            pass
    for attr_name, attr_value in (("show_transparent_back", False), ("use_transparency_overlap", False)):
        try:
            setattr(mat, attr_name, attr_value)
        except (AttributeError, TypeError):
            pass

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (620, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (340, 0)
    bsdf.inputs["Roughness"].default_value = 0.98
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = 0.0
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.03
    elif "Specular" in bsdf.inputs:
        bsdf.inputs["Specular"].default_value = 0.03

    attr = nodes.new("ShaderNodeAttribute")
    attr.location = (-420, 50)
    attr.attribute_name = "fw_smoke_color"

    texcoord = nodes.new("ShaderNodeTexCoord")
    texcoord.location = (-420, -170)
    noise = nodes.new("ShaderNodeTexNoise")
    noise.location = (-180, -180)
    noise.noise_dimensions = '3D'
    noise.inputs["Scale"].default_value = 3.2
    noise.inputs["Detail"].default_value = 4.0
    noise.inputs["Roughness"].default_value = 0.72

    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.location = (20, -180)
    ramp.color_ramp.elements[0].position = 0.26
    ramp.color_ramp.elements[1].position = 0.72
    ramp.color_ramp.elements[0].color = (0.0, 0.0, 0.0, 1.0)
    ramp.color_ramp.elements[1].color = (1.0, 1.0, 1.0, 1.0)

    alpha_mul = nodes.new("ShaderNodeMath")
    alpha_mul.operation = 'MULTIPLY'
    alpha_mul.location = (160, -20)

    links.new(attr.outputs["Color"], bsdf.inputs["Base Color"])
    if "Alpha" in attr.outputs and "Alpha" in bsdf.inputs:
        links.new(attr.outputs["Alpha"], alpha_mul.inputs[0])
        links.new(ramp.outputs["Color"], alpha_mul.inputs[1])
        links.new(alpha_mul.outputs[0], bsdf.inputs["Alpha"])
    links.new(texcoord.outputs["Generated"], noise.inputs["Vector"])
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    mat["sparkshow_material_hash"] = chash
    return mat


# ---------------------------------------------------------------------------
# Deterministic simulation data
# ---------------------------------------------------------------------------


def _stable_seed(drone_name: str, channel: int, frame: int, pyro: int) -> int:
    digest = hashlib.sha1(f"{drone_name}|{channel}|{frame}|{pyro}".encode()).digest()
    return int.from_bytes(digest[:8], "little", signed=False)


def _unit(rng: random.Random) -> Vector:
    z = rng.uniform(-1.0, 1.0)
    phi = rng.random() * math.tau
    r = math.sqrt(max(0.0, 1.0 - z * z))
    return Vector((r * math.cos(phi), r * math.sin(phi), z))


def _cone(rng: random.Random, spread: float) -> Vector:
    az = rng.random() * math.tau
    theta = max(0.0, min(math.radians(89.0), rng.uniform(0.0, spread)))
    return Vector((math.sin(theta) * math.cos(az), math.sin(theta) * math.sin(az), math.cos(theta))).normalized()


def _oriented_cone(rng: random.Random, spread: float, axis: Vector) -> Vector:
    """Generate a cone around an arbitrary local axis."""
    local = _cone(rng, spread)
    axis = Vector(axis)
    if axis.length < 1e-6:
        axis = Vector((0.0, 0.0, -1.0))
    axis.normalize()
    align = Vector((0.0, 0.0, 1.0)).rotation_difference(axis)
    result = align @ local
    return result.normalized()


def _ballistic_position(p: Particle, t: float) -> Vector:
    return p.base + p.velocity * t + 0.5 * p.acceleration * (t * t)


def _build_particles(cfg: PyroConfig, seed: int) -> list[Particle]:
    rng = random.Random(seed)
    particles: list[Particle] = []
    g = cfg.gravity
    size = cfg.size
    duration = cfg.duration
    lifetime = cfg.lifetime

    if cfg.effect == "FOUNTAIN":
        jets_cap = 8 if cfg.light_preview else 24
        particle_cap = 48 if cfg.light_preview else 360
        jets = max(2, min(jets_cap, int(cfg.params.get("fountain_jets", 12))))
        count = max(12 if cfg.light_preview else 24, min(particle_cap, int(cfg.params.get("fountain_particles", 120))))
        velocity = max(0.05, float(cfg.params.get("fountain_velocity", 8.0)))
        spread = float(cfg.params.get("fountain_spread", math.radians(35.0)))
        axis_values = cfg.params.get("fountain_direction", (0.0, 0.0, -1.0))
        axis = Vector(tuple(axis_values)) if isinstance(axis_values, (tuple, list)) else Vector((0.0, 0.0, -1.0))
        if axis.length < 1e-6:
            axis = Vector((0.0, 0.0, -1.0))
        axis.normalize()
        trail = max(0.02, float(cfg.params.get("fountain_trail", 0.28)))
        emission_window = duration * 0.58
        for i in range(count):
            jet = i % jets
            jet_axis = axis.copy()
            # Spread each jet around the requested diffusion axis while keeping
            # a deterministic azimuth for a stable preview.
            d = _oriented_cone(rng, max(0.0, spread), jet_axis)
            speed = velocity * rng.uniform(0.78, 1.18)
            birth = rng.uniform(0.0, emission_window)
            life = max(0.05, lifetime * rng.uniform(0.88, 1.12))
            particles.append(Particle(
                birth=birth,
                life=life,
                velocity=d * speed,
                base=Vector((rng.uniform(-0.06, 0.06) * size, rng.uniform(-0.06, 0.06) * size, 0.0)),
                acceleration=Vector((0.0, 0.0, -g * rng.uniform(0.9, 1.1))),
                trail=trail,
                radius=max(0.004, size * rng.uniform(0.004, 0.009)),
                brightness=cfg.intensity * rng.uniform(0.8, 1.15),
                phase=rng.random() * math.tau,
            ))

    elif cfg.effect == "CRACKLING":
        main_cap = 40 if cfg.light_preview else 260
        branch_cap = 2 if cfg.light_preview else 12
        main_count = max(12 if cfg.light_preview else 20, min(main_cap, int(cfg.params.get("crackle_stars", 80))))
        branches = max(0, min(branch_cap, int(cfg.params.get("crackle_branches", 3))))
        velocity = float(cfg.params.get("crackle_velocity", 7.0)) * max(0.45, size / 1.8)
        gravity = float(cfg.params.get("crackle_gravity", g))
        radius = float(cfg.params.get("crackle_spread", 1.5)) * size
        trail = max(0.02, float(cfg.params.get("crackle_trail", 0.16)))
        records: list[tuple[float, float, Vector]] = []
        for _ in range(main_count):
            d = _unit(rng)
            speed = velocity * rng.uniform(0.78, 1.18)
            birth = rng.uniform(0.05, min(0.25, duration * 0.22))
            life = lifetime * rng.uniform(0.78, 1.08)
            vel = d * speed
            records.append((birth, life, vel))
            particles.append(Particle(
                birth=birth,
                life=life,
                velocity=vel,
                base=Vector((0.0, 0.0, 0.0)),
                acceleration=Vector((0.0, 0.0, -gravity)),
                trail=trail,
                radius=max(0.004, size * rng.uniform(0.004, 0.0085)),
                brightness=cfg.intensity * rng.uniform(0.85, 1.2),
                phase=rng.random() * math.tau,
                twinkle=rng.uniform(0.35, 1.0),
            ))
        branch_len = float(cfg.params.get("crackle_branch_length", 0.38)) * size
        for i in range(branches * max(1, main_count // 8)):
            birth, life, parent_vel = records[i % len(records)]
            t0 = rng.uniform(0.22, 0.58)
            parent_pos = parent_vel * t0 + Vector((0, 0, -0.5 * gravity * t0 * t0))
            radial = _unit(rng)
            vel = radial * rng.uniform(0.45, 1.0) * velocity * max(0.15, branch_len)
            particles.append(Particle(
                birth=birth + t0,
                life=max(0.05, lifetime * rng.uniform(0.16, 0.42)),
                velocity=vel,
                base=parent_pos,
                acceleration=Vector((0.0, 0.0, -gravity * 0.75)),
                trail=trail * 0.55,
                radius=max(0.003, size * rng.uniform(0.002, 0.0045)),
                brightness=cfg.intensity * rng.uniform(0.45, 0.9),
                phase=rng.random() * math.tau,
                twinkle=rng.uniform(0.5, 1.0),
            ))

    elif cfg.effect == "FALLING_STARS":
        star_cap = 40 if cfg.light_preview else 220
        count = max(6 if cfg.light_preview else 8, min(star_cap, int(cfg.params.get("falling_stars", 36))))
        velocity = float(cfg.params.get("falling_velocity", 7.0)) * max(0.4, size / 1.6)
        spread = min(math.pi / 2.0, float(cfg.params.get("falling_spread", math.radians(38.0))))
        gravity = float(cfg.params.get("falling_gravity", g))
        trail = max(0.04, float(cfg.params.get("falling_trail", 0.42)))
        twinkle = float(cfg.params.get("falling_twinkle", 0.5))
        for _ in range(count):
            d = _cone(rng, spread)
            d.z *= rng.uniform(0.05, 0.35)
            d.x += rng.uniform(-0.8, 0.8)
            d.y += rng.uniform(-0.8, 0.8)
            d.normalize()
            vel = d * velocity * rng.uniform(0.75, 1.18)
            particles.append(Particle(
                birth=rng.uniform(0.02, duration * 0.16),
                life=lifetime * rng.uniform(0.72, 1.06),
                velocity=vel,
                base=Vector((0.0, 0.0, size * rng.uniform(0.2, 0.55))),
                acceleration=Vector((0.0, 0.0, -gravity)),
                trail=trail,
                radius=max(0.004, size * rng.uniform(0.004, 0.007)),
                brightness=cfg.intensity * rng.uniform(0.85, 1.2),
                phase=rng.random() * math.tau,
                twinkle=twinkle,
            ))

    return particles


def _uv_sphere_template(segments: int = 8, rings: int = 4) -> tuple[list[Vector], list[tuple[int, int, int]]]:
    verts: list[Vector] = [Vector((0.0, 0.0, 1.0))]
    faces: list[tuple[int, int, int]] = []
    for r in range(1, rings):
        phi = math.pi * r / rings
        z = math.cos(phi)
        s = math.sin(phi)
        for seg in range(segments):
            a = math.tau * seg / segments
            verts.append(Vector((s * math.cos(a), s * math.sin(a), z)))
    bottom = len(verts)
    verts.append(Vector((0.0, 0.0, -1.0)))
    ring_count = rings - 1
    for seg in range(segments):
        a = 1 + seg
        b = 1 + (seg + 1) % segments
        faces.append((0, b, a))
    for r in range(ring_count - 1):
        start = 1 + r * segments
        next_start = start + segments
        for seg in range(segments):
            a = start + seg
            b = start + (seg + 1) % segments
            c = next_start + seg
            d = next_start + (seg + 1) % segments
            faces.append((a, b, d))
            faces.append((a, d, c))
    last = 1 + (ring_count - 1) * segments
    for seg in range(segments):
        a = last + seg
        b = last + (seg + 1) % segments
        faces.append((a, b, bottom))
    return verts, faces


def _build_smoke_puffs(cfg: PyroConfig, seed: int) -> tuple[list[SmokePuff], list[Vector], list[tuple[int, int, int]], list[tuple[int, int, SmokePuff]]]:
    rng = random.Random(seed)
    puff_cap = 8 if cfg.light_preview else 45
    count = max(3 if cfg.light_preview else 4, min(puff_cap, int(cfg.params.get("smoke_puffs", 16))))
    duration = cfg.duration
    lifetime = cfg.lifetime
    size = cfg.size
    rise = float(cfg.params.get("smoke_rise", 1.4))
    expansion = float(cfg.params.get("smoke_expansion", 1.0))
    turbulence = float(cfg.params.get("smoke_turbulence", 0.45))
    opacity = float(cfg.params.get("smoke_opacity", 0.72))
    mesh_res_cap = 6 if cfg.light_preview else 24
    mesh_resolution = max(4 if cfg.light_preview else 6, min(mesh_res_cap, int(cfg.params.get("smoke_mesh_resolution", 10))))
    mesh_rings = max(3, min(12, mesh_resolution // 2))
    template_v, template_f = _uv_sphere_template(segments=mesh_resolution, rings=mesh_rings)
    vertices: list[Vector] = []
    faces: list[tuple[int, int, int]] = []
    puffs: list[SmokePuff] = []
    groups: list[tuple[int, int, SmokePuff, list[Vector]]] = []

    for _ in range(count):
        puff = SmokePuff(
            birth=rng.uniform(0.0, duration * 0.52),
            life=lifetime * rng.uniform(0.82, 1.25),
            base=Vector((rng.uniform(-0.18, 0.18), rng.uniform(-0.18, 0.18), rng.uniform(-0.08, 0.08))) * size,
            velocity=Vector((rng.uniform(-0.16, 0.16) * expansion, rng.uniform(-0.16, 0.16) * expansion, rise * rng.uniform(0.78, 1.22))),
            scale=Vector((rng.uniform(0.22, 0.52), rng.uniform(0.22, 0.52), rng.uniform(0.26, 0.62))) * size,
            phase=rng.random() * math.tau,
            turbulence=turbulence * size * rng.uniform(0.65, 1.35),
            opacity=opacity * rng.uniform(0.7, 1.0),
        )
        start = len(vertices)
        directions: list[Vector] = []
        for v in template_v:
            jitter = Vector((rng.uniform(0.88, 1.12), rng.uniform(0.88, 1.12), rng.uniform(0.88, 1.12)))
            local = Vector((v.x * jitter.x, v.y * jitter.y, v.z * jitter.z))
            directions.append(local.normalized() if local.length > 0.001 else Vector((0.0, 0.0, 1.0)))
            vertices.append(Vector((local.x * puff.scale.x, local.y * puff.scale.y, local.z * puff.scale.z)))
        for a, b, c in template_f:
            faces.append((start + a, start + b, start + c))
        puffs.append(puff)
        groups.append((start, start + len(template_v), puff, directions))
    return puffs, vertices, faces, groups


def _hashable_config_value(value):
    """Convert Blender property values to stable, hashable primitives.

    Blender FloatVectorProperty values are mathutils.Vector instances, which
    cannot be passed through float().  The preview cache hash must therefore
    serialize scalars, vectors and nested sequences explicitly.
    """
    if isinstance(value, Vector):
        return tuple(round(float(component), 5) for component in value)
    if isinstance(value, (tuple, list)):
        return tuple(_hashable_config_value(item) for item in value)
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return round(value, 5)
    try:
        return round(float(value), 5)
    except (TypeError, ValueError):
        return repr(value)


def _config_hash(pyro: int, cfg: PyroConfig) -> str:
    payload = (
        pyro,
        cfg.effect,
        _hashable_config_value(cfg.color),
        _hashable_config_value(cfg.duration),
        _hashable_config_value(cfg.lifetime),
        _hashable_config_value(cfg.size),
        _hashable_config_value(cfg.intensity),
        _hashable_config_value(cfg.gravity),
        bool(cfg.light_preview),
        tuple(sorted((str(k), _hashable_config_value(v)) for k, v in cfg.params.items())),
    )
    return hashlib.sha1(repr(payload).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Object construction
# ---------------------------------------------------------------------------


def _event_object_name(event: FirePreviewEvent) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in event.drone_name)
    return f"{_PREVIEW_OBJECT_PREFIX}{safe}_F{event.channel + 1}_{event.frame}"


def _delete_preview_object(obj: bpy.types.Object) -> None:
    if obj and obj.name in bpy.data.objects:
        bpy.data.objects.remove(obj, do_unlink=True)


def _ensure_curve_event(scene: bpy.types.Scene, event: FirePreviewEvent, pyro: int, cfg: PyroConfig, runtime: EventRuntime | None) -> EventRuntime:
    collection = _ensure_preview_collection(scene)
    name = _event_object_name(event)
    obj = bpy.data.objects.get(name)
    if obj is not None and obj.type != "CURVE":
        _delete_preview_object(obj)
        obj = None

    chash = _config_hash(pyro, cfg)
    particles = _build_particles(cfg, _stable_seed(event.drone_name, event.channel, event.frame, pyro))
    if runtime is None or runtime.config_hash != chash or runtime.event != event or runtime.pyro != pyro or obj is None:
        if obj is not None:
            _delete_preview_object(obj)
        data = bpy.data.curves.new(name + "_Curve", "CURVE")
        data.dimensions = "3D"
        data.resolution_u = 1
        data.bevel_resolution = 0
        data.fill_mode = "FULL"
        data.bevel_depth = max(0.002, min(0.08, cfg.size * 0.012))
        data.resolution_u = 1
        data.materials.append(_ensure_spark_material(pyro, cfg))
        obj = bpy.data.objects.new(name, data)
        collection.objects.link(obj)
        samples = 3 if cfg.light_preview else 7
        for p in particles:
            spline = data.splines.new("POLY")
            spline.points.add(samples - 1)
            for point in spline.points:
                point.co = (0.0, 0.0, 0.0, 1.0)
                point.radius = 0.0
        runtime = EventRuntime(event, pyro, chash, particles, [], samples, [])
        _RUNTIME[name] = runtime
    _unlink_from_other_collections(obj, collection)
    obj.hide_render = True
    obj.hide_set(True)
    obj.display_type = "TEXTURED"
    obj.color = cfg.color
    obj["sparkshow_synoptic"] = True
    obj["sparkshow_synoptic_type"] = "pyrotechnic_preview"
    obj["sparkshow_pyro_collection"] = _PREVIEW_COLLECTION_NAME
    obj["sparkshow_pyro_profile"] = pyro + 1
    obj["sparkshow_pyro_effect"] = cfg.effect
    obj["sparkshow_fire_channel"] = event.channel + 1
    obj["sparkshow_fire_frame"] = event.frame
    obj["sparkshow_drone"] = event.drone_name
    obj["sparkshow_pyro_config_hash"] = chash
    obj["sparkshow_pyro_duration"] = cfg.duration
    obj["sparkshow_pyro_lifetime"] = cfg.lifetime
    obj["sparkshow_pyro_size"] = cfg.size
    obj["sparkshow_pyro_gravity"] = cfg.gravity
    if cfg.effect == "FOUNTAIN":
        obj["sparkshow_pyro_diffusion_direction"] = tuple(cfg.params.get("fountain_direction", (0.0, 0.0, -1.0)))
        obj["sparkshow_pyro_diffusion_angle"] = float(cfg.params.get("fountain_spread", math.radians(35.0)))
        obj["sparkshow_pyro_trail_length"] = float(cfg.params.get("fountain_trail", 0.28))
        obj["sparkshow_pyro_initial_velocity"] = float(cfg.params.get("fountain_velocity", 8.0))
    if cfg.effect == "DAY_SMOKE":
        obj["sparkshow_pyro_smoke_mesh_resolution"] = int(cfg.params.get("smoke_mesh_resolution", 10))
        obj["sparkshow_pyro_smoke_opacity"] = float(cfg.params.get("smoke_opacity", 0.72))
    return runtime


def _ensure_smoke_event(scene: bpy.types.Scene, event: FirePreviewEvent, pyro: int, cfg: PyroConfig, runtime: EventRuntime | None) -> EventRuntime:
    collection = _ensure_preview_collection(scene)
    name = _event_object_name(event)
    obj = bpy.data.objects.get(name)
    if obj is not None and obj.type != "MESH":
        _delete_preview_object(obj)
        obj = None

    chash = _config_hash(pyro, cfg)
    seed = _stable_seed(event.drone_name, event.channel, event.frame, pyro)
    puffs, verts, faces, groups = _build_smoke_puffs(cfg, seed)
    if runtime is None or runtime.config_hash != chash or runtime.event != event or runtime.pyro != pyro or obj is None:
        if obj is not None:
            _delete_preview_object(obj)
        mesh = bpy.data.meshes.new(name + "_Mesh")
        mesh.from_pydata([tuple(v) for v in verts], [], faces)
        mesh.update(calc_edges=True)
        for poly in mesh.polygons:
            poly.use_smooth = True
        attr = mesh.attributes.get("fw_smoke_color") or mesh.attributes.new("fw_smoke_color", "FLOAT_COLOR", "POINT")
        col = (*cfg.color[:3], min(1.0, max(0.05, cfg.params.get("smoke_opacity", 0.72))))
        for datum in attr.data:
            datum.color = col
        obj = bpy.data.objects.new(name, mesh)
        collection.objects.link(obj)
        obj.data.materials.append(_ensure_smoke_material(pyro, cfg))
        runtime = EventRuntime(event, pyro, chash, [], puffs, 0, groups)
        _RUNTIME[name] = runtime
    _unlink_from_other_collections(obj, collection)
    obj.hide_render = True
    obj.hide_set(True)
    obj.display_type = "TEXTURED"
    obj.color = cfg.color
    obj["sparkshow_synoptic"] = True
    obj["sparkshow_synoptic_type"] = "pyrotechnic_preview"
    obj["sparkshow_pyro_collection"] = _PREVIEW_COLLECTION_NAME
    obj["sparkshow_pyro_profile"] = pyro + 1
    obj["sparkshow_pyro_effect"] = cfg.effect
    obj["sparkshow_fire_channel"] = event.channel + 1
    obj["sparkshow_fire_frame"] = event.frame
    obj["sparkshow_drone"] = event.drone_name
    obj["sparkshow_pyro_config_hash"] = chash
    obj["sparkshow_pyro_duration"] = cfg.duration
    obj["sparkshow_pyro_lifetime"] = cfg.lifetime
    obj["sparkshow_pyro_size"] = cfg.size
    obj["sparkshow_pyro_gravity"] = cfg.gravity
    if cfg.effect == "FOUNTAIN":
        obj["sparkshow_pyro_diffusion_direction"] = tuple(cfg.params.get("fountain_direction", (0.0, 0.0, -1.0)))
        obj["sparkshow_pyro_diffusion_angle"] = float(cfg.params.get("fountain_spread", math.radians(35.0)))
        obj["sparkshow_pyro_trail_length"] = float(cfg.params.get("fountain_trail", 0.28))
        obj["sparkshow_pyro_initial_velocity"] = float(cfg.params.get("fountain_velocity", 8.0))
    if cfg.effect == "DAY_SMOKE":
        obj["sparkshow_pyro_smoke_mesh_resolution"] = int(cfg.params.get("smoke_mesh_resolution", 10))
        obj["sparkshow_pyro_smoke_opacity"] = float(cfg.params.get("smoke_opacity", 0.72))
    return runtime


def _ensure_event_object(scene: bpy.types.Scene, event: FirePreviewEvent, pyro: int, cfg: PyroConfig) -> EventRuntime:
    name = _event_object_name(event)
    runtime = _RUNTIME.get(name)
    if cfg.effect == "DAY_SMOKE":
        return _ensure_smoke_event(scene, event, pyro, cfg, runtime)
    return _ensure_curve_event(scene, event, pyro, cfg, runtime)


# ---------------------------------------------------------------------------
# Per-frame update: ONLY active events are simulated
# ---------------------------------------------------------------------------


def _drone_world_matrix(drone_name: str, scene: bpy.types.Scene) -> Matrix | None:
    """Resolve the current drone object by name before reading its transform.

    Fire preview events intentionally store names instead of live Blender object
    references, because Initialize Show can delete/recreate drone objects and
    invalidate their underlying StructRNA handles.
    """
    try:
        drone = bpy.data.objects.get(drone_name)
        if drone is None:
            return None
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = drone.evaluated_get(depsgraph)
        return evaluated.matrix_world.copy()
    except (ReferenceError, AttributeError, RuntimeError):
        try:
            drone = bpy.data.objects.get(drone_name)
            return drone.matrix_world.copy() if drone is not None else None
        except (ReferenceError, AttributeError, RuntimeError):
            return None


def _update_curve_object(obj: bpy.types.Object, runtime: EventRuntime, cfg: PyroConfig, age_global: float) -> None:
    data = obj.data
    if not isinstance(data, bpy.types.Curve):
        return
    if len(data.splines) != len(runtime.particles):
        return

    for particle, spline in zip(runtime.particles, data.splines):
        age = age_global - particle.birth
        if age < 0.0 or age > particle.life:
            for point in spline.points:
                point.radius = 0.0
            continue
        n = len(spline.points)
        for idx, point in enumerate(spline.points):
            sample_age = age - particle.trail * (1.0 - idx / max(1, n - 1))
            if sample_age < 0.0:
                point.radius = 0.0
                continue
            sample_age = min(sample_age, particle.life)
            pos = _ballistic_position(particle, sample_age)
            point.co = (pos.x, pos.y, pos.z, 1.0)
            fade = min(1.0, sample_age / max(0.001, particle.life * 0.08))
            tail_fade = max(0.0, 1.0 - sample_age / max(0.001, particle.life))
            twinkle = 1.0 + particle.twinkle * 0.35 * math.sin(particle.phase + age_global * 24.0)
            radius = (0.22 + 0.78 * idx / max(1, n - 1)) * tail_fade * fade * twinkle
            if idx == n - 1:
                radius *= 2.2
            point.radius = max(0.0, radius)
    data.update_tag()


def _update_smoke_object(obj: bpy.types.Object, runtime: EventRuntime, cfg: PyroConfig, age_global: float) -> None:
    mesh = obj.data
    if not isinstance(mesh, bpy.types.Mesh):
        return
    for start, end, puff, directions in runtime.puff_vertex_groups:
        age = age_global - puff.birth
        if age < 0.0 or age > puff.life:
            for i in range(start, end):
                mesh.vertices[i].co = puff.base
            continue
        t = min(age, puff.life)
        progress = t / max(0.001, puff.life)
        turb = Vector((
            math.sin(puff.phase + t * 1.7),
            math.cos(puff.phase * 0.73 + t * 1.35),
            math.sin(puff.phase * 0.41 + t * 0.95),
        )) * puff.turbulence * progress
        center = puff.base + puff.velocity * t + turb
        growth = 0.22 + 1.15 * progress
        fade = max(0.0, 1.0 - progress) ** max(0.35, float(cfg.params.get("smoke_dissipation", 1.0)) * 0.8)
        color_attr = mesh.attributes.get("fw_smoke_color")
        smoke_alpha = max(0.02, puff.opacity * fade)
        for offset, i in enumerate(range(start, end)):
            direction = directions[offset]
            noise = 1.0 + 0.08 * math.sin(puff.phase + i * 0.71)
            mesh.vertices[i].co = center + Vector((
                direction.x * puff.scale.x * growth * noise,
                direction.y * puff.scale.y * growth * noise,
                direction.z * puff.scale.z * growth * noise,
            ))
            if color_attr is not None:
                c = color_attr.data[i].color
                color_attr.data[i].color = (cfg.color[0], cfg.color[1], cfg.color[2], smoke_alpha)
    mesh.update_tag()


def _runtime_lifetime(runtime: EventRuntime, cfg: PyroConfig) -> float:
    """Return the maximum visible age of an event from emission duration + particle life."""
    max_tail = 0.0
    if runtime.particles:
        max_tail = max((p.birth + p.life for p in runtime.particles), default=0.0)
    elif runtime.smoke_puffs:
        max_tail = max((p.birth + p.life for p in runtime.smoke_puffs), default=0.0)
    return max(cfg.duration, max_tail, cfg.duration + cfg.lifetime * 0.08)


def _update_event(scene: bpy.types.Scene, runtime: EventRuntime, cfg: PyroConfig) -> None:
    obj = bpy.data.objects.get(_event_object_name(runtime.event))
    if obj is None:
        return
    matrix = _drone_world_matrix(runtime.event.drone_name, scene)
    if matrix is None:
        obj.hide_set(True)
        obj["sparkshow_synoptic_visible"] = False
        return
    obj.matrix_world = matrix

    age = (scene.frame_current - runtime.event.frame) / FPS
    event_end = _runtime_lifetime(runtime, cfg)
    active = 0.0 <= age <= event_end
    obj.hide_set(not active)
    obj["sparkshow_synoptic_visible"] = bool(active)
    obj["sparkshow_current_age"] = max(0.0, age)
    obj["sparkshow_pyro_end_age"] = event_end
    if not active:
        return
    if cfg.effect == "DAY_SMOKE":
        _update_smoke_object(obj, runtime, cfg, age)
    else:
        _update_curve_object(obj, runtime, cfg, age)


def _update_all(scene: bpy.types.Scene) -> None:
    if scene is None:
        return
    if bool(scene.get("sparkshow_pyro_bake_active", False)):
        return
    lightshow = get_lightshow(scene)
    from . import preview_engines
    engine = preview_engines._effective_engine(lightshow)
    if engine == "GPU_POINTS":
        preview_engines.update_gpu(scene)
        return
    if engine == "INSTANCED_MESH":
        preview_engines.update_instanced(scene)
        return
    if engine == "PARTICLES":
        preview_engines.update_particles(scene)
        return
    if not getattr(lightshow, "fire_preview_enabled", False):
        for runtime in list(_RUNTIME.values()):
            obj = bpy.data.objects.get(_event_object_name(runtime.event))
            if obj is not None:
                obj.hide_set(True)
                obj["sparkshow_synoptic_visible"] = False
        return
    for name, runtime in list(_RUNTIME.items()):
        obj = bpy.data.objects.get(_event_object_name(runtime.event))
        if obj is None:
            _RUNTIME.pop(name, None)
            continue
        if bpy.data.objects.get(runtime.event.drone_name) is None:
            obj.hide_set(True)
            obj["sparkshow_synoptic_visible"] = False
            continue
        cfg = _pyro_settings(lightshow, runtime.pyro)
        _update_event(scene, runtime, cfg)


@persistent
def _frame_change_handler(scene: bpy.types.Scene) -> None:
    _update_all(scene)


_frame_change_handler.__name__ = _HANDLER_NAME


# ---------------------------------------------------------------------------
# Public refresh / registration
# ---------------------------------------------------------------------------


def _purge_legacy_preview_locations(preview_collection: bpy.types.Collection) -> None:
    """Move/unlink every legacy preview object out of drone-family collections."""
    for obj in list(bpy.data.objects):
        if not obj.name.startswith(_PREVIEW_OBJECT_PREFIX):
            continue
        _unlink_from_other_collections(obj, preview_collection)
        obj.parent = None


def _remove_stale_preview_objects(keep: set[str], preview_collection: bpy.types.Collection) -> None:
    for obj in list(bpy.data.objects):
        if obj.name.startswith(_PREVIEW_OBJECT_PREFIX) and obj.name not in keep:
            _RUNTIME.pop(obj.name, None)
            _delete_preview_object(obj)
    for obj in list(preview_collection.objects):
        if obj.name.startswith(_PREVIEW_OBJECT_PREFIX) and obj.name not in keep:
            _delete_preview_object(obj)


def refresh_preview(scene: bpy.types.Scene | None = None) -> None:
    scene = scene or bpy.context.scene
    if scene is None:
        return

    if bool(scene.get("sparkshow_pyro_bake_active", False)):
        try:
            from . import preview_engines
            preview_engines.cleanup_all_engines()
        except Exception:
            pass
        return

    lightshow = get_lightshow(scene)
    from . import preview_engines
    engine = preview_engines._effective_engine(lightshow)
    if engine == "GPU_POINTS":
        preview_engines.refresh_gpu(scene)
        return
    if engine == "INSTANCED_MESH":
        preview_engines.refresh_instanced(scene)
        return
    if engine == "PARTICLES":
        preview_engines.refresh_particles(scene)
        return

    preview_engines.cleanup_all_engines()
    collection = _ensure_preview_collection(scene)
    _purge_legacy_preview_locations(collection)

    if not getattr(lightshow, "fire_preview_enabled", False):
        _update_all(scene)
        return

    keep: set[str] = set()
    active_runtime_names: set[str] = set()
    for event in _cached_fire_events(scene):
        pyro = _assigned_pyro(lightshow, event.channel)
        cfg = _pyro_settings(lightshow, pyro)
        runtime = _ensure_event_object(scene, event, pyro, cfg)
        name = _event_object_name(event)
        keep.add(name)
        active_runtime_names.add(name)
        _RUNTIME[name] = runtime

    _remove_stale_preview_objects(keep, collection)
    scene["sparkshow_pyro_preview_event_count"] = len(keep)
    _update_all(scene)


def rebuild_preview(context: bpy.types.Context) -> None:
    refresh_preview(context.scene)
    if context.screen:
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()



def register() -> None:
    global _EVENT_CACHE_SCENE_ID, _EVENT_CACHE_REVISION, _EVENT_CACHE, _RUNTIME
    unregister_handlers_only()
    from . import preview_engines
    preview_engines.register()
    _EVENT_CACHE_SCENE_ID = None
    _EVENT_CACHE_REVISION = -1
    _EVENT_CACHE = []
    _RUNTIME = {}
    try:
        refresh_preview(bpy.context.scene)
    except Exception:
        pass



def unregister_handlers_only() -> None:
    for handler in list(bpy.app.handlers.frame_change_post):
        if getattr(handler, "__name__", "") == _HANDLER_NAME:
            bpy.app.handlers.frame_change_post.remove(handler)


def unregister() -> None:
    global _EVENT_CACHE_SCENE_ID, _EVENT_CACHE_REVISION, _EVENT_CACHE, _RUNTIME
    unregister_handlers_only()
    try:
        from . import preview_engines
        preview_engines.unregister()
    except Exception:
        pass
    for obj in list(bpy.data.objects):
        if obj.name.startswith(_PREVIEW_OBJECT_PREFIX):
            _delete_preview_object(obj)
    _RUNTIME = {}
    _EVENT_CACHE_SCENE_ID = None
    _EVENT_CACHE_REVISION = -1
    _EVENT_CACHE = []


def clear_event_snapshots(drone: bpy.types.Object) -> None:
    for key in list(drone.keys()):
        if isinstance(key, str) and key.startswith("sparkshow_pyro_preview:"):
            del drone[key]
