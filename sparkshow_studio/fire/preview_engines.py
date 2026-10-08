"""Selectable lightweight viewport engines for Sparkshow Studio Pyro preview.

Engines are strictly isolated in ``Sparkshow Pyrotechnics`` (or GPU-only runtime
state) and never add anything to drone-family collections.
"""
from __future__ import annotations

import math
from typing import Any

import bpy

from mathutils import Vector

from ..setup import FPS, get_lightshow
from . import preview as core

_ENGINE_COLLECTION = "Sparkshow Pyrotechnics"
_INSTANCE_PREFIX = "Sparkshow_PyroInstance_"
_GPU_PREFIX = "Sparkshow_PyroGPUEvent_"
_GPU_HANDLER = None
_GPU_SHADER = None
_GPU_BATCH = []
_GPU_POINTS = []
_GPU_COLORS = []
_GPU_SIZES = []
_GPU_GLOWS = []
_GPU_POINT_SIZE = 9.0
_GPU_MAX_POINTS_LIGHT = 18000
_GPU_MAX_POINTS_FULL = 70000


def _ensure_collection(scene: bpy.types.Scene) -> bpy.types.Collection:
    col = bpy.data.collections.get(_ENGINE_COLLECTION)
    if col is None:
        col = bpy.data.collections.new(_ENGINE_COLLECTION)
        scene.collection.children.link(col)
    return col


def _unlink_others(obj: bpy.types.Object, keep: bpy.types.Collection) -> None:
    for col in list(obj.users_collection):
        if col != keep:
            try:
                col.objects.unlink(obj)
            except RuntimeError:
                pass
    if obj.name not in keep.objects:
        try:
            keep.objects.link(obj)
        except RuntimeError:
            pass
    obj.parent = None


def _safe_name(event: core.FirePreviewEvent, prefix: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in event.drone_name)
    return f"{prefix}{safe}_F{event.channel + 1}_{event.frame}"


def _runtime_for(event: core.FirePreviewEvent, pyro: int, cfg: core.PyroConfig) -> core.EventRuntime:
    seed = core._stable_seed(event.drone_name, event.channel, event.frame, pyro)
    chash = core._config_hash(pyro, cfg)
    particles = core._build_particles(cfg, seed)
    puffs: list[core.SmokePuff] = []
    groups: list[tuple[int, int, core.SmokePuff, list[Vector]]] = []
    if cfg.effect == "DAY_SMOKE":
        puffs, _, _, groups = core._build_smoke_puffs(cfg, seed)
    return core.EventRuntime(event, pyro, chash, particles, puffs, 5, groups)


def _cleanup_prefix(prefix: str) -> None:
    for obj in list(bpy.data.objects):
        if obj.name.startswith(prefix):
            bpy.data.objects.remove(obj, do_unlink=True)


def cleanup_all_engines() -> None:
    global _GPU_BATCH, _GPU_POINTS, _GPU_COLORS, _GPU_SIZES, _GPU_GLOWS
    _cleanup_prefix(_INSTANCE_PREFIX)
    _cleanup_prefix(_GPU_PREFIX)
    _cleanup_prefix(core._PREVIEW_OBJECT_PREFIX)
    # Particle engine objects use its own namespace; keep cleanup lazy to avoid
    # importing particle code when it is not selected.
    _cleanup_prefix("Sparkshow_ParticlePyro_")
    _cleanup_prefix("Sparkshow_PyroParticle_")
    _cleanup_prefix("Sparkshow_ParticleAsset_")
    _GPU_BATCH = []
    _GPU_POINTS = []
    _GPU_COLORS = []
    _GPU_SIZES = []


def _effective_engine(lightshow) -> str:
    mode = str(getattr(lightshow, "fire_preview_renderer", "AUTO"))
    if mode == "AUTO":
        return "GPU_POINTS" if bool(getattr(lightshow, "fire_preview_light_mode", True)) else "INSTANCED_MESH"
    return mode


def _ensure_instance_material(kind: str) -> bpy.types.Material:
    name = f"Sparkshow Pyro Instance Material {kind}"
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    if kind == "SMOKE":
        bsdf = nodes.new("ShaderNodeBsdfPrincipled")
        info = nodes.new("ShaderNodeObjectInfo")
        bsdf.inputs["Roughness"].default_value = 1.0
        links.new(info.outputs["Color"], bsdf.inputs["Base Color"])
        if "Alpha" in info.outputs and "Alpha" in bsdf.inputs:
            links.new(info.outputs["Alpha"], bsdf.inputs["Alpha"])
        links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
        try:
            mat.surface_render_method = 'DITHERED'
        except Exception:
            try:
                mat.blend_method = 'BLEND'
            except Exception:
                pass
    else:
        em = nodes.new("ShaderNodeEmission")
        info = nodes.new("ShaderNodeObjectInfo")
        links.new(info.outputs["Color"], em.inputs["Color"])
        links.new(em.outputs["Emission"], out.inputs["Surface"])
    return mat


def _ensure_instance_gn(kind: str) -> bpy.types.GeometryNodeTree:
    name = f"Sparkshow Pyro Instance GN {kind}"
    ng = bpy.data.node_groups.get(name)
    if ng is not None:
        return ng
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    ng.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    inp = ng.nodes.new("NodeGroupInput")
    out = ng.nodes.new("NodeGroupOutput")
    points = inp.outputs.get("Geometry")
    inst = ng.nodes.new("GeometryNodeInstanceOnPoints")
    if kind == "SMOKE":
        ico = ng.nodes.new("GeometryNodeMeshIcoSphere")
        ico.inputs["Subdivisions"].default_value = 1
        ico.inputs["Radius"].default_value = 0.35
    else:
        ico = ng.nodes.new("GeometryNodeMeshIcoSphere")
        ico.inputs["Subdivisions"].default_value = 0
        ico.inputs["Radius"].default_value = 0.045
    mat = ng.nodes.new("GeometryNodeSetMaterial")
    mat.inputs["Material"].default_value = _ensure_instance_material(kind)
    ng.links.new(points, inst.inputs["Points"])
    ng.links.new(ico.outputs["Mesh"], inst.inputs["Instance"])
    ng.links.new(inst.outputs["Instances"], mat.inputs["Geometry"])
    ng.links.new(mat.outputs["Geometry"], out.inputs["Geometry"])
    return ng


def _ensure_instance_object(scene: bpy.types.Scene, event: core.FirePreviewEvent, pyro: int, cfg: core.PyroConfig, runtime: core.EventRuntime | None) -> core.EventRuntime:
    collection = _ensure_collection(scene)
    name = _safe_name(event, _INSTANCE_PREFIX)
    obj = bpy.data.objects.get(name)
    kind = "SMOKE" if cfg.effect == "DAY_SMOKE" else "SPARK"
    if obj is not None and (obj.type != "MESH" or obj.name.startswith(_INSTANCE_PREFIX) is False):
        bpy.data.objects.remove(obj, do_unlink=True)
        obj = None
    if runtime is None or runtime.config_hash != core._config_hash(pyro, cfg) or obj is None:
        runtime = _runtime_for(event, pyro, cfg)
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)
        mesh = bpy.data.meshes.new(name + "_Mesh")
        count = len(runtime.smoke_puffs) if kind == "SMOKE" else len(runtime.particles)
        mesh.from_pydata([(0.0, 0.0, 0.0)] * max(1, count), [], [])
        mesh.update()
        obj = bpy.data.objects.new(name, mesh)
        collection.objects.link(obj)
        obj.data.materials.append(_ensure_instance_material(kind))
        mod = obj.modifiers.new("Sparkshow Pyro Instances", "NODES")
        mod.node_group = _ensure_instance_gn(kind)
    _unlink_others(obj, collection)
    obj.hide_render = True
    obj.display_type = "TEXTURED"
    obj.color = cfg.color
    obj["sparkshow_synoptic"] = True
    obj["sparkshow_synoptic_type"] = "pyrotechnic_preview"
    obj["sparkshow_pyro_collection"] = _ENGINE_COLLECTION
    obj["sparkshow_pyro_renderer"] = "INSTANCED_MESH"
    obj["sparkshow_pyro_profile"] = pyro + 1
    obj["sparkshow_pyro_effect"] = cfg.effect
    obj["sparkshow_fire_channel"] = event.channel + 1
    obj["sparkshow_fire_frame"] = event.frame
    obj["sparkshow_drone"] = event.drone_name
    return runtime


def _update_instance_event(scene: bpy.types.Scene, runtime: core.EventRuntime, cfg: core.PyroConfig) -> None:
    obj = bpy.data.objects.get(_safe_name(runtime.event, _INSTANCE_PREFIX))
    if obj is None or obj.type != "MESH":
        return
    matrix = core._drone_world_matrix(runtime.event.drone_name, scene)
    if matrix is None:
        obj.hide_set(True)
        return
    obj.matrix_world = matrix
    age = (scene.frame_current - runtime.event.frame) / FPS
    end = core._runtime_lifetime(runtime, cfg)
    active = 0.0 <= age <= end
    obj.hide_set(not active)
    obj["sparkshow_synoptic_visible"] = active
    if not active:
        return
    if cfg.effect == "DAY_SMOKE":
        points = []
        for puff in runtime.smoke_puffs:
            a = age - puff.birth
            if 0.0 <= a <= puff.life:
                t = a
                turb = Vector((math.sin(puff.phase + t * 1.7), math.cos(puff.phase * 0.73 + t * 1.35), math.sin(puff.phase * 0.41 + t * 0.95))) * puff.turbulence * min(1.0, a / max(0.01, puff.life))
                center = puff.base + puff.velocity * t + turb
                growth = 0.22 + 1.15 * min(1.0, t / max(0.01, puff.life))
                points.append(center)
            else:
                points.append(Vector((0.0, 0.0, -10000.0)))
    else:
        points = []
        for p in runtime.particles:
            a = age - p.birth
            points.append(core._ballistic_position(p, min(max(a, 0.0), p.life)) if 0.0 <= a <= p.life else Vector((0.0, 0.0, -10000.0)))
    if not points:
        return
    verts = obj.data.vertices
    if len(verts) != len(points):
        return
    for v, p in zip(verts, points):
        v.co = p
    obj.data.update_tag()


def refresh_instanced(scene: bpy.types.Scene) -> None:
    if bool(scene.get("sparkshow_pyro_bake_active", False)):
        cleanup_all_engines()
        return

    cleanup_all_engines()
    lightshow = get_lightshow(scene)
    _INSTANCE_RUNTIMES.clear()
    if not getattr(lightshow, "fire_preview_enabled", False):
        return
    col = _ensure_collection(scene)
    runtimes: dict[str, core.EventRuntime] = {}
    scene["sparkshow_pyro_renderer_active"] = "INSTANCED_MESH"
    for event in core._cached_fire_events(scene):
        pyro = core._assigned_pyro(lightshow, event.channel)
        cfg = core._pyro_settings(lightshow, pyro)
        key = _safe_name(event, _INSTANCE_PREFIX)
        runtimes[key] = _ensure_instance_object(scene, event, pyro, cfg, None)
    scene["sparkshow_pyro_preview_event_count"] = len(runtimes)
    for rt in runtimes.values():
        _update_instance_event(scene, rt, core._pyro_settings(lightshow, rt.pyro))
    scene["sparkshow_pyro_instance_runtime"] = True
    # store runtime in module-level cache for frame updates
    _INSTANCE_RUNTIMES.update(runtimes)

_INSTANCE_RUNTIMES: dict[str, core.EventRuntime] = {}
_GPU_RUNTIMES: dict[str, core.EventRuntime] = {}


def update_instanced(scene: bpy.types.Scene) -> None:
    if bool(scene.get("sparkshow_pyro_bake_active", False)):
        cleanup_all_engines()
        return

    lightshow = get_lightshow(scene)
    if not getattr(lightshow, "fire_preview_enabled", False):
        for rt in _INSTANCE_RUNTIMES.values():
            obj = bpy.data.objects.get(_safe_name(rt.event, _INSTANCE_PREFIX))
            if obj:
                obj.hide_set(True)
        return
    for rt in list(_INSTANCE_RUNTIMES.values()):
        cfg = core._pyro_settings(lightshow, rt.pyro)
        _update_instance_event(scene, rt, cfg)


def _gpu_make_shader():
    """Create a small self-contained 3D point shader for Blender 4.1.

    Built-in shader names changed across Blender releases; using a tiny custom
    shader here avoids silent failure and gives us a soft luminous point in the
    viewport without creating mesh/curve geometry.
    """
    try:
        import gpu
        info = gpu.types.GPUShaderCreateInfo()
        info.push_constant('MAT4', 'viewProjectionMatrix')
        info.push_constant('FLOAT', 'pointSize')
        info.push_constant('FLOAT', 'pointGlow')
        info.push_constant('VEC4', 'pointColor')
        info.vertex_in(0, 'VEC3', 'position')
        info.fragment_out(0, 'VEC4', 'FragColor')
        info.vertex_source(
            "void main()"
            "{"
            "  gl_Position = viewProjectionMatrix * vec4(position, 1.0);"
            "  gl_PointSize = pointSize;"
            "}"
        )
        info.fragment_source(
            "void main()"
            "{"
            "  float d = distance(gl_PointCoord, vec2(0.5));"
            "  float glow = clamp(pointGlow, 0.0, 4.0);"
            "  float core = 1.0 - smoothstep(0.04, 0.28, d);"
            "  float halo = pow(max(0.0, 1.0 - d * 2.0), 2.2);"
            "  float a = max(core, halo * glow * 0.55);"
            "  vec3 rgb = pointColor.rgb * (1.0 + halo * glow * 1.8);"
            "  FragColor = vec4(rgb, pointColor.a * clamp(a, 0.0, 1.0));"
            "}"
        )
        shader = gpu.shader.create_from_info(info)
        del info
        return shader
    except Exception:
        return None


def _gpu_build_batch():
    """Build point batches grouped by color and size."""
    global _GPU_BATCH, _GPU_SHADER
    _GPU_BATCH = []
    _GPU_SHADER = _gpu_make_shader()
    if _GPU_SHADER is None or not _GPU_POINTS:
        return
    try:
        from gpu_extras.batch import batch_for_shader
    except Exception:
        return

    groups = {}
    for pos, color, size, glow in zip(_GPU_POINTS, _GPU_COLORS, _GPU_SIZES, _GPU_GLOWS):
        key = (tuple(round(float(c), 4) for c in color), round(float(size), 2), round(float(glow), 2))
        groups.setdefault(key, []).append(pos)

    for (color, size, glow), positions in groups.items():
        try:
            batch = batch_for_shader(_GPU_SHADER, 'POINTS', {'position': positions})
            _GPU_BATCH.append((batch, color, size, glow))
        except Exception:
            continue


def _gpu_draw():
    batches = _GPU_BATCH
    shader = _GPU_SHADER
    if not batches or shader is None:
        return
    try:
        import gpu
        region = bpy.context.region_data
        if region is None:
            return
        matrix = region.perspective_matrix
        gpu.state.depth_test_set('LESS_EQUAL')
        gpu.state.depth_mask_set(False)
        gpu.state.blend_set('ALPHA')
        shader.bind()
        shader.uniform_float('viewProjectionMatrix', matrix)
        for batch, color, size, glow in batches:
            shader.uniform_float('pointSize', size)
            shader.uniform_float('pointGlow', glow)
            shader.uniform_float('pointColor', color)
            batch.draw(shader)
    except Exception:
        pass
    finally:
        try:
            gpu.state.blend_set('NONE')
            gpu.state.depth_mask_set(True)
            gpu.state.depth_test_set('NONE')
        except Exception:
            pass

def register_gpu_handler() -> None:
    global _GPU_HANDLER
    if _GPU_HANDLER is not None:
        return
    try:
        _GPU_HANDLER = bpy.types.SpaceView3D.draw_handler_add(_gpu_draw, (), "WINDOW", "POST_VIEW")
    except Exception:
        _GPU_HANDLER = None


def unregister_gpu_handler() -> None:
    global _GPU_HANDLER
    if _GPU_HANDLER is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_GPU_HANDLER, "WINDOW")
        except Exception:
            pass
    _GPU_HANDLER = None


def refresh_gpu(scene: bpy.types.Scene) -> None:
    if bool(scene.get("sparkshow_pyro_bake_active", False)):
        cleanup_all_engines()
        return

    cleanup_all_engines()
    register_gpu_handler()
    _GPU_RUNTIMES.clear()
    lightshow = get_lightshow(scene)
    if not getattr(lightshow, "fire_preview_enabled", False):
        update_gpu(scene)
        return
    for event in core._cached_fire_events(scene):
        pyro = core._assigned_pyro(lightshow, event.channel)
        cfg = core._pyro_settings(lightshow, pyro)
        _GPU_RUNTIMES[_safe_name(event, _GPU_PREFIX)] = _runtime_for(event, pyro, cfg)
        # Lightweight synoptic handle, no geometry.
        col = _ensure_collection(scene)
        name = _safe_name(event, _GPU_PREFIX)
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "EMPTY":
            if obj is not None:
                bpy.data.objects.remove(obj, do_unlink=True)
            obj = bpy.data.objects.new(name, None)
            col.objects.link(obj)
        _unlink_others(obj, col)
        obj.empty_display_type = "SPHERE"
        obj.empty_display_size = 0.02
        obj.hide_set(True)
        obj["sparkshow_synoptic"] = True
        obj["sparkshow_synoptic_type"] = "pyrotechnic_preview"
        obj["sparkshow_pyro_renderer"] = "GPU_POINTS"
        obj["sparkshow_pyro_collection"] = _ENGINE_COLLECTION
        obj["sparkshow_pyro_profile"] = pyro + 1
        obj["sparkshow_pyro_effect"] = cfg.effect
        obj["sparkshow_fire_channel"] = event.channel + 1
        obj["sparkshow_fire_frame"] = event.frame
        obj["sparkshow_drone"] = event.drone_name
    update_gpu(scene)
    try:
        for area in bpy.context.screen.areas if bpy.context.screen else ():
            if area.type == "VIEW_3D":
                area.tag_redraw()
    except Exception:
        pass


def update_gpu(scene: bpy.types.Scene) -> None:
    if bool(scene.get("sparkshow_pyro_bake_active", False)):
        cleanup_all_engines()
        return

    global _GPU_POINTS, _GPU_COLORS, _GPU_SIZES, _GPU_GLOWS
    _GPU_POINTS = []
    _GPU_COLORS = []
    _GPU_SIZES = []
    _GPU_GLOWS = []
    lightshow = get_lightshow(scene)
    if not getattr(lightshow, "fire_preview_enabled", False):
        _gpu_build_batch()
        return
    max_points = _GPU_MAX_POINTS_LIGHT if bool(getattr(lightshow, "fire_preview_light_mode", True)) else _GPU_MAX_POINTS_FULL
    for rt in list(_GPU_RUNTIMES.values()):
        cfg = core._pyro_settings(lightshow, rt.pyro)
        matrix = core._drone_world_matrix(rt.event.drone_name, scene)
        if matrix is None:
            continue
        age = (scene.frame_current - rt.event.frame) / FPS
        if age < 0.0 or age > core._runtime_lifetime(rt, cfg):
            continue
        brightness = max(0.75, min(4.0, float(cfg.intensity)))
        alpha = max(0.18, min(1.0, float(cfg.color[3])))
        color = (
            float(cfg.color[0]) * brightness,
            float(cfg.color[1]) * brightness,
            float(cfg.color[2]) * brightness,
            alpha,
        )
        configured_size = float(cfg.params.get("gpu_particle_size", _GPU_POINT_SIZE))
        point_size = max(1.0, min(48.0, configured_size))
        configured_glow = float(cfg.params.get("gpu_glow", 1.0))
        glow = max(0.0, min(4.0, configured_glow))
        if cfg.effect == "DAY_SMOKE":
            candidates = []
            for puff in rt.smoke_puffs:
                a = age - puff.birth
                if 0.0 <= a <= puff.life:
                    progress = min(1.0, a / max(0.01, puff.life))
                    center = puff.base + puff.velocity * a
                    candidates.append(center)
        else:
            candidates = []
            for p in rt.particles:
                a = age - p.birth
                if 0.0 <= a <= p.life:
                    candidates.append(core._ballistic_position(p, a))
        if not candidates:
            continue
        remaining = max_points - len(_GPU_POINTS)
        if remaining <= 0:
            break
        stride = max(1, math.ceil(len(candidates) / remaining))
        for local in candidates[::stride]:
            world = matrix @ local.to_4d()
            _GPU_POINTS.append((world.x, world.y, world.z))
            _GPU_COLORS.append(color)
            _GPU_SIZES.append(point_size)
            _GPU_GLOWS.append(glow)
    _gpu_build_batch()


def refresh_particles(scene: bpy.types.Scene) -> None:
    if bool(scene.get("sparkshow_pyro_bake_active", False)):
        cleanup_all_engines()
        return

    cleanup_all_engines()
    from .particle_preview import refresh_preview
    refresh_preview(scene)


def update_particles(scene: bpy.types.Scene) -> None:
    if bool(scene.get("sparkshow_pyro_bake_active", False)):
        cleanup_all_engines()
        return

    # Native particle systems evaluate themselves through Blender. A redraw is
    # enough; no Python simulation is performed here.
    if bpy.context.screen:
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def register() -> None:
    register_gpu_handler()


def unregister() -> None:
    unregister_gpu_handler()
    cleanup_all_engines()
    _INSTANCE_RUNTIMES.clear()
    _GPU_RUNTIMES.clear()
