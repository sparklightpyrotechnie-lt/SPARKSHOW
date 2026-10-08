"""Render-safe Pyro bake for Sparkshow Studio / Blender 4.1.

The bake converts Fire preview events into dedicated, renderable point-cache
objects.  The baked objects live only in ``Sparkshow Pyro Bake`` and are never
linked to drone-family collections.  Their animation is evaluated entirely by
Geometry Nodes from static per-point attributes plus Scene Time, so no Python
frame handler is involved during render.
"""
from __future__ import annotations

import math

import bpy
from mathutils import Vector

from ..setup import FPS, get_lightshow
from . import preview as core

BAKE_COLLECTION = "Sparkshow Pyro Bake"
BAKE_SPARK_PREFIX = "Sparkshow_PyroBake_Sparks_"
BAKE_SMOKE_PREFIX = "Sparkshow_PyroBake_Smoke_"
BAKE_STEP_DEFAULT = 1


def _ensure_bake_collection(scene: bpy.types.Scene) -> bpy.types.Collection:
    col = bpy.data.collections.get(BAKE_COLLECTION)
    if col is None:
        col = bpy.data.collections.new(BAKE_COLLECTION)
    if col.name not in scene.collection.children:
        try:
            scene.collection.children.link(col)
        except RuntimeError:
            pass
    col.hide_render = False
    col.hide_viewport = False
    return col


def clear_bake(scene: bpy.types.Scene | None = None) -> int:
    scene = scene or bpy.context.scene
    removed = 0
    for obj in list(bpy.data.objects):
        if obj.name.startswith((BAKE_SPARK_PREFIX, BAKE_SMOKE_PREFIX)):
            bpy.data.objects.remove(obj, do_unlink=True)
            removed += 1
    col = bpy.data.collections.get(BAKE_COLLECTION)
    if col is not None and not col.objects:
        try:
            bpy.data.collections.remove(col)
        except RuntimeError:
            pass
    if scene is not None:
        scene["sparkshow_pyro_bake_active"] = False
        scene["sparkshow_pyro_bake_frame_start"] = 0
        scene["sparkshow_pyro_bake_frame_end"] = 0
        scene["sparkshow_pyro_bake_step"] = 0
        scene["sparkshow_pyro_bake_event_count"] = 0
    return removed


def _events_for_range(scene: bpy.types.Scene, start: int, end: int) -> list[core.FirePreviewEvent]:
    return [event for event in core._cached_fire_events(scene) if start <= event.frame <= end]


def _pyro_cfg_for_event(cfg: core.PyroConfig) -> core.PyroConfig:
    """Return the Pyro profile configuration unchanged for this Fire event.

    Pyro is intentionally independent from drone lighting. A drone only
    triggers the effect; the Pyro profile supplies its own color and all other
    visual parameters.
    """
    return core.PyroConfig(
        cfg.effect,
        tuple(float(v) for v in cfg.color[:4]),
        cfg.duration,
        cfg.lifetime,
        cfg.size,
        cfg.intensity,
        cfg.gravity,
        dict(cfg.params),
        cfg.light_preview,
    )


def _attribute(mesh: bpy.types.Mesh, name: str, data_type: str):
    return mesh.attributes.new(name, data_type, 'POINT')


def _set_vector_attr(attr, values: list[Vector]) -> None:
    for index, value in enumerate(values):
        attr.data[index].vector = tuple(value)


def _set_float_attr(attr, values: list[float]) -> None:
    for index, value in enumerate(values):
        attr.data[index].value = float(value)


def _ensure_render_material(kind: str, pyro: int, cfg: core.PyroConfig, *, role: str = "RENDER") -> bpy.types.Material:
    """Create a dedicated material for the Pyro bake role.

    ``RENDER`` and ``VIEWPORT`` are deliberately separate for Day Smoke: the
    viewport uses a light surface cloud, while the render object uses a real
    volume shader. This avoids forcing the viewport to evaluate volumetrics.
    """
    color_key = "_".join(f"{float(v):.4f}" for v in cfg.color[:3])
    safe_effect = str(cfg.effect).replace(" ", "_").replace("/", "_")
    name = f"Sparkshow Pyro {role} Material {kind} {pyro + 1} {safe_effect} {color_key}"
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (820, 0)

    if kind == "SMOKE":
        texcoord = nodes.new("ShaderNodeTexCoord")
        texcoord.location = (-1200, 180)

        mapping = nodes.new("ShaderNodeMapping")
        mapping.location = (-1020, 180)
        links.new(texcoord.outputs["Generated"], mapping.inputs["Vector"])

        noise = nodes.new("ShaderNodeTexNoise")
        noise.location = (-800, 260)
        noise.noise_dimensions = "3D"
        noise.inputs["Scale"].default_value = 2.1
        noise.inputs["Detail"].default_value = 4.0
        noise.inputs["Roughness"].default_value = 0.72
        noise.inputs["Distortion"].default_value = 0.15
        links.new(mapping.outputs["Vector"], noise.inputs["Vector"])

        noise2 = nodes.new("ShaderNodeTexNoise")
        noise2.location = (-800, 40)
        noise2.noise_dimensions = "3D"
        noise2.inputs["Scale"].default_value = 6.0
        noise2.inputs["Detail"].default_value = 2.0
        noise2.inputs["Roughness"].default_value = 0.78
        noise2.inputs["Distortion"].default_value = 0.20
        links.new(mapping.outputs["Vector"], noise2.inputs["Vector"])

        mix_noise = nodes.new("ShaderNodeMixRGB")
        mix_noise.blend_type = "MULTIPLY"
        mix_noise.inputs[0].default_value = 0.35
        mix_noise.location = (-540, 180)
        links.new(noise.outputs["Fac"], mix_noise.inputs[1])
        links.new(noise2.outputs["Fac"], mix_noise.inputs[2])

        density_ramp = nodes.new("ShaderNodeValToRGB")
        density_ramp.location = (-300, 180)
        density_ramp.color_ramp.elements[0].position = 0.14
        density_ramp.color_ramp.elements[1].position = 0.58
        density_ramp.color_ramp.elements[0].color = (0.0, 0.0, 0.0, 1.0)
        density_ramp.color_ramp.elements[1].color = (0.98, 0.98, 0.98, 1.0)
        links.new(mix_noise.outputs[0], density_ramp.inputs["Fac"])

        # Explicitly convert the ramp's RGB output to a scalar. This avoids
        # implicit RGB-to-float conversion in Blender's shader sockets.
        density_value = nodes.new("ShaderNodeRGBToBW")
        density_value.location = (-60, 180)
        links.new(density_ramp.outputs["Color"], density_value.inputs["Color"])

        opacity = max(0.01, min(1.0, float(cfg.params.get("smoke_opacity", 0.35))))
        opacity_node = nodes.new("ShaderNodeValue")
        opacity_node.location = (-300, -10)
        opacity_node.outputs[0].default_value = opacity

        density_scale = nodes.new("ShaderNodeMath")
        density_scale.operation = "MULTIPLY"
        density_scale.location = (140, 180)
        links.new(density_value.outputs["Val"], density_scale.inputs[0])
        links.new(opacity_node.outputs[0], density_scale.inputs[1])

        if role == "RENDER":
            volume = nodes.new("ShaderNodeVolumePrincipled")
            volume.location = (300, 80)
            volume.inputs["Color"].default_value = (*cfg.color[:3], 1.0)
            if "Density" in volume.inputs:
                links.new(density_scale.outputs[0], volume.inputs["Density"])
            if "Anisotropy" in volume.inputs:
                volume.inputs["Anisotropy"].default_value = 0.05
            links.new(volume.outputs["Volume"], output.inputs["Volume"])
        else:
            # Lightweight viewport cloud. Soft transparency is intended for
            # Material Preview/Rendered; the object also gets an object colour
            # so Solid/object-colour viewport modes remain readable.
            principled = nodes.new("ShaderNodeBsdfPrincipled")
            principled.location = (230, 150)
            principled.inputs["Base Color"].default_value = (*cfg.color[:3], 1.0)
            principled.inputs["Roughness"].default_value = 1.0
            if "Specular IOR Level" in principled.inputs:
                principled.inputs["Specular IOR Level"].default_value = 0.0
            elif "Specular" in principled.inputs:
                principled.inputs["Specular"].default_value = 0.0
            # Alpha comes from the procedural density mask multiplied by the
            # profile opacity. Use the ColorRamp factor rather than its Color
            # socket so Blender does not perform an implicit RGB->scalar cast.
            alpha_mult = nodes.new("ShaderNodeMath")
            alpha_mult.operation = "MULTIPLY"
            alpha_mult.location = (0, 40)
            links.new(density_value.outputs["Val"], alpha_mult.inputs[0])
            links.new(opacity_node.outputs[0], alpha_mult.inputs[1])
            # Boost mid-density values so Opacity=1.0 produces a clearly
            # visible cloud while preserving soft, porous edges.
            alpha_curve = nodes.new("ShaderNodeMath")
            alpha_curve.operation = "POWER"
            alpha_curve.inputs[1].default_value = 0.58
            alpha_curve.location = (200, 40)
            links.new(alpha_mult.outputs[0], alpha_curve.inputs[0])

            alpha_gain = nodes.new("ShaderNodeMath")
            alpha_gain.operation = "MULTIPLY"
            alpha_gain.inputs[1].default_value = 1.15
            alpha_gain.location = (360, 40)
            links.new(alpha_curve.outputs[0], alpha_gain.inputs[0])

            alpha_clamp = nodes.new("ShaderNodeClamp")
            alpha_clamp.location = (500, 40)
            links.new(alpha_gain.outputs[0], alpha_clamp.inputs[0])
            alpha_clamp.inputs[1].default_value = 0.0
            alpha_clamp.inputs[2].default_value = 1.0

            if "Alpha" in principled.inputs:
                links.new(alpha_clamp.outputs[0], principled.inputs["Alpha"])

            # Correct blend order: factor 0 = fully transparent, factor 1 =
            # fully opaque Principled smoke. The previous implementation was
            # inverted, which made the transparency response counter-intuitive.
            transparent = nodes.new("ShaderNodeBsdfTransparent")
            transparent.location = (230, -40)
            mix = nodes.new("ShaderNodeMixShader")
            mix.location = (540, 80)
            links.new(alpha_clamp.outputs[0], mix.inputs[0])
            links.new(transparent.outputs[0], mix.inputs[1])
            links.new(principled.outputs[0], mix.inputs[2])
            links.new(mix.outputs[0], output.inputs["Surface"])
            # Blender 4.1 uses Material.blend_method for Eevee alpha blending.
            # Configure it explicitly so the Transparent BSDF is actually honored.
            try:
                mat.blend_method = "BLEND"
            except Exception:
                pass
            try:
                mat.surface_render_method = "DITHERED"
            except Exception:
                pass
            try:
                mat.show_transparent_back = False
            except Exception:
                pass

        mat.diffuse_color = (*cfg.color[:3], max(0.05, opacity))
        mat["sparkshow_pyro_material_role"] = role
        mat["sparkshow_pyro_material_kind"] = kind
        if kind == "SMOKE":
            mat["sparkshow_smoke_alpha_enabled"] = (role == "VIEWPORT")
            mat["sparkshow_smoke_alpha_driver"] = "Clamp(Pow(RGBToBW(ColorRamp) * smoke_opacity, 0.58) * 1.15)"
        return mat

    emission = nodes.new("ShaderNodeEmission")
    emission.location = (160, 0)
    emission.inputs["Color"].default_value = (*cfg.color[:3], 1.0)
    emission.inputs["Strength"].default_value = max(1.5, cfg.intensity * 4.0)
    links.new(emission.outputs["Emission"], output.inputs["Surface"])
    mat.diffuse_color = (*cfg.color[:3], 1.0)
    mat["sparkshow_pyro_material_role"] = role
    mat["sparkshow_pyro_material_kind"] = kind
    return mat

def _ensure_render_gn(kind: str, material: bpy.types.Material) -> bpy.types.GeometryNodeTree:
    """Return a render GN tree dedicated to this material.

    Never share one GN Set Material node between different Pyro colours:
    reassigning the material on a shared node group makes every baked event
    render with the last profile/material that was created.
    """
    # Material names are already unique for Pyro smoke colours. Using the name
    # in the GN datablock key keeps each baked colour isolated.
    name = f"Sparkshow Pyro Bake GN {kind} :: {material.name}"
    ng = bpy.data.node_groups.get(name)
    if ng is not None:
        return ng

    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    ng.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nodes = ng.nodes
    links = ng.links

    group_in = nodes.new("NodeGroupInput")
    group_in.location = (-1100, 0)
    group_out = nodes.new("NodeGroupOutput")
    group_out.location = (940, 0)

    scene_time = nodes.new("GeometryNodeInputSceneTime")
    scene_time.location = (-1100, 260)

    start = nodes.new("GeometryNodeInputNamedAttribute")
    start.data_type = 'FLOAT'
    start.inputs["Name"].default_value = "ss_start"
    start.location = (-900, 180)

    life = nodes.new("GeometryNodeInputNamedAttribute")
    life.data_type = 'FLOAT'
    life.inputs["Name"].default_value = "ss_life"
    life.location = (-900, 60)

    age_raw = nodes.new("ShaderNodeMath")
    age_raw.operation = 'SUBTRACT'
    age_raw.location = (-700, 220)
    links.new(scene_time.outputs["Seconds"], age_raw.inputs[0])
    links.new(start.outputs["Attribute"], age_raw.inputs[1])

    active_start = nodes.new("FunctionNodeCompare")
    active_start.data_type = 'FLOAT'
    active_start.operation = 'GREATER_EQUAL'
    active_start.location = (-500, 140)
    links.new(age_raw.outputs[0], active_start.inputs[0])
    active_start.inputs[1].default_value = 0.0

    active_life = nodes.new("FunctionNodeCompare")
    active_life.data_type = 'FLOAT'
    active_life.operation = 'LESS_EQUAL'
    active_life.location = (-500, 20)
    links.new(age_raw.outputs[0], active_life.inputs[0])
    links.new(life.outputs["Attribute"], active_life.inputs[1])

    active_and = nodes.new("FunctionNodeBooleanMath")
    active_and.operation = 'AND'
    active_and.location = (-300, 80)
    links.new(active_start.outputs[0], active_and.inputs[0])
    links.new(active_life.outputs[0], active_and.inputs[1])

    age = nodes.new("ShaderNodeMath")
    age.operation = 'MAXIMUM'
    age.location = (-300, 230)
    age.inputs[1].default_value = 0.0
    links.new(age_raw.outputs[0], age.inputs[0])

    if kind == "SPARKS":
        base = nodes.new("GeometryNodeInputNamedAttribute")
        base.data_type = 'FLOAT_VECTOR'
        base.inputs["Name"].default_value = "ss_base"
        base.location = (-100, 360)

        velocity = nodes.new("GeometryNodeInputNamedAttribute")
        velocity.data_type = 'FLOAT_VECTOR'
        velocity.inputs["Name"].default_value = "ss_velocity"
        velocity.location = (-100, 220)

        acceleration = nodes.new("GeometryNodeInputNamedAttribute")
        acceleration.data_type = 'FLOAT_VECTOR'
        acceleration.inputs["Name"].default_value = "ss_accel"
        acceleration.location = (-100, 80)

        vel_age = nodes.new("ShaderNodeVectorMath")
        vel_age.operation = 'SCALE'
        vel_age.location = (120, 220)
        links.new(velocity.outputs["Attribute"], vel_age.inputs[0])
        links.new(age.outputs[0], vel_age.inputs[3])

        acc_age_sq = nodes.new("ShaderNodeMath")
        acc_age_sq.operation = 'MULTIPLY'
        acc_age_sq.location = (0, -80)
        links.new(age.outputs[0], acc_age_sq.inputs[0])
        links.new(age.outputs[0], acc_age_sq.inputs[1])

        acc_half = nodes.new("ShaderNodeVectorMath")
        acc_half.operation = 'SCALE'
        acc_half.location = (120, 20)
        links.new(acceleration.outputs["Attribute"], acc_half.inputs[0])
        acc_half.inputs[3].default_value = 0.5

        acc_term = nodes.new("ShaderNodeVectorMath")
        acc_term.operation = 'SCALE'
        acc_term.location = (300, 20)
        links.new(acc_half.outputs["Vector"], acc_term.inputs[0])
        links.new(acc_age_sq.outputs[0], acc_term.inputs[3])

        sum_vel = nodes.new("ShaderNodeVectorMath")
        sum_vel.operation = 'ADD'
        sum_vel.location = (320, 230)
        links.new(vel_age.outputs["Vector"], sum_vel.inputs[0])
        links.new(acc_term.outputs["Vector"], sum_vel.inputs[1])

        sum_base = nodes.new("ShaderNodeVectorMath")
        sum_base.operation = 'ADD'
        sum_base.location = (500, 260)
        links.new(base.outputs["Attribute"], sum_base.inputs[0])
        links.new(sum_vel.outputs["Vector"], sum_base.inputs[1])

        set_pos = nodes.new("GeometryNodeSetPosition")
        set_pos.location = (520, 0)
        links.new(group_in.outputs["Geometry"], set_pos.inputs["Geometry"])
        links.new(sum_base.outputs["Vector"], set_pos.inputs["Position"])

        radius = nodes.new("GeometryNodeInputNamedAttribute")
        radius.data_type = 'FLOAT'
        radius.inputs["Name"].default_value = "ss_radius"
        radius.location = (320, -160)

        scale = nodes.new("ShaderNodeCombineXYZ")
        scale.location = (500, -150)
        for socket in ("X", "Y", "Z"):
            links.new(radius.outputs["Attribute"], scale.inputs[socket])

        ico = nodes.new("GeometryNodeMeshIcoSphere")
        ico.inputs["Subdivisions"].default_value = 0
        ico.inputs["Radius"].default_value = 1.0
        ico.location = (520, 420)

        inst = nodes.new("GeometryNodeInstanceOnPoints")
        inst.location = (700, 120)
        links.new(set_pos.outputs["Geometry"], inst.inputs["Points"])
        links.new(active_and.outputs[0], inst.inputs["Selection"])
        links.new(ico.outputs["Mesh"], inst.inputs["Instance"])
        links.new(scale.outputs["Vector"], inst.inputs["Scale"])

        set_mat = nodes.new("GeometryNodeSetMaterial")
        set_mat.location = (900, 120)
        set_mat.inputs["Material"].default_value = material
        links.new(inst.outputs["Instances"], set_mat.inputs["Geometry"])
        links.new(set_mat.outputs["Geometry"], group_out.inputs["Geometry"])
    else:
        base = nodes.new("GeometryNodeInputNamedAttribute")
        base.data_type = 'FLOAT_VECTOR'
        base.inputs["Name"].default_value = "ss_base"
        base.location = (-100, 360)

        velocity = nodes.new("GeometryNodeInputNamedAttribute")
        velocity.data_type = 'FLOAT_VECTOR'
        velocity.inputs["Name"].default_value = "ss_velocity"
        velocity.location = (-100, 220)

        scale_attr = nodes.new("GeometryNodeInputNamedAttribute")
        scale_attr.data_type = 'FLOAT_VECTOR'
        scale_attr.inputs["Name"].default_value = "ss_scale"
        scale_attr.location = (-100, 80)

        vel_age = nodes.new("ShaderNodeVectorMath")
        vel_age.operation = 'SCALE'
        vel_age.location = (120, 220)
        links.new(velocity.outputs["Attribute"], vel_age.inputs[0])
        links.new(age.outputs[0], vel_age.inputs[3])

        sum_pos = nodes.new("ShaderNodeVectorMath")
        sum_pos.operation = 'ADD'
        sum_pos.location = (300, 260)
        links.new(base.outputs["Attribute"], sum_pos.inputs[0])
        links.new(vel_age.outputs["Vector"], sum_pos.inputs[1])

        set_pos = nodes.new("GeometryNodeSetPosition")
        set_pos.location = (500, 0)
        links.new(group_in.outputs["Geometry"], set_pos.inputs["Geometry"])
        links.new(sum_pos.outputs["Vector"], set_pos.inputs["Position"])

        progress = nodes.new("ShaderNodeMath")
        progress.operation = 'DIVIDE'
        progress.location = (80, -80)
        links.new(age.outputs[0], progress.inputs[0])
        life_safe = nodes.new("ShaderNodeMath")
        life_safe.operation = 'MAXIMUM'
        life_safe.location = (-100, -20)
        life_safe.inputs[1].default_value = 0.001
        links.new(life.outputs["Attribute"], life_safe.inputs[0])
        links.new(life_safe.outputs[0], progress.inputs[1])

        progress_clamped = nodes.new("ShaderNodeClamp")
        progress_clamped.location = (250, -80)
        links.new(progress.outputs[0], progress_clamped.inputs[0])
        progress_clamped.inputs[1].default_value = 0.0
        progress_clamped.inputs[2].default_value = 1.0

        # Grow quickly, then gently contract before disappearing.
        growth_pow = nodes.new("ShaderNodeMath")
        growth_pow.operation = 'POWER'
        growth_pow.location = (420, -80)
        growth_pow.inputs[1].default_value = 0.58
        links.new(progress_clamped.outputs[0], growth_pow.inputs[0])

        growth = nodes.new("ShaderNodeMath")
        growth.operation = 'MULTIPLY_ADD'
        growth.location = (590, -80)
        growth.inputs[1].default_value = 1.10
        growth.inputs[2].default_value = 0.12
        links.new(growth_pow.outputs[0], growth.inputs[0])

        inv_progress = nodes.new("ShaderNodeMath")
        inv_progress.operation = 'SUBTRACT'
        inv_progress.location = (420, -300)
        inv_progress.inputs[0].default_value = 1.0
        links.new(progress_clamped.outputs[0], inv_progress.inputs[1])

        fade = nodes.new("ShaderNodeMath")
        fade.operation = 'POWER'
        fade.location = (590, -300)
        fade.inputs[1].default_value = 0.95
        links.new(inv_progress.outputs[0], fade.inputs[0])

        growth_fade = nodes.new("ShaderNodeMath")
        growth_fade.operation = 'MULTIPLY'
        growth_fade.location = (760, -140)
        links.new(growth.outputs[0], growth_fade.inputs[0])
        links.new(fade.outputs[0], growth_fade.inputs[1])

        scale_vec = nodes.new("ShaderNodeCombineXYZ")
        scale_vec.location = (760, -260)
        links.new(growth_fade.outputs[0], scale_vec.inputs["X"])
        links.new(growth_fade.outputs[0], scale_vec.inputs["Y"])
        links.new(growth_fade.outputs[0], scale_vec.inputs["Z"])

        ico = nodes.new("GeometryNodeMeshIcoSphere")
        ico.inputs["Subdivisions"].default_value = 2
        ico.inputs["Radius"].default_value = 1.0
        ico.location = (520, 420)

        inst = nodes.new("GeometryNodeInstanceOnPoints")
        inst.location = (700, 120)
        links.new(set_pos.outputs["Geometry"], inst.inputs["Points"])
        links.new(active_and.outputs[0], inst.inputs["Selection"])
        links.new(ico.outputs["Mesh"], inst.inputs["Instance"])
        links.new(scale_attr.outputs["Attribute"], inst.inputs["Scale"])

        growth_scale = nodes.new("GeometryNodeScaleInstances")
        growth_scale.location = (860, 80)
        links.new(inst.outputs["Instances"], growth_scale.inputs["Instances"])
        links.new(scale_vec.outputs["Vector"], growth_scale.inputs["Scale"])

        set_smooth = nodes.new("GeometryNodeSetShadeSmooth")
        set_smooth.location = (1030, 80)
        links.new(growth_scale.outputs["Instances"], set_smooth.inputs["Geometry"])

        set_mat = nodes.new("GeometryNodeSetMaterial")
        set_mat.location = (1210, 120)
        set_mat.inputs["Material"].default_value = material
        links.new(set_smooth.outputs["Geometry"], set_mat.inputs["Geometry"])
        links.new(set_mat.outputs["Geometry"], group_out.inputs["Geometry"])

    return ng


def _add_drone_follow(obj: bpy.types.Object, scene: bpy.types.Scene, drone_name: str) -> None:
    drone = bpy.data.objects.get(drone_name)
    if drone is None:
        obj["sparkshow_pyro_missing_drone"] = drone_name
        return
    constraint = obj.constraints.new("COPY_TRANSFORMS")
    constraint.name = "Sparkshow Pyro Follow Drone"
    constraint.target = drone


def _build_bake_mesh(entries, kind: str, event: core.FirePreviewEvent) -> tuple[bpy.types.Mesh, list[Vector], list[Vector], list[float], list[float], list[Vector] | None, list[Vector] | None]:
    mesh_name = f"Sparkshow_PyroBake_{kind}_{event.drone_name}_F{event.channel + 1}_{event.frame}_Mesh"
    mesh = bpy.data.meshes.new(mesh_name)
    mesh.from_pydata([(0.0, 0.0, 0.0)] * len(entries), [], [])
    mesh.update()
    base_values: list[Vector] = []
    velocity_values: list[Vector] = []
    start_values: list[float] = []
    life_values: list[float] = []
    accel_values: list[Vector] | None = None
    radius_values: list[Vector] | None = None
    scale_values: list[Vector] | None = None

    if kind == "SPARKS":
        accel_list: list[Vector] = []
        radius_list: list[float] = []
        for particle in entries:
            base_values.append(Vector(particle.base))
            velocity_values.append(Vector(particle.velocity))
            accel_list.append(Vector(particle.acceleration))
            start_values.append(event.frame / FPS + particle.birth)
            life_values.append(max(0.02, particle.life))
            radius_list.append(max(0.005, particle.radius * 1.8))
        accel_values = accel_list
        for name, vals, kind_name in (
            ("ss_base", base_values, "VECTOR"),
            ("ss_velocity", velocity_values, "VECTOR"),
            ("ss_accel", accel_list, "VECTOR"),
        ):
            _set_vector_attr(_attribute(mesh, name, 'FLOAT_VECTOR'), vals)
        _set_float_attr(_attribute(mesh, "ss_start", 'FLOAT'), start_values)
        _set_float_attr(_attribute(mesh, "ss_life", 'FLOAT'), life_values)
        _set_float_attr(_attribute(mesh, "ss_radius", 'FLOAT'), radius_list)
    else:
        scales: list[Vector] = []
        for puff in entries:
            base_values.append(Vector(puff.base))
            velocity_values.append(Vector(puff.velocity))
            scales.append(Vector(puff.scale))
            start_values.append(event.frame / FPS + puff.birth)
            life_values.append(max(0.05, puff.life))
        scale_values = scales
        _set_vector_attr(_attribute(mesh, "ss_base", 'FLOAT_VECTOR'), base_values)
        _set_vector_attr(_attribute(mesh, "ss_velocity", 'FLOAT_VECTOR'), velocity_values)
        _set_vector_attr(_attribute(mesh, "ss_scale", 'FLOAT_VECTOR'), scales)
        _set_float_attr(_attribute(mesh, "ss_start", 'FLOAT'), start_values)
        _set_float_attr(_attribute(mesh, "ss_life", 'FLOAT'), life_values)
    return mesh, base_values, velocity_values, start_values, life_values, accel_values, scale_values


def _annotate_bake_object(obj: bpy.types.Object, event, pyro, cfg, *, role: str) -> None:
    obj["sparkshow_synoptic"] = True
    obj["sparkshow_synoptic_type"] = "pyrotechnic_bake"
    obj["sparkshow_pyro_collection"] = BAKE_COLLECTION
    obj["sparkshow_pyro_renderer"] = f"GN_RENDER_BAKE_{role}_SMOKE" if cfg.effect == "DAY_SMOKE" else "GN_RENDER_BAKE_SPARKS"
    obj["sparkshow_pyro_profile"] = pyro + 1
    obj["sparkshow_pyro_effect"] = cfg.effect
    obj["sparkshow_fire_channel"] = event.channel + 1
    obj["sparkshow_fire_frame"] = event.frame
    obj["sparkshow_drone"] = event.drone_name
    obj["sparkshow_pyro_duration"] = cfg.duration
    obj["sparkshow_pyro_lifetime"] = cfg.lifetime
    obj["sparkshow_pyro_size"] = cfg.size
    obj["sparkshow_pyro_gravity"] = cfg.gravity
    obj["sparkshow_pyro_profile_rgbw"] = tuple(float(v) for v in cfg.color[:4])
    obj["sparkshow_pyro_smoke_color_source"] = "pyro_profile"
    obj["sparkshow_pyro_bake_role"] = role


def _create_bake_sparks(scene, name, event, pyro, cfg, runtime):
    entries = runtime.particles
    if not entries:
        return None
    collection = _ensure_bake_collection(scene)
    mesh, *_ = _build_bake_mesh(entries, "SPARKS", event)
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.location = (0,0,0)
    obj.hide_viewport = False
    obj.hide_render = False
    obj.display_type = 'TEXTURED'
    obj.color = cfg.color
    _add_drone_follow(obj, scene, event.drone_name)
    material = _ensure_render_material("SPARKS", pyro, cfg)
    if material.name not in obj.data.materials:
        obj.data.materials.append(material)
    mod = obj.modifiers.new("Sparkshow Pyro Bake", 'NODES')
    mod.node_group = _ensure_render_gn("SPARKS", material)
    _annotate_bake_object(obj, event, pyro, cfg, role="SPARKS")
    return obj


def _create_bake_smoke(scene, name, event, pyro, cfg, runtime):
    entries = runtime.smoke_puffs
    if not entries:
        return None
    collection = _ensure_bake_collection(scene)
    mesh, *_ = _build_bake_mesh(entries, "SMOKE", event)

    # One shared mesh, two render layers: a light viewport surface and a
    # render-only procedural volume. They never enter drone Family collections.
    viewport_obj = bpy.data.objects.new(name + "_VIEWPORT", mesh)
    render_obj = bpy.data.objects.new(name + "_RENDER", mesh.copy())
    collection.objects.link(viewport_obj)
    collection.objects.link(render_obj)
    for obj in (viewport_obj, render_obj):
        obj.location = (0, 0, 0)
        obj.hide_viewport = False
        obj.hide_render = False
        obj.display_type = 'TEXTURED'
        obj.color = cfg.color
        _add_drone_follow(obj, scene, event.drone_name)
        _annotate_bake_object(obj, event, pyro, cfg, role="SMOKE_VIEWPORT" if obj is viewport_obj else "SMOKE_RENDER")

    # Viewport layer: light surface cloud, never rendered.
    viewport_obj.hide_render = True
    viewport_obj["sparkshow_pyro_bake_viewport_only"] = True
    vp_mat = _ensure_render_material("SMOKE", pyro, cfg, role="VIEWPORT")
    viewport_obj.data.materials.append(vp_mat)
    vp_mod = viewport_obj.modifiers.new("Sparkshow Smoke Viewport", 'NODES')
    vp_mod.node_group = _ensure_render_gn("SMOKE", vp_mat)

    # Render layer: true volume, never evaluated in the viewport.
    render_obj.hide_viewport = True
    render_obj["sparkshow_pyro_bake_render_only"] = True
    render_mat = _ensure_render_material("SMOKE", pyro, cfg, role="RENDER")
    render_obj.data.materials.append(render_mat)
    render_mod = render_obj.modifiers.new("Sparkshow Smoke Render", 'NODES')
    render_mod.node_group = _ensure_render_gn("SMOKE", render_mat)

    return viewport_obj, render_obj


def _create_bake_object(scene, name, event, pyro, cfg, runtime, kind):
    if kind == "SMOKE":
        return _create_bake_smoke(scene, name, event, pyro, cfg, runtime)
    return _create_bake_sparks(scene, name, event, pyro, cfg, runtime)

def bake(scene: bpy.types.Scene | None = None, start: int | None = None, end: int | None = None, step: int | None = None) -> dict[str, int]:
    scene = scene or bpy.context.scene
    lightshow = get_lightshow(scene)
    start = scene.frame_start if start is None else int(start)
    end = scene.frame_end if end is None else int(end)
    step = int(step or getattr(lightshow, "fire_pyro_bake_step", BAKE_STEP_DEFAULT))
    start = max(1, start)
    end = max(start, end)
    step = max(1, min(8, step))

    clear_bake(scene)
    events = _events_for_range(scene, start, end)
    if not events:
        return {}

    created = {"events": 0, "sparks": 0, "smoke": 0}
    for event in events:
        pyro = core._assigned_pyro(lightshow, event.channel)
        cfg = core._pyro_settings(lightshow, pyro)
        if cfg.effect == "DAY_SMOKE":
            # Pyro smoke remains fully independent from drone Lighting.
            cfg = _pyro_cfg_for_event(cfg)
        seed = core._stable_seed(event.drone_name, event.channel, event.frame, pyro)
        particles = core._build_particles(cfg, seed)
        puffs: list[core.SmokePuff] = []
        groups = []
        if cfg.effect == "DAY_SMOKE":
            puffs, _, _, groups = core._build_smoke_puffs(cfg, seed)

        runtime = core.EventRuntime(event, pyro, core._config_hash(pyro, cfg), particles, puffs, 0, groups)
        if cfg.effect == "DAY_SMOKE":
            obj = _create_bake_object(
                scene,
                f"{BAKE_SMOKE_PREFIX}{event.drone_name}_F{event.channel + 1}_{event.frame}",
                event,
                pyro,
                cfg,
                runtime,
                "SMOKE",
            )
            if obj:
                created["smoke"] += 1
        else:
            obj = _create_bake_object(
                scene,
                f"{BAKE_SPARK_PREFIX}{event.drone_name}_F{event.channel + 1}_{event.frame}",
                event,
                pyro,
                cfg,
                runtime,
                "SPARKS",
            )
            if obj:
                created["sparks"] += 1
        if obj:
            created["events"] += 1

    if not created["events"]:
        clear_bake(scene)
        return {}

    scene["sparkshow_pyro_bake_active"] = True
    scene["sparkshow_pyro_bake_frame_start"] = start
    scene["sparkshow_pyro_bake_frame_end"] = end
    scene["sparkshow_pyro_bake_step"] = step
    scene["sparkshow_pyro_bake_event_count"] = len(events)
    return created


class LIGHTSHOW_OT_bake_pyro(bpy.types.Operator):
    bl_idname = "sparkshow_studio.bake_pyro"
    bl_label = "Bake Pyro"
    bl_description = "Create renderable Pyro bake objects in the dedicated Sparkshow Pyro Bake collection"

    def execute(self, context: bpy.types.Context) -> set[str]:
        try:
            result = bake(context.scene)
        except Exception as exc:
            self.report({"ERROR"}, f"Pyro bake: {exc}")
            return {"CANCELLED"}
        if not result:
            self.report({"WARNING"}, "No Fire events found in the scene range")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Pyro bake ready: {result['events']} event(s) in '{BAKE_COLLECTION}'")
        return {"FINISHED"}


class LIGHTSHOW_OT_clear_pyro_bake(bpy.types.Operator):
    bl_idname = "sparkshow_studio.clear_pyro_bake"
    bl_label = "Clear Pyro Bake"
    bl_description = "Remove the baked Pyro render objects and restore the viewport preview"

    def execute(self, context: bpy.types.Context) -> set[str]:
        clear_bake(context.scene)
        try:
            from .preview import refresh_preview
            refresh_preview(context.scene)
        except Exception:
            pass
        self.report({"INFO"}, "Pyro bake cleared")
        return {"FINISHED"}


classes = [LIGHTSHOW_OT_bake_pyro, LIGHTSHOW_OT_clear_pyro_bake]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
