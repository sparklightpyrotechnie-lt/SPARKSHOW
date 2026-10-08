bl_info = {
    "name": "Sparkshow Studio Lighting",
    "author": "OpenAI / évolution du code utilisateur",
    "version": (5, 2, 76),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > Lighting",
    "description": "Gestion avancée des couleurs, gradients et animations pour drones lumineux",
    "category": "Animation",
}

import bpy
import os
import math
import random
import hashlib
from pathlib import Path

from mathutils import Vector
from bpy.app.handlers import persistent

from ..tools.collection_tools import get_drones, get_import_drones, get_selected_drones, is_drone, is_import_drone
from ..tools.fcurve_tools import change_interpolation
from ..setup import get_lightshow


# ============================================================
# GLOBALS / CACHE
# ============================================================

preview_collections = {}

GRADIENT_PREVIEW_REBUILD_TIMER = False

LIVE_PREVIEW_UPDATING = False
LIVE_PREVIEW_HANDLER_REGISTERED = False
LIVE_PREVIEW_LAST_FRAME = None
LIVE_PREVIEW_BAKING = False

# Viewport shading states temporarily changed for Object.color preview.
_PREVIEW_SAVED_SHADING = {}

# Temporary values used while the single Lighting preview switch overrides
# Object.color. We restore the actual animated value when preview is disabled.
_PREVIEW_SAVED_COLORS = {}

DRONE_CACHE = {
    "scene_ptr": None,

    # Objets racines représentant les drones
    "objects": [],

    # Position spatiale
    "positions": {},

    # Socket principal
    "sockets": {},

    # Tous les sockets d'émission
    "all_sockets": {},

    # Nombre de sockets / LEDs
    "led_counts": {},

    # Racines
    "roots": {},

    # Objets qui portent réellement les émissions
    "emission_objects": {},

    # Facteurs spatiaux
    "spatial": {},

    # Courbes
    "curve": {},

    # Seeds
    "seed": {},

    # Cache
    "dirty": True,

    # Diagnostics
    "detected_emission_objects": 0,
    "detected_mesh_objects": 0,

    # Diagnostic détaillé
    "diagnostics": [],

    # Signature de sélection
    "selection_signature": None,
}

EPSILON = 0.000001


# ============================================================
# UTILITAIRES
# ============================================================

def clamp(value, minimum=0.0, maximum=1.0):
    return max(minimum, min(maximum, value))


def smoothstep(t):
    t = clamp(t)
    return t * t * (3.0 - 2.0 * t)


def smootherstep(t):
    t = clamp(t)
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def lerp(a, b, t):
    return a + (b - a) * t


def color_distance(a, b):
    return math.sqrt(
        (a[0] - b[0]) ** 2 +
        (a[1] - b[1]) ** 2 +
        (a[2] - b[2]) ** 2 +
        (a[3] - b[3]) ** 2
    )


def stable_seed(text):
    digest = hashlib.md5(
        text.encode("utf-8")
    ).hexdigest()

    return int(digest[:8], 16)


def get_scene_fps(scene):
    if scene.render.fps_base == 0:
        return float(scene.render.fps)

    return float(scene.render.fps) / float(
        scene.render.fps_base
    )


def safe_name(name):
    return (
        str(name)
        .lower()
        .replace("_", " ")
        .replace("-", " ")
        .replace(".", " ")
    )


# ============================================================
# DRONE NAME DETECTION
# ============================================================

DRONE_KEYWORDS = (
    "drone",
    "uav",
    "leddrone",
    "lightdrone",
    "quad",
    "quadcopter",
    "coptere",
    "copter",
)

CONTAINER_KEYWORDS = (
    "drones",
    "drone fleet",
    "fleet",
    "formation",
    "formations",
    "show",
    "swarm",
    "essaim",
    "families",
    "family",
)


def name_looks_like_drone(name):

    name = safe_name(name)

    for keyword in DRONE_KEYWORDS:

        if keyword in name:
            return True

    return False


def name_looks_like_container(name):

    name = safe_name(name)

    for keyword in CONTAINER_KEYWORDS:

        if keyword in name:
            return True

    return False


# ============================================================
# MATERIAL / EMISSION
# ============================================================

def get_materials_from_object(obj):

    materials = []

    if not obj:
        return materials

    try:

        if hasattr(obj, "active_material"):

            material = obj.active_material

            if material:
                materials.append(material)

    except Exception:
        pass

    try:

        if hasattr(obj, "material_slots"):

            for slot in obj.material_slots:

                material = slot.material

                if (
                    material
                    and
                    material not in materials
                ):

                    materials.append(material)

    except Exception:
        pass

    return materials


def socket_is_color(socket):

    if not socket:
        return False

    try:

        if socket.type in {
            'RGBA',
            'VECTOR'
        }:

            return True

    except Exception:
        pass

    return False


def socket_name_looks_like_color(socket):

    if not socket:
        return False

    name = safe_name(
        socket.name
    )

    keywords = (
        "color",
        "couleur",
        "rgb",
        "rgba",
        "emission color",
        "emission couleur",
    )

    return any(
        keyword in name
        for keyword in keywords
    )


def get_material_emission_sockets(obj):

    sockets = []

    if not obj:
        return sockets

    materials = get_materials_from_object(
        obj
    )

    for material in materials:

        try:

            if not material.use_nodes:
                continue

            if not material.node_tree:
                continue

        except Exception:
            continue

        nodes = material.node_tree.nodes

        # ====================================================
        # 1. NODES RGBW / EMISSION
        # ====================================================

        for node in nodes:

            node_text = (
                f"{node.name} "
                f"{getattr(node, 'label', '')}"
            )

            node_text = safe_name(
                node_text
            )

            is_rgbw = (
                "rgbw" in node_text
            )

            is_emission = (
                "emission" in node_text
            )

            is_led = (
                "led" in node_text
            )

            is_emission_node = (
                node.type == 'EMISSION'
            )

            if not (
                is_rgbw
                or
                is_emission
                or
                is_led
                or
                is_emission_node
            ):
                continue

            # ------------------------------------------------
            # Recherche préférentielle du socket couleur
            # ------------------------------------------------

            preferred = []

            for socket in node.inputs:

                if not socket_is_color(
                    socket
                ):
                    continue

                if socket_name_looks_like_color(
                    socket
                ):

                    preferred.append(
                        socket
                    )

            if preferred:

                sockets.extend(
                    preferred
                )

            else:

                # Pour un node Emission standard,
                # le premier RGBA est normalement Color.
                for socket in node.inputs:

                    if socket.type == 'RGBA':

                        sockets.append(
                            socket
                        )

                        break

        # ====================================================
        # 2. PRINCIPLED BLENDER 4.x
        # ====================================================

        for node in nodes:

            if node.type != 'BSDF_PRINCIPLED':
                continue

            # Blender 4.x :
            # Emission Color

            socket = node.inputs.get(
                "Emission Color"
            )

            if socket:

                sockets.append(
                    socket
                )

                continue

            # Compatibilité
            socket = node.inputs.get(
                "Emission"
            )

            if socket:

                sockets.append(
                    socket
                )

    # ========================================================
    # SUPPRESSION DES DOUBLONS
    # ========================================================

    unique = []

    seen = set()

    for socket in sockets:

        try:

            pointer = socket.as_pointer()

        except Exception:

            pointer = id(socket)

        if pointer in seen:
            continue

        seen.add(pointer)
        unique.append(socket)

    return unique


def get_emission_socket(obj):

    sockets = get_material_emission_sockets(
        obj
    )

    if sockets:
        return sockets[0]

    return None


# ============================================================
# SOCKET COLOR
# ============================================================

def set_socket_color(
    socket,
    color
):

    if not socket:
        return False

    try:
        value = socket.default_value

        if len(value) >= 4:
            new_value = (
                clamp(color[0]),
                clamp(color[1]),
                clamp(color[2]),
                clamp(color[3])
            )

            current = tuple(value[:4])
            if all(abs(current[i] - new_value[i]) < 1e-7 for i in range(4)):
                return False

            value = new_value

        elif len(value) >= 3:
            new_value = (
                clamp(color[0]),
                clamp(color[1]),
                clamp(color[2])
            )

            current = tuple(value[:3])
            if all(abs(current[i] - new_value[i]) < 1e-7 for i in range(3)):
                return False

            value = new_value
        else:
            return False

        socket.default_value = value

        # Force la mise à jour du node tree / matériau pour le viewport.
        try:
            node_tree = socket.id_data
            if node_tree and hasattr(node_tree, "update_tag"):
                node_tree.update_tag()
        except Exception:
            pass

        return True

    except Exception:
        return False


# ============================================================
# OBJECT TREE
# ============================================================

def iter_children_recursive(obj):

    if not obj:
        return

    for child in obj.children:

        yield child

        yield from iter_children_recursive(
            child
        )


def get_all_descendants(obj):

    return list(
        iter_children_recursive(
            obj
        )
    )


def get_top_parent(obj):

    current = obj

    visited = set()

    while current.parent:

        pointer = current.as_pointer()

        if pointer in visited:
            break

        visited.add(
            pointer
        )

        current = current.parent

    return current


# ============================================================
# ROOT DRONE
# ============================================================

def get_drone_root(obj):

    """
    Détermine le root logique du drone.

    Pour ton architecture :

        Families
        └── Family 000
            └── Drone 000.000
                └── Drone.001
                    └── RGBW Emission

    Le résultat recherché est :

        Drone.001
    """

    if not obj:
        return None

    current = obj

    visited = set()

    drone_candidate = None

    while current:

        pointer = current.as_pointer()

        if pointer in visited:
            break

        visited.add(
            pointer
        )

        # ----------------------------------------------------
        # Un objet explicitement nommé Drone est prioritaire
        # ----------------------------------------------------

        if name_looks_like_drone(
            current.name
        ):

            # Ne pas utiliser les conteneurs "Drones"
            if not name_looks_like_container(
                current.name
            ):

                drone_candidate = current

        parent = current.parent

        if not parent:
            break

        # ----------------------------------------------------
        # Si le parent est un conteneur global,
        # on s'arrête.
        # ----------------------------------------------------

        if name_looks_like_container(
            parent.name
        ):

            break

        current = parent

    if drone_candidate:

        return drone_candidate

    # --------------------------------------------------------
    # Sinon parent immédiat
    # --------------------------------------------------------

    if obj.parent:

        if not name_looks_like_container(
            obj.parent.name
        ):

            return obj.parent

    # --------------------------------------------------------
    # Sinon root global
    # --------------------------------------------------------

    root = get_top_parent(
        obj
    )

    if root:

        if name_looks_like_container(
            root.name
        ):

            if obj.parent:

                return obj.parent

            return obj

        return root

    return obj


# ============================================================
# SELECTED OBJECT DETECTION
# ============================================================

def get_selected_roots():

    selected = list(
        bpy.context.selected_objects
    )

    if not selected:
        return []

    roots = []

    selected_pointers = {
        obj.as_pointer()
        for obj in selected
    }

    for obj in selected:

        parent = obj.parent

        is_child_of_selected = False

        visited = set()

        while parent:

            pointer = parent.as_pointer()

            if pointer in visited:
                break

            visited.add(
                pointer
            )

            if pointer in selected_pointers:

                is_child_of_selected = True

                break

            parent = parent.parent

        if not is_child_of_selected:

            roots.append(
                obj
            )

    return roots


# ============================================================
# FIND EMISSION IN HIERARCHY
# ============================================================

def find_emissions_in_hierarchy(
    root
):

    """
    Recherche TOUTES les émissions dans :

        root
        └── enfants
            └── enfants
                └── ...

    Retourne :

        [
            (objet, socket),
            ...
        ]
    """

    results = []

    if not root:
        return results

    objects = [
        root
    ]

    objects.extend(
        get_all_descendants(
            root
        )
    )

    for obj in objects:

        sockets = get_material_emission_sockets(
            obj
        )

        for socket in sockets:

            results.append(
                (
                    obj,
                    socket
                )
            )

    return results


# ============================================================
# DETECT SELECTED DRONES
# ============================================================

def detect_selected_drones():

    """
    MODE SÉLECTION :

    L'utilisateur sélectionne :

        Drone.001

    L'addon inspecte toute la hiérarchie :

        Drone.001
        └── ...
            └── RGBW Emission

    Si une émission est trouvée :

        Drone.001 = drone détecté
    """

    drones = []

    roots = get_selected_roots()

    for root in roots:

        emissions = (
            find_emissions_in_hierarchy(
                root
            )
        )

        if not emissions:
            continue

        drones.append({
            "root": root,
            "emissions": emissions,
        })

    return drones


# ============================================================
# COLLECTION
# ============================================================

def get_collection_from_scene(scene):

    name = (
        scene.studio_palette_drone_collection_name
        .strip()
    )

    if not name:
        return None

    return bpy.data.collections.get(
        name
    )


def object_is_in_collection(
    obj,
    collection
):

    if not collection:
        return False

    try:

        for coll in obj.users_collection:

            current = coll

            while current:

                if current == collection:
                    return True

                current = current.parent

    except Exception:
        pass

    return False


# ============================================================
# AUTOMATIC DETECTION
# ============================================================

def find_emission_objects(
    objects
):

    result = []

    for obj in objects:

        sockets = (
            get_material_emission_sockets(
                obj
            )
        )

        if sockets:

            result.append(
                (
                    obj,
                    sockets
                )
            )

    return result


# ============================================================
# BUILD DRONE GROUPS
# ============================================================

def build_drone_groups(
    scene
):

    mode = (
        scene.studio_palette_drone_detection_mode
    )

    groups = {}

    # ========================================================
    # MODE SELECTED
    # ========================================================

    if mode == 'SELECTED':

        detected = (
            detect_selected_drones()
        )

        DRONE_CACHE[
            "detected_mesh_objects"
        ] = sum(
            1
            for obj in bpy.context.selected_objects
            if obj.type == 'MESH'
        )

        DRONE_CACHE[
            "detected_emission_objects"
        ] = sum(
            len(item["emissions"])
            for item in detected
        )

        for item in detected:

            root = item["root"]

            key = root.as_pointer()

            groups[key] = {
                "root": root,
                "emission_objects": [],
                "sockets": [],
            }

            for emission_obj, socket in (
                item["emissions"]
            ):

                groups[key][
                    "emission_objects"
                ].append(
                    emission_obj
                )

                groups[key][
                    "sockets"
                ].append(
                    socket
                )

        return groups

    # ========================================================
    # MODE COLLECTION
    # ========================================================

    if mode == 'COLLECTION':

        collection = (
            get_collection_from_scene(
                scene
            )
        )

        if not collection:

            return {}

        source_objects = [
            obj
            for obj in scene.objects
            if object_is_in_collection(
                obj,
                collection
            )
        ]

    # ========================================================
    # MODE AUTO
    # ========================================================

    else:

        source_objects = list(
            scene.objects
        )

    DRONE_CACHE[
        "detected_mesh_objects"
    ] = sum(
        1
        for obj in source_objects
        if obj.type == 'MESH'
    )

    emission_objects = (
        find_emission_objects(
            source_objects
        )
    )

    DRONE_CACHE[
        "detected_emission_objects"
    ] = len(
        emission_objects
    )

    # ========================================================
    # GROUPING
    # ========================================================

    for obj, sockets in emission_objects:

        root = get_drone_root(
            obj
        )

        if not root:

            root = obj

        key = root.as_pointer()

        if key not in groups:

            groups[key] = {
                "root": root,
                "emission_objects": [],
                "sockets": [],
            }

        groups[key][
            "emission_objects"
        ].append(
            obj
        )

        groups[key][
            "sockets"
        ].extend(
            sockets
        )

    return groups


# ============================================================
# CACHE
# ============================================================

def invalidate_cache():

    DRONE_CACHE[
        "dirty"
    ] = True


def clear_drone_cache():

    DRONE_CACHE[
        "objects"
    ] = []

    DRONE_CACHE[
        "positions"
    ].clear()

    DRONE_CACHE[
        "sockets"
    ].clear()

    DRONE_CACHE[
        "all_sockets"
    ].clear()

    DRONE_CACHE[
        "led_counts"
    ].clear()

    DRONE_CACHE[
        "roots"
    ].clear()

    DRONE_CACHE[
        "emission_objects"
    ].clear()

    DRONE_CACHE[
        "spatial"
    ].clear()

    DRONE_CACHE[
        "curve"
    ].clear()

    DRONE_CACHE[
        "seed"
    ].clear()

    DRONE_CACHE[
        "diagnostics"
    ] = []

    DRONE_CACHE[
        "detected_emission_objects"
    ] = 0

    DRONE_CACHE[
        "detected_mesh_objects"
    ] = 0


def get_selection_signature():

    try:

        return tuple(
            sorted(
                (
                    obj.name,
                    obj.as_pointer()
                )
                for obj in bpy.context.selected_objects
            )
        )

    except Exception:

        return ()



def _authoritative_show_drones(scene):
    """Return real Sparkshow show drones, not arbitrary marked meshes.

    Sparkshow's own collection helpers are authoritative for the show fleet:
    regular drones live under Families/Family xxx and are named ``Drone xxx.xxx``.
    Imported drones are used only as a fallback when no regular show drones are
    present. This prevents helper/template meshes carrying the color marker from
    inflating the count (for example 241 reported for a 240-drone show).
    """
    try:
        regular = [d for d in get_drones(scene.collection) if d and d.type == 'MESH']
    except Exception:
        regular = []

    if regular:
        return regular

    try:
        imported = [d for d in get_import_drones(scene.collection) if d and d.type == 'MESH']
    except Exception:
        imported = []

    return imported


def build_drone_cache(scene):
    """Build the cache from real Sparkshow drones and their visible emission hierarchy."""
    mode = getattr(scene, "studio_palette_drone_detection_mode", "SHOW")

    if mode == "SELECTED":
        drones = [
            obj for obj in bpy.context.selected_objects
            if obj and obj.type == 'MESH' and (is_drone(obj) or is_import_drone(obj))
        ]
    elif mode == "COLLECTION":
        name = getattr(scene, "studio_palette_drone_collection_name", "").strip()
        col = bpy.data.collections.get(name) if name else None
        drones = [
            obj for obj in col.all_objects
            if obj and obj.type == 'MESH' and (is_drone(obj) or is_import_drone(obj))
        ] if col else []
    else:
        drones = _authoritative_show_drones(scene)

    unique = []
    seen = set()
    for d in drones:
        try:
            ptr = d.as_pointer()
        except Exception:
            continue
        if ptr in seen:
            continue
        seen.add(ptr)
        unique.append(d)
    unique.sort(key=lambda obj: obj.name)

    all_sockets = {}
    emission_objects = {}
    led_counts = {}
    diagnostics = []
    detected_emission_ptrs = set()

    for d in unique:
        pairs = find_emissions_in_hierarchy(d)
        sockets = []
        objects = []
        for emission_obj, socket in pairs:
            try:
                sp = socket.as_pointer()
            except Exception:
                sp = id(socket)
            if sp not in {s.as_pointer() if hasattr(s, 'as_pointer') else id(s) for s in sockets}:
                sockets.append(socket)
            try:
                op = emission_obj.as_pointer()
            except Exception:
                op = id(emission_obj)
            if op not in {o.as_pointer() if hasattr(o, 'as_pointer') else id(o) for o in objects}:
                objects.append(emission_obj)
            detected_emission_ptrs.add(op)

        all_sockets[d.name] = sockets
        emission_objects[d.name] = objects if objects else [d]
        led_counts[d.name] = len(sockets) if sockets else 1
        diagnostics.append({
            "drone": d.name,
            "root": d.name,
            "led_count": led_counts[d.name],
            "emission_objects": [o.name for o in emission_objects[d.name]],
        })

    DRONE_CACHE.clear()
    DRONE_CACHE.update({
        "scene_ptr": scene.as_pointer(),
        "objects": unique,
        "positions": {d.name: d.matrix_world.translation.copy() for d in unique if d is not None},
        "sockets": {name: (sockets[0] if sockets else None) for name, sockets in all_sockets.items()},
        "all_sockets": all_sockets,
        "led_counts": led_counts,
        "roots": {d.name: d for d in unique},
        "emission_objects": emission_objects,
        "spatial": {},
        "curve": {},
        "seed": {d.name: stable_seed(d.name) for d in unique},
        "dirty": False,
        "detected_emission_objects": len(detected_emission_ptrs) if detected_emission_ptrs else len(unique),
        "detected_mesh_objects": len(unique),
        "diagnostics": diagnostics,
        "selection_signature": get_selection_signature(),
    })
    return unique



def get_drone_cache(scene):
    selection_changed = get_selection_signature() != DRONE_CACHE.get("selection_signature")
    if DRONE_CACHE.get("dirty") or DRONE_CACHE.get("scene_ptr") != scene.as_pointer() or (
        getattr(scene, "studio_palette_drone_detection_mode", "SHOW") == 'SELECTED' and selection_changed
    ):
        return build_drone_cache(scene)
    return DRONE_CACHE.get("objects", [])



# ============================================================
# DRONE NAME
# ============================================================

def get_drone_name(
    obj
):

    for name, root in (
        DRONE_CACHE[
            "roots"
        ].items()
    ):

        if root == obj:
            return name

    return obj.name


def get_sockets_for_drone(obj):
    """Return all real emission color sockets belonging to one Sparkshow drone."""
    name = get_drone_name(obj)
    return list(DRONE_CACHE.get("all_sockets", {}).get(name, []))


def _is_shared_object_color_backend(obj):
    """Return True only for the modern shared Sparkshow Object.color material."""
    if obj is None or getattr(obj, "type", None) != "MESH":
        return False
    try:
        for material in obj.data.materials:
            if material is None or material.name != "Sparkshow Drone RGBW (Shared)":
                continue
            nodes = material.node_tree.nodes
            links = material.node_tree.links
            object_info = nodes.get("Drone Object Color")
            emission = nodes.get("RGBW Emission")
            if object_info is None or emission is None:
                continue
            color_output = object_info.outputs.get("Color")
            color_input = emission.inputs.get("Color")
            if color_output is None or color_input is None:
                continue
            if any(
                link.from_node == object_info
                and link.from_socket == color_output
                and link.to_node == emission
                and link.to_socket == color_input
                for link in links
            ):
                return True
    except Exception:
        pass
    return False


def _ensure_object_color_material(obj):
    """Repair the modern shared material without changing legacy per-drone materials."""
    return _is_shared_object_color_backend(obj)


def _material_from_socket(socket):
    try:
        owner = socket.id_data
        if owner is not None and getattr(owner, "bl_rna", None) is not None:
            if getattr(owner.bl_rna, "identifier", "") == "ShaderNodeTree":
                return owner.id_data
    except Exception:
        pass
    try:
        return socket.id_data.id_data
    except Exception:
        return None


def _ensure_material_diffuse_driver(material):
    """Mirror V3: make Solid viewport material color follow RGBW emission color."""
    if material is None or not getattr(material, "use_nodes", False):
        return
    try:
        for index in range(3):
            data_path = "diffuse_color"
            existing = [
                d for d in (material.animation_data.drivers if material.animation_data else [])
                if d.data_path == data_path and d.array_index == index
            ]
            if existing:
                continue
            fcurve = material.driver_add(data_path, index)
            driver = fcurve.driver
            driver.type = "SUM"
            var = driver.variables.new()
            target = var.targets[0]
            target.id_type = "MATERIAL"
            target.id = material
            target.data_path = f'node_tree.nodes["RGBW Emission"].inputs["Color"].default_value[{index}]'
            var_w = driver.variables.new()
            target_w = var_w.targets[0]
            target_w.id_type = "MATERIAL"
            target_w.id = material
            target_w.data_path = 'node_tree.nodes["RGBW Emission"].inputs["Color"].default_value[3]'
    except Exception:
        pass


def _set_material_diffuse_preview(material, rgba):
    """Update material display color as a viewport fallback for legacy materials."""
    if material is None:
        return
    try:
        _ensure_material_diffuse_driver(material)
        material.diffuse_color = (
            clamp(rgba[0] + rgba[3]),
            clamp(rgba[1] + rgba[3]),
            clamp(rgba[2] + rgba[3]),
            1.0,
        )
    except Exception:
        pass


def set_drone_color(obj, color):
    """Apply RGBW to the actual visible backend used by this drone.

    - Modern shared Sparkshow material: Object.color.
    - Legacy/current per-drone emission hierarchy: actual emission node sockets,
      exactly like the working Palette V3 addon.
    """
    if obj is None or getattr(obj, "type", None) != 'MESH':
        return 0, 0, 0
    rgba = tuple(float(clamp(v)) for v in color[:4])

    # Modern shared material must stay per-object.
    if _is_shared_object_color_backend(obj):
        try:
            previous = tuple(float(v) for v in obj.color[:4])
            obj.color = rgba
            obj["sparkshow_object_color"] = True
            try:
                obj.update_tag(refresh={'OBJECT'})
            except Exception:
                obj.update_tag()
            changed = int(any(abs(previous[i] - rgba[i]) > 1e-7 for i in range(4)))
            return changed, 1, 1
        except Exception:
            return 0, 0, 0

    sockets = get_sockets_for_drone(obj)
    if not sockets:
        # Final fallback for a correctly marked object-color drone.
        try:
            if obj.get("sparkshow_object_color", False):
                previous = tuple(float(v) for v in obj.color[:4])
                obj.color = rgba
                return int(previous != rgba), 0, 1
        except Exception:
            pass
        return 0, 0, 0

    changed = 0
    linked = 0
    for socket in sockets:
        try:
            if getattr(socket, "is_linked", False):
                linked += 1
        except Exception:
            pass
        if set_socket_color(socket, rgba):
            changed += 1
        try:
            material = socket.id_data.id_data
            _set_material_diffuse_preview(material, rgba)
        except Exception:
            pass
    return changed, linked, len(sockets)


def _socket_fcurves(socket):
    """Return F-curves for one socket's default_value."""
    try:
        node_tree = socket.id_data
        action = node_tree.animation_data.action if node_tree.animation_data else None
        if action is None:
            return []
        path = socket.path_from_id("default_value")
        return [fc for fc in action.fcurves if fc.data_path == path]
    except Exception:
        return []


def _mark_color_keyframes_jitter(obj, frame):
    """Mark only the color keys created/updated by Lighting Bake as JITTER (green)."""
    if obj is None:
        return

    # Shared modern backend: Object.color action on the drone object.
    try:
        if _is_shared_object_color_backend(obj):
            action = obj.animation_data.action if obj.animation_data else None
            if action:
                for fc in action.fcurves:
                    if fc.data_path != "color":
                        continue
                    for key in fc.keyframe_points:
                        if abs(float(key.co.x) - float(frame)) < 0.01:
                            key.type = 'JITTER'
            return
    except Exception:
        pass

    # RGBW Emission backend: keyframes live on the node-tree sockets.
    for socket in get_sockets_for_drone(obj):
        try:
            action = socket.id_data.animation_data.action if socket.id_data.animation_data else None
            if not action:
                continue
            path = socket.path_from_id("default_value")
            for fc in action.fcurves:
                if fc.data_path != path:
                    continue
                for key in fc.keyframe_points:
                    if abs(float(key.co.x) - float(frame)) < 0.01:
                        key.type = 'JITTER'
        except Exception:
            pass


def keyframe_drone_color(obj, frame):
    """Keyframe actual emission sockets, or Object.color for shared modern drones."""
    if obj is None:
        return False
    keyed = False
    try:
        if _is_shared_object_color_backend(obj):
            obj.keyframe_insert(data_path="color", frame=frame)
            keyed = True
        else:
            sockets = get_sockets_for_drone(obj)
            for socket in sockets:
                try:
                    socket.keyframe_insert(data_path="default_value", frame=frame)
                    keyed = True
                except Exception:
                    pass
    except Exception:
        pass

    # Lighting Bake keys are intentionally tagged JITTER (green) so they are
    # visually distinct from normal animation keys. This does not change the
    # keyframe values, interpolation, or any exported show data.
    if keyed:
        _mark_color_keyframes_jitter(obj, frame)

    return keyed


def _get_socket_color_at_frame(socket, frame):
    try:
        value = list(socket.default_value)
    except Exception:
        return None
    try:
        for fc in _socket_fcurves(socket):
            idx = int(fc.array_index)
            if 0 <= idx < len(value):
                value[idx] = fc.evaluate(frame)
    except Exception:
        pass
    while len(value) < 4:
        value.append(0.0)
    return tuple(clamp(float(v)) for v in value[:4])


# ============================================================
# PREVIEWS
# ============================================================

def get_preview_collection():

    if "gradients" not in preview_collections:

        preview_collections[
            "gradients"
        ] = bpy.utils.previews.new()

    return preview_collections[
        "gradients"
    ]


def _gradient_preview_signature(preset, preview_width=128, preview_height=20):
    """Stable signature for a gradient preview across Blender sessions.

    The requested preview dimensions are part of the runtime icon key so the UI
    can change width without reusing an icon generated at another aspect ratio.
    """
    parts = [
        str(getattr(preset, "name", "Gradient")),
        str(getattr(preset, "interpolation", "LINEAR")),
        f"W{int(preview_width)}",
        f"H{int(preview_height)}",
    ]
    try:
        stops = sorted(
            list(preset.stops),
            key=lambda stop: float(stop.position)
        )
    except Exception:
        stops = []
    for stop in stops:
        c = tuple(float(v) for v in stop.color[:4])
        parts.append(
            f"{float(stop.position):.8f}:"
            f"{c[0]:.8f},{c[1]:.8f},{c[2]:.8f},{c[3]:.8f}"
        )
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _gradient_preview_icon_key(preset, preview_width=128, preview_height=20):
    return (
        "gradient_"
        + _gradient_preview_signature(
            preset, preview_width, preview_height
        )
    )


def _evaluate_gradient_preset_preview(preset, t):
    """Evaluate a stored gradient without touching the active Blender ColorRamp."""
    try:
        stops = sorted(
            list(preset.stops),
            key=lambda stop: float(stop.position)
        )
    except Exception:
        stops = []

    if not stops:
        return (1.0, 1.0, 1.0)

    t = clamp(float(t))

    if len(stops) == 1:
        return tuple(float(v) for v in stops[0].color[:3])

    if t <= float(stops[0].position):
        return tuple(float(v) for v in stops[0].color[:3])

    if t >= float(stops[-1].position):
        return tuple(float(v) for v in stops[-1].color[:3])

    for left, right in zip(stops, stops[1:]):
        p0 = float(left.position)
        p1 = float(right.position)
        if t <= p1:
            span = max(1e-8, p1 - p0)
            u = clamp((t - p0) / span)
            interpolation = str(getattr(preset, "interpolation", "LINEAR"))
            if interpolation == 'CONSTANT':
                u = 0.0
            elif interpolation in {'EASE', 'BEZIER'}:
                u = u * u * (3.0 - 2.0 * u)
            c0 = left.color
            c1 = right.color
            return tuple(
                float(c0[k]) + (float(c1[k]) - float(c0[k])) * u
                for k in range(3)
            )

    return tuple(float(v) for v in stops[-1].color[:3])


def _write_gradient_preview_png(filepath, width, height, color_fn):
    """Write a small RGBA PNG without creating/modifying a Blender Image datablock.

    This keeps catalog thumbnails safe during load_post/timer callbacks and also
    avoids the restricted-context Image.pixels errors seen during file loading.
    """
    import struct
    import zlib

    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type: None
        for x in range(width):
            r, g, b = color_fn(x / float(max(1, width - 1)))
            raw.extend((
                int(round(clamp(float(r)) * 255.0)),
                int(round(clamp(float(g)) * 255.0)),
                int(round(clamp(float(b)) * 255.0)),
                255,
            ))

    def chunk(tag, data):
        return (
            struct.pack('>I', len(data))
            + tag
            + data
            + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    png = bytearray(b'\x89PNG\r\n\x1a\n')
    png += chunk(
        b'IHDR',
        struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
    )
    png += chunk(b'IDAT', zlib.compress(bytes(raw), 6))
    png += chunk(b'IEND', b'')
    Path(filepath).write_bytes(bytes(png))


def generate_gradient_preview_image(
    preset,
    node=None,
    preview_width=128,
    preview_height=20
):
    """Generate a catalog thumbnail using only a temporary PNG + preview collection.

    No bpy.data.images datablock is created or modified. This is intentionally
    safe to call from a deferred load callback after a .blend has opened.
    """
    if preset is None:
        return

    try:
        width = max(32, int(preview_width))
        height = max(8, int(preview_height))
        signature = _gradient_preview_signature(preset, width, height)
        icon_key = f"gradient_{signature}"

        ramp = None
        if node is not None and hasattr(node, "color_ramp"):
            ramp = node.color_ramp

        if ramp is not None:
            def color_fn(t):
                rgb = ramp.evaluate(t)
                return float(rgb[0]), float(rgb[1]), float(rgb[2])
        else:
            def color_fn(t):
                rgb = _evaluate_gradient_preset_preview(preset, t)
                return float(rgb[0]), float(rgb[1]), float(rgb[2])

        filepath = os.path.join(
            bpy.app.tempdir,
            f"sparkshow_gradient_{signature}.png"
        )
        _write_gradient_preview_png(
            filepath,
            width,
            height,
            color_fn
        )

        pcoll = get_preview_collection()
        if icon_key in pcoll:
            try:
                del pcoll[icon_key]
            except Exception:
                pass
        pcoll.load(icon_key, filepath, 'IMAGE')
        preset.image_name = icon_key

    except Exception as e:
        print("[Sparkshow Studio] Preview error:", e)


def rebuild_gradient_previews():
    """Rebuild all gradient thumbnails after opening/reloading a .blend."""
    try:
        old = preview_collections.pop("gradients", None)
        if old is not None:
            try:
                bpy.utils.previews.remove(old)
            except Exception:
                pass
    except Exception:
        pass

    try:
        for scene in bpy.data.scenes:
            items = getattr(scene, "studio_palette_gradient_items", None)
            if not items:
                continue
            width_factor = float(
                getattr(
                    scene,
                    "studio_palette_gradient_preview_width",
                    1.0
                )
            )
            preview_width = int(
                128.0 * max(0.5, min(3.0, width_factor))
            )
            for preset in items:
                generate_gradient_preview_image(
                    preset,
                    None,
                    preview_width=preview_width,
                    preview_height=20
                )
    except Exception as e:
        print("[Sparkshow Studio] Gradient catalog rebuild error:", e)


def _deferred_gradient_catalog_rebuild():
    global GRADIENT_PREVIEW_REBUILD_TIMER
    GRADIENT_PREVIEW_REBUILD_TIMER = False
    try:
        rebuild_gradient_previews()
    except Exception as e:
        print("[Sparkshow Studio] Deferred gradient catalog rebuild error:", e)
    return None


def schedule_gradient_catalog_rebuild(delay=0.15):
    """Schedule thumbnail rebuild outside Blender's restricted load/register context."""
    global GRADIENT_PREVIEW_REBUILD_TIMER
    try:
        if GRADIENT_PREVIEW_REBUILD_TIMER:
            return
        bpy.app.timers.register(
            _deferred_gradient_catalog_rebuild,
            first_interval=max(0.05, float(delay))
        )
        GRADIENT_PREVIEW_REBUILD_TIMER = True
    except Exception as e:
        GRADIENT_PREVIEW_REBUILD_TIMER = False
        print("[Sparkshow Studio] Gradient catalog timer error:", e)


def ensure_gradient_preview(
    preset,
    preview_width=128,
    preview_height=20
):
    """Return a runtime preview key without mutating Blender datablocks in UI draw."""
    if preset is None:
        return None

    preview_width = max(32, int(preview_width))
    preview_height = max(8, int(preview_height))
    expected = _gradient_preview_icon_key(
        preset,
        preview_width,
        preview_height
    )
    pcoll = get_preview_collection()
    if expected not in pcoll:
        return None
    return expected

def _tag_view3d_redraw(context=None):
    try:
        wm = getattr(context, "window_manager", None) if context else None
        if wm is None:
            wm = bpy.context.window_manager
        for window in wm.windows:
            screen = window.screen
            if not screen:
                continue
            for area in screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
                elif area.type == 'PROPERTIES':
                    area.tag_redraw()
    except Exception:
        pass


def update_gradient_preview_width(self, context):
    """Regenerate catalog thumbnails after Blender leaves the property-update context."""
    schedule_gradient_catalog_rebuild()
    _tag_view3d_redraw(context)


def update_gradient_preview_size(self, context):
    """Refresh the list when thumbnail display scale changes.

    This does not rebuild image data because size is a UI scale only.
    """
    _tag_view3d_redraw(context)


def cleanup_preview_images():

    for image in list(
        bpy.data.images
    ):

        if image.name.startswith(
            "_SparkshowStudioLightingPreview_"
        ):

            try:

                bpy.data.images.remove(
                    image
                )

            except Exception:
                pass


# ============================================================
# PROPERTY GROUPS
# ============================================================

def _save_preview_color(obj):
    """Save the visible lighting state before a temporary preview override."""
    try:
        name = obj.name
        if name in _PREVIEW_SAVED_COLORS:
            return
        if _is_shared_object_color_backend(obj):
            _PREVIEW_SAVED_COLORS[name] = {
                "backend": "OBJECT",
                "color": tuple(float(v) for v in obj.color[:4]),
            }
            return
        values = []
        for socket in get_sockets_for_drone(obj):
            try:
                values.append((socket, tuple(float(v) for v in socket.default_value)))
            except Exception:
                pass
        _PREVIEW_SAVED_COLORS[name] = {"backend": "MATERIAL", "sockets": values}
    except Exception:
        pass


def _get_actual_drone_color(obj, frame):
    """Return the real current RGBW state, evaluating existing keyframes if present."""
    try:
        if _is_shared_object_color_backend(obj):
            values = [float(v) for v in obj.color[:4]]
            try:
                action = obj.animation_data.action if obj.animation_data else None
                if action:
                    for fc in action.fcurves:
                        if fc.data_path == "color" and 0 <= fc.array_index < 4:
                            values[fc.array_index] = fc.evaluate(frame)
            except Exception:
                pass
            return tuple(clamp(v) for v in values)
        sockets = get_sockets_for_drone(obj)
        if sockets:
            color = _get_socket_color_at_frame(sockets[0], frame)
            if color is not None:
                return color
        return (1.0, 1.0, 1.0, 0.0)
    except Exception:
        return (1.0, 1.0, 1.0, 0.0)


def _restore_evaluated_drone_color(obj, frame):
    """Restore the real animated color at the current frame."""
    try:
        if _is_shared_object_color_backend(obj):
            obj.color = _get_actual_drone_color(obj, frame)
            return
        color = _get_actual_drone_color(obj, frame)
        set_drone_color(obj, color)
    except Exception:
        pass


def _clear_preview_override(scene=None):
    """Restore the real animated state after a temporary Lighting preview override."""
    if not _PREVIEW_SAVED_COLORS:
        return
    frame = int(getattr(scene, "frame_current", 1)) if scene is not None else int(bpy.context.scene.frame_current)
    for name in tuple(_PREVIEW_SAVED_COLORS):
        obj = bpy.data.objects.get(name)
        if obj is not None:
            _restore_evaluated_drone_color(obj, frame)
    _PREVIEW_SAVED_COLORS.clear()


def _enable_object_color_viewport_preview():
    """Make Object.color visible in Solid viewport while Live Preview is active."""
    global _PREVIEW_SAVED_SHADING
    try:
        wm = bpy.context.window_manager
        for window in wm.windows:
            screen = window.screen
            if not screen:
                continue
            for area in screen.areas:
                if area.type != 'VIEW_3D':
                    continue
                for space in area.spaces:
                    if space.type != 'VIEW_3D':
                        continue
                    shading = space.shading
                    key = space.as_pointer()
                    if shading.type == 'SOLID':
                        if key not in _PREVIEW_SAVED_SHADING:
                            _PREVIEW_SAVED_SHADING[key] = getattr(shading, 'color_type', None)
                        if hasattr(shading, 'color_type'):
                            shading.color_type = 'OBJECT'
                    area.tag_redraw()
    except Exception:
        pass


def _restore_object_color_viewport_preview():
    """Restore Solid viewport color settings changed by Live Preview."""
    global _PREVIEW_SAVED_SHADING
    if not _PREVIEW_SAVED_SHADING:
        return
    try:
        wm = bpy.context.window_manager
        for window in wm.windows:
            screen = window.screen
            if not screen:
                continue
            for area in screen.areas:
                if area.type != 'VIEW_3D':
                    continue
                for space in area.spaces:
                    if space.type != 'VIEW_3D':
                        continue
                    key = space.as_pointer()
                    if key in _PREVIEW_SAVED_SHADING:
                        old = _PREVIEW_SAVED_SHADING[key]
                        if old and hasattr(space.shading, 'color_type'):
                            try:
                                space.shading.color_type = old
                            except Exception:
                                pass
                    area.tag_redraw()
    except Exception:
        pass
    finally:
        _PREVIEW_SAVED_SHADING.clear()


def _update_live_preview_property(self=None, context=None):
    """One preview switch for both UNI and DÉGRADÉ modes."""
    scene = getattr(context, "scene", None) if context else None
    if scene is None:
        return

    if getattr(scene, "studio_palette_live_preview", False):
        enable_live_preview(scene)
    else:
        disable_live_preview(scene)


def _palette_mode_update(self=None, context=None):
    """Switch UNI/DÉGRADÉ through the same preview engine, never two previews."""
    scene = getattr(context, "scene", None) if context else None
    if scene is None or not getattr(scene, "studio_palette_live_preview", False):
        return
    _run_live_preview(scene)


def _live_preview_property_update(self=None, context=None):
    """Rafraîchit immédiatement le preview lorsqu'un réglage change."""
    if context is None:
        return

    scene = getattr(context, "scene", None)
    if scene is None or not getattr(scene, "studio_palette_live_preview", False):
        return

    _run_live_preview(scene)


class STUDIO_GradientStopItem(
    bpy.types.PropertyGroup
):

    position: bpy.props.FloatProperty(
        name="Position",
        min=0.0,
        max=1.0,
        default=0.0,
        update=_live_preview_property_update
    )

    color: bpy.props.FloatVectorProperty(
        name="Couleur",
        subtype='COLOR',
        size=4,
        min=0.0,
        max=1.0,
        default=(1, 1, 1, 0),
        update=_live_preview_property_update
    )


class STUDIO_GradientPresetItem(
    bpy.types.PropertyGroup
):

    name: bpy.props.StringProperty(
        name="Nom",
        default="Dégradé"
    )

    stops: bpy.props.CollectionProperty(
        type=STUDIO_GradientStopItem
    )

    image_name: bpy.props.StringProperty(
        name="Nom Aperçu",
        default=""
    )

    interpolation: bpy.props.EnumProperty(
        name="Interpolation Aperçu",
        items=[
            ('CONSTANT', "Constante", ""),
            ('LINEAR', "Linéaire", ""),
            ('EASE', "Ease", ""),
            ('BEZIER', "Bézier", "")
        ],
        default='LINEAR'
    )


class STUDIO_ColorItem(
    bpy.types.PropertyGroup
):

    name: bpy.props.StringProperty(
        name="Nom",
        default="Couleur"
    )

    color: bpy.props.FloatVectorProperty(
        name="Couleur RGBW",
        subtype='COLOR',
        size=4,
        min=0.0,
        max=1.0,
        default=(1, 1, 1, 0),
        update=_live_preview_property_update
    )


# ============================================================
# RAMP
# ============================================================

RAMP_GROUP_NAME = (
    "_SPARKSHOW_STUDIO_PALETTE_RAMP"
)


def ensure_ramp_node():

    ng = bpy.data.node_groups.get(
        RAMP_GROUP_NAME
    )

    if not ng:

        ng = bpy.data.node_groups.new(
            RAMP_GROUP_NAME,
            'ShaderNodeTree'
        )

    node = ng.nodes.get(
        "ColorRampNode"
    )

    if not node:

        node = ng.nodes.new(
            'ShaderNodeValToRGB'
        )

        node.name = (
            "ColorRampNode"
        )

        node.label = (
            "Sparkshow Studio Gradient"
        )

    return node


def get_ramp_node():

    ng = bpy.data.node_groups.get(
        RAMP_GROUP_NAME
    )

    if not ng:
        return None

    return ng.nodes.get(
        "ColorRampNode"
    )


def sync_ramp_to_preset(
    node,
    preset
):

    if (
        not node
        or
        not hasattr(
            node,
            "color_ramp"
        )
    ):
        return

    preset.stops.clear()
    try:
        preset.interpolation = str(node.color_ramp.interpolation)
    except Exception:
        pass

    for element in node.color_ramp.elements:

        stop = preset.stops.add()

        stop.position = (
            element.position
        )

        stop.color = (
            element.color
        )

    generate_gradient_preview_image(
        preset,
        node
    )


def sync_preset_to_ramp(
    preset,
    node
):

    if (
        not node
        or
        not hasattr(
            node,
            "color_ramp"
        )
        or
        not preset.stops
    ):
        return

    ramp = node.color_ramp

    while (
        len(ramp.elements)
        >
        len(preset.stops)
    ):

        if len(
            ramp.elements
        ) <= 2:
            break

        ramp.elements.remove(
            ramp.elements[-1]
        )

    while (
        len(ramp.elements)
        <
        len(preset.stops)
    ):

        ramp.elements.new(
            0.5
        )

    sorted_stops = sorted(
        preset.stops,
        key=lambda x:
        x.position
    )

    for index, stop in enumerate(
        sorted_stops
    ):

        if (
            index >=
            len(ramp.elements)
        ):
            break

        ramp.elements[
            index
        ].position = stop.position

        ramp.elements[
            index
        ].color = stop.color

    generate_gradient_preview_image(
        preset,
        node
    )


def update_active_gradient(
    self,
    context
):

    scene = context.scene

    items = (
        scene.studio_palette_gradient_items
    )

    index = (
        scene.studio_palette_gradient_index
    )

    if (
        0 <= index <
        len(items)
    ):

        node = ensure_ramp_node()

        sync_preset_to_ramp(
            items[index],
            node
        )

        DRONE_CACHE[
            "dirty"
        ] = True


# ============================================================
# CURVES
# ============================================================

def bezier_point(
    p0,
    p1,
    p2,
    p3,
    t
):

    u = 1.0 - t

    return (
        p0 * (u ** 3)
        +
        p1 * (3 * u * u * t)
        +
        p2 * (3 * u * t * t)
        +
        p3 * (t ** 3)
    )


def build_curve_points(
    obj,
    resolution=300
):

    if (
        not obj
        or
        obj.type != 'CURVE'
    ):
        return []

    points = []

    world = obj.matrix_world

    for spline in obj.data.splines:

        if spline.type == 'POLY':

            coords = [
                world @ p.co.xyz
                for p in spline.points
            ]

            if len(coords) >= 2:
                points.extend(coords)

        elif spline.type == 'BEZIER':

            bezier_points = (
                spline.bezier_points
            )

            count = len(
                bezier_points
            )

            if count < 2:
                continue

            for i in range(
                count - 1
            ):

                p0 = (
                    world @
                    bezier_points[i].co
                )

                p1 = (
                    world @
                    bezier_points[i].handle_right
                )

                p2 = (
                    world @
                    bezier_points[
                        i + 1
                    ].handle_left
                )

                p3 = (
                    world @
                    bezier_points[
                        i + 1
                    ].co
                )

                samples = max(
                    4,
                    resolution //
                    max(
                        1,
                        count - 1
                    )
                )

                for j in range(
                    samples
                ):

                    t = (
                        j /
                        float(samples)
                    )

                    points.append(
                        bezier_point(
                            p0,
                            p1,
                            p2,
                            p3,
                            t
                        )
                    )

            points.append(
                world @
                bezier_points[-1].co
            )

        else:

            try:

                for p in spline.points:

                    points.append(
                        world @
                        p.co.xyz
                    )

            except Exception:
                pass

    return points


def get_curve_cache(
    scene,
    target
):

    if (
        not target
        or
        target.type != 'CURVE'
    ):
        return []

    key = (
        target.as_pointer(),
        target.matrix_world.copy().__repr__()
    )

    if key not in DRONE_CACHE[
        "curve"
    ]:

        DRONE_CACHE[
            "curve"
        ][key] = (
            build_curve_points(
                target
            )
        )

    return DRONE_CACHE[
        "curve"
    ][key]


def closest_curve_factor(
    position,
    curve_points
):

    if not curve_points:
        return 0.0

    closest_index = 0
    closest_distance = float(
        "inf"
    )

    for index, point in enumerate(
        curve_points
    ):

        distance = (
            point -
            position
        ).length_squared

        if distance < closest_distance:

            closest_distance = distance
            closest_index = index

    if len(
        curve_points
    ) <= 1:

        return 0.0

    return (
        closest_index /
        float(
            len(curve_points) - 1
        )
    )


# ============================================================
# SPATIAL ENGINE
# ============================================================

def compute_spatial_factors(
    scene,
    target_objects
):

    mode = scene.studio_palette_grad_axis

    if not target_objects:
        return {}

    positions = {}

    # Always use the evaluated world-space position at the current frame.
    # Cached positions can be stale when a drone follows an animated anchor.
    for obj in target_objects:
        name = get_drone_name(obj)
        try:
            positions[name] = obj.matrix_world.translation.copy()
        except (ReferenceError, AttributeError, RuntimeError):
            continue

    result = {}

    # ========================================================
    # AXES
    # ========================================================

    if mode in {
        'X',
        '-X',
        'Y',
        '-Y',
        'Z',
        '-Z'
    }:

        axis_map = {
            'X': 0,
            '-X': 0,
            'Y': 1,
            '-Y': 1,
            'Z': 2,
            '-Z': 2
        }

        axis = axis_map[
            mode
        ]

        values = [
            pos[axis]
            for pos in positions.values()
        ]

        if not values:
            return {get_drone_name(obj): 0.0 for obj in target_objects}

        minimum = min(values)
        maximum = max(values)

        delta = (
            maximum -
            minimum
        )

        if abs(delta) < EPSILON:
            delta = 1.0

        for name, pos in positions.items():

            result[name] = (
                pos[axis] -
                minimum
            ) / delta

        return result

    # ========================================================
    # OBJECT
    # ========================================================

    if mode == 'OBJECT':

        target = (
            scene.studio_palette_grad_target
        )

        if not target:

            return {
                get_drone_name(obj): 0.0
                for obj in target_objects
            }

        origin = (
            target.matrix_world.translation
        )

        direction = (
            target.matrix_world.to_3x3()
            @ Vector((0, 0, 1))
        )

        if direction.length < EPSILON:

            direction = Vector(
                (0, 0, 1)
            )

        direction.normalize()

        projections = {}

        for name, pos in positions.items():

            projections[name] = (
                pos -
                origin
            ).dot(
                direction
            )

        if not projections:
            return {get_drone_name(obj): 0.0 for obj in target_objects}

        minimum = min(
            projections.values()
        )

        maximum = max(
            projections.values()
        )

        delta = (
            maximum -
            minimum
        )

        if abs(delta) < EPSILON:
            delta = 1.0

        for name, value in projections.items():

            result[name] = (
                value -
                minimum
            ) / delta

        return result

    # ========================================================
    # CURVE
    # ========================================================

    if mode == 'CURVE':

        target = (
            scene.studio_palette_grad_target
        )

        curve_points = (
            get_curve_cache(
                scene,
                target
            )
        )

        if not curve_points:

            return {
                get_drone_name(obj): 0.0
                for obj in target_objects
            }

        for obj in target_objects:

            name = get_drone_name(
                obj
            )

            position = positions[
                name
            ]

            result[name] = (
                closest_curve_factor(
                    position,
                    curve_points
                )
            )

        return result

    # ========================================================
    # RADIAL
    # ========================================================

    if mode == 'RADIAL':

        target = (
            scene.studio_palette_grad_target
        )

        if target:

            center = (
                target.matrix_world.translation
            )

        else:

            center = Vector(
                (0, 0, 0)
            )

        distances = {
            name:
            (
                pos -
                center
            ).length

            for name, pos
            in positions.items()
        }

        if not distances:
            return {get_drone_name(obj): 0.0 for obj in target_objects}

        minimum = min(
            distances.values()
        )

        maximum = max(
            distances.values()
        )

        delta = (
            maximum -
            minimum
        )

        if abs(delta) < EPSILON:
            delta = 1.0

        for name, distance in distances.items():

            result[name] = (
                distance -
                minimum
            ) / delta

        return result

    # ========================================================
    # ANGULAR
    # ========================================================

    if mode == 'ANGULAR':

        target = (
            scene.studio_palette_grad_target
        )

        if target:

            center = (
                target.matrix_world.translation
            )

        else:

            center = Vector(
                (0, 0, 0)
            )

        for name, pos in positions.items():

            delta = (
                pos -
                center
            )

            angle = math.atan2(
                delta.y,
                delta.x
            )

            result[name] = (
                angle +
                math.pi
            ) / (
                2.0 *
                math.pi
            )

        return result

    return {
        get_drone_name(obj): 0.0
        for obj in target_objects
    }


def get_spatial_factor(
    obj,
    spatial_cache,
    invert=False,
    direction_mode=""
):

    name = get_drone_name(
        obj
    )

    factor = spatial_cache.get(
        name,
        0.0
    )

    if (
        direction_mode.startswith("-")
        or
        invert
    ):

        factor = 1.0 - factor

    return clamp(
        factor
    )


# ============================================================
# COLOR ENGINE
# ============================================================

def evaluate_gradient(
    scene,
    factor
):

    node = get_ramp_node()

    if (
        not node
        or
        not hasattr(
            node,
            "color_ramp"
        )
    ):

        return Vector(
            (1, 0, 0)
        )

    rgb = node.color_ramp.evaluate(
        clamp(factor)
    )

    return Vector(
        (
            rgb[0],
            rgb[1],
            rgb[2]
        )
    )


def get_solid_color(
    scene
):

    items = (
        scene.studio_palette_color_items
    )

    index = (
        scene.studio_palette_color_index
    )

    if not items:

        return Vector(
            (1, 1, 1, 1)
        )

    if not (
        0 <= index <
        len(items)
    ):

        return Vector(
            (1, 1, 1, 1)
        )

    return Vector(
        items[index].color
    )


# ============================================================
# EFFECT ENGINE
# ============================================================

def get_progress(
    scene,
    frame,
    start_frame,
    duration
):

    if duration <= 1:
        return 0.0

    return clamp(
        (
            frame -
            start_frame
        ) /
        float(
            duration - 1
        )
    )


def _gradient_effect_window(scene):
    """Return the active frame window of the gradient effect."""
    start = int(getattr(scene, "studio_palette_grad_start_frame", 1))
    duration = max(1, int(getattr(scene, "studio_palette_grad_duration", 1)))
    end = start + duration - 1
    return start, end, duration


def _apply_gradient_effect_fade(color, scene, frame, start, end):
    """Apply optional entry/exit fades to a gradient effect color."""
    if color is None:
        return color

    fade_in = max(0, int(getattr(scene, "studio_palette_grad_fade_in", 0)))
    fade_out = max(0, int(getattr(scene, "studio_palette_grad_fade_out", 0)))

    span = max(0, end - start)
    total_fade = fade_in + fade_out

    # Keep a non-overlapping fade envelope when the requested fades are
    # longer than the effect itself.
    if total_fade > span and total_fade > 0:
        scale = span / float(total_fade)
        fade_in = int(round(fade_in * scale))
        fade_out = int(round(fade_out * scale))

    factor = 1.0
    curve = getattr(scene, "studio_palette_grad_fade_curve", "LINEAR")

    if fade_in > 0 and frame <= start + fade_in:
        t = clamp((frame - start) / float(max(1, fade_in)))
        factor *= smoothstep(t) if curve == 'BEZIER' else t

    if fade_out > 0 and frame >= end - fade_out:
        t = clamp((end - frame) / float(max(1, fade_out)))
        factor *= smoothstep(t) if curve == 'BEZIER' else t

    return Vector((
        color[0] * factor,
        color[1] * factor,
        color[2] * factor,
        color[3] * factor,
    ))


def compute_effect_color(
    obj,
    scene,
    spatial_factor,
    frame,
    target_objects
):
    """Compute the existing effect and apply the optional fade envelope."""
    if scene.studio_palette_mode == 'SOLID':
        return _compute_effect_color_base(
            obj, scene, spatial_factor, frame, target_objects
        )

    start, end, _duration = _gradient_effect_window(scene)

    if frame < start or frame > end:
        return Vector(_get_actual_drone_color(obj, frame))

    base_color = _compute_effect_color_base(
        obj, scene, spatial_factor, frame, target_objects
    )

    return _apply_gradient_effect_fade(
        base_color, scene, frame, start, end
    )


def _compute_effect_color_base(
    obj,
    scene,
    spatial_factor,
    frame,
    target_objects,
    effect_start_frame=None,
    effect_duration=None
):

    mode = scene.studio_palette_mode

    # The preview must not overwrite the drone's existing RGBW state before
    # the first frame where the selected lighting effect is scheduled.  This
    # was especially visible with gradients: the selected color appeared from
    # frame 1 even when the effect was configured to start later.
    if effect_start_frame is None:
        if mode == 'SOLID':
            effect_start_frame = int(getattr(scene, 'studio_palette_solid_start_frame', 1))
        else:
            effect_start_frame = int(getattr(scene, 'studio_palette_grad_start_frame', 1))
    else:
        effect_start_frame = int(effect_start_frame)

    if frame < effect_start_frame:
        return Vector(_get_actual_drone_color(obj, frame))

    if mode == 'SOLID':

        color = get_solid_color(
            scene
        )

        return Vector(
            (
                color[0],
                color[1],
                color[2],
                color[3]
            )
        )

    effect = (
        scene.studio_palette_grad_anim_type
    )

    cycles = (
        scene.studio_palette_grad_anim_cycles
    )

    speed = (
        scene.studio_palette_grad_anim_speed
    )

    # --------------------------------------------------------
    # IMPORTANT :
    # pour éviter que Frame active annule le preview,
    # on utilise le début de timeline configuré.
    # --------------------------------------------------------

    # Respect the temporal window supplied by the caller (notably the
    # per-drone window used by the compact 2-key/marker bake).  Falling back
    # to the scene setting keeps the normal preview/frame-by-frame path intact.
    start_frame = (
        int(effect_start_frame)
        if effect_start_frame is not None
        else int(scene.studio_palette_grad_start_frame)
    )

    duration = max(
        1,
        int(effect_duration) if effect_duration is not None else int(scene.studio_palette_grad_duration)
    )

    progress = get_progress(
        scene,
        frame,
        start_frame,
        duration
    )

    white = (
        scene.studio_palette_grad_white
    )

    # ========================================================
    # STATIC
    # ========================================================

    if effect == 'STATIC':

        rgb = evaluate_gradient(
            scene,
            spatial_factor
        )

        return Vector(
            (
                rgb[0],
                rgb[1],
                rgb[2],
                white
            )
        )

    # ========================================================
    # LINE DRAW
    # ========================================================

    if effect == 'LINE_DRAW':

        total = len(
            target_objects
        )

        if total <= 1:

            rank = 0

        else:

            rank = int(
                round(
                    spatial_factor *
                    (total - 1)
                )
            )

        delay = (
            scene.studio_palette_grad_anim_delay
        )

        trigger = (
            start_frame +
            rank * delay
        )

        if frame < trigger:
            return Vector(_get_actual_drone_color(obj, frame))

        elapsed = (
            frame -
            trigger
        )

        fade_time = max(
            0.01,
            scene.studio_palette_grad_fade_time
        )

        fade = clamp(
            elapsed /
            fade_time
        )

        if (
            scene.studio_palette_grad_fade_curve
            ==
            'BEZIER'
        ):

            fade = smoothstep(
                fade
            )

        rgb = evaluate_gradient(
            scene,
            spatial_factor
        )

        intensity = fade

        fade_count = (
            scene.studio_palette_grad_fade_count
        )

        if fade_count > 0:

            if rank < fade_count:

                t = (
                    rank /
                    max(
                        1,
                        fade_count - 1
                    )
                )

                intensity *= (
                    0.1 +
                    0.9 * t
                )

            elif (
                rank >=
                total -
                fade_count
            ):

                reverse_rank = (
                    total -
                    1 -
                    rank
                )

                t = (
                    reverse_rank /
                    max(
                        1,
                        fade_count - 1
                    )
                )

                intensity *= (
                    0.1 +
                    0.9 * t
                )

        return Vector(
            (
                rgb[0] * intensity,
                rgb[1] * intensity,
                rgb[2] * intensity,
                white * intensity
            )
        )

    # ========================================================
    # CYCLE — spatial repetition of the gradient
    # ========================================================

    if effect == 'CYCLE':

        # The gradient is repeated spatially across the formation. Every
        # drone receives a valid ramp color; the modulo wrap prevents the
        # artificial black band that can occur when a temporal line-draw
        # effect is mistaken for a cyclic gradient.
        factor = (
            spatial_factor * max(0.1, float(cycles))
        ) % 1.0

        rgb = evaluate_gradient(
            scene,
            factor
        )

        return Vector(
            (
                rgb[0],
                rgb[1],
                rgb[2],
                white
            )
        )

    # ========================================================
    # WAVE
    # ========================================================

    if effect == 'WAVE':

        factor = (
            spatial_factor +
            progress * cycles
        ) % 1.0

        rgb = evaluate_gradient(
            scene,
            factor
        )

        return Vector(
            (
                rgb[0],
                rgb[1],
                rgb[2],
                white
            )
        )

    # ========================================================
    # ROTARY
    # ========================================================

    if effect == 'ROTARY':

        factor = (
            spatial_factor +
            progress * cycles
        ) % 1.0

        rgb = evaluate_gradient(
            scene,
            factor
        )

        return Vector(
            (
                rgb[0],
                rgb[1],
                rgb[2],
                white
            )
        )

    # ========================================================
    # SCANNER / KITT
    # ========================================================

    if effect in {
        'SCANNER',
        'KITT'
    }:

        scan_position = (
            progress *
            cycles
        ) % 2.0

        if scan_position > 1.0:

            scan_position = (
                2.0 -
                scan_position
            )

        width = clamp(
            scene.studio_palette_grad_scan_width,
            0.001,
            1.0
        )

        distance = abs(
            spatial_factor -
            scan_position
        )

        intensity = max(
            0.0,
            1.0 -
            distance / width
        )

        intensity = smoothstep(
            intensity
        )

        if effect == 'KITT':

            rgb = evaluate_gradient(
                scene,
                scan_position
            )

        else:

            rgb = evaluate_gradient(
                scene,
                spatial_factor
            )

        return Vector(
            (
                rgb[0] * intensity,
                rgb[1] * intensity,
                rgb[2] * intensity,
                white * intensity
            )
        )

    # ========================================================
    # METEOR
    # ========================================================

    if effect == 'METEOR':

        head = (
            progress *
            cycles
        ) % 1.0

        distance = (
            head -
            spatial_factor
        )

        if distance < 0:
            distance += 1.0

        tail_length = clamp(
            scene.studio_palette_grad_tail_length,
            0.001,
            1.0
        )

        if distance <= tail_length:

            local = (
                1.0 -
                distance /
                tail_length
            )

            intensity = smoothstep(
                local
            )

            rgb = evaluate_gradient(
                scene,
                local
            )

            return Vector(
                (
                    rgb[0] * intensity,
                    rgb[1] * intensity,
                    rgb[2] * intensity,
                    white * intensity
                )
            )

        return Vector(
            (0, 0, 0, 0)
        )

    # ========================================================
    # STARS
    # ========================================================

    if effect == 'STARS':

        seed = DRONE_CACHE[
            "seed"
        ].get(
            get_drone_name(obj),
            stable_seed(
                obj.name
            )
        )

        rng = random.Random(
            seed
        )

        phase = (
            rng.random()
            *
            math.pi
            *
            2.0
        )

        individual_speed = (
            rng.uniform(
                0.5,
                2.0
            )
        )

        twinkle = (
            math.sin(
                frame *
                0.1 *
                individual_speed *
                speed +
                phase
            )
            +
            1.0
        ) / 2.0

        rgb = evaluate_gradient(
            scene,
            twinkle
        )

        return Vector(
            (
                rgb[0] * twinkle,
                rgb[1] * twinkle,
                rgb[2] * twinkle,
                white * twinkle
            )
        )

    # ========================================================
    # PULSE
    # ========================================================

    if effect == 'PULSE':

        phase = (
            spatial_factor *
            math.pi
        )

        pulse = (
            math.sin(
                progress *
                cycles *
                speed *
                math.pi *
                2.0 +
                phase
            )
            +
            1.0
        ) / 2.0

        pulse = smoothstep(
            pulse
        )

        # Pulsation luminance floor: never allow the effect to turn the
        # gradient black unless the user explicitly chooses 0%.
        min_intensity = max(
            0.0,
            min(
                1.0,
                float(
                    getattr(
                        scene,
                        'studio_palette_grad_pulse_min_intensity',
                        0.20
                    )
                )
            )
        )

        pulse = (
            min_intensity +
            (1.0 - min_intensity) * pulse
        )

        rgb = evaluate_gradient(
            scene,
            pulse
        )

        return Vector(
            (
                rgb[0] * pulse,
                rgb[1] * pulse,
                rgb[2] * pulse,
                white * pulse
            )
        )

    # ========================================================
    # HEARTBEAT
    # ========================================================

    if effect == 'HEARTBEAT':

        t = (
            progress *
            cycles
        ) % 1.0

        pulse1 = math.exp(
            -(
                (t - 0.20) /
                0.08
            ) ** 2
        )

        pulse2 = math.exp(
            -(
                (t - 0.38) /
                0.12
            ) ** 2
        )

        intensity = clamp(
            pulse1 +
            pulse2
        )

        rgb = evaluate_gradient(
            scene,
            intensity
        )

        return Vector(
            (
                rgb[0] * intensity,
                rgb[1] * intensity,
                rgb[2] * intensity,
                white * intensity
            )
        )

    # ========================================================
    # STROBE
    # ========================================================

    if effect == 'STROBE':

        frequency = max(
            0.1,
            speed
        )

        value = math.sin(
            frame *
            frequency *
            math.pi
        )

        intensity = (
            1.0
            if value >= 0
            else 0.0
        )

        rgb = evaluate_gradient(
            scene,
            spatial_factor
        )

        return Vector(
            (
                rgb[0] * intensity,
                rgb[1] * intensity,
                rgb[2] * intensity,
                white * intensity
            )
        )

    rgb = evaluate_gradient(
        scene,
        spatial_factor
    )

    return Vector(
        (
            rgb[0],
            rgb[1],
            rgb[2],
            white
        )
    )


# ============================================================
# LIVE PREVIEW
# ============================================================


def update_preview_colors(scene):
    """
    Calcule et applique la couleur à la frame courante.

    Cette fonction utilise exactement le même moteur que le Bake :
    compute_effect_color(). Aucune keyframe n'est créée.
    """
    if scene is None or not getattr(scene, "studio_palette_live_preview", False):
        return

    target_objects = get_drone_cache(scene)
    if not target_objects:
        return

    # Recalcule les positions/facteurs comme le Bake.
    for obj in target_objects:
        name = get_drone_name(obj)
        try:
            DRONE_CACHE["positions"][name] = obj.matrix_world.translation.copy()
        except Exception:
            pass

    spatial_cache = compute_spatial_factors(scene, target_objects)
    frame = scene.frame_current
    invert = scene.studio_palette_grad_invert_direction
    direction = scene.studio_palette_grad_axis

    total_sockets = 0
    total_changed = 0
    total_linked = 0

    for obj in target_objects:
        _ensure_object_color_material(obj)
        factor = get_spatial_factor(
            obj, spatial_cache, invert, direction
        )

        color = compute_effect_color(
            obj, scene, factor, frame, target_objects
        )

        if color is not None:
            _save_preview_color(obj)
            changed, linked, socket_count = set_drone_color(obj, color)
            total_changed += changed
            total_linked += linked
            total_sockets += socket_count

    # Force a dependency-graph refresh so material/socket changes are reflected immediately.
    try:
        context_view_layer = bpy.context.view_layer
        if context_view_layer is not None:
            context_view_layer.update()
    except Exception:
        pass

    # Diagnostic léger : permet de distinguer
    # "le handler ne tourne pas" de "le shader n'accepte pas la couleur".
    print(
        f"[Sparkshow Studio] Live Preview frame={frame} "
        f"drones={len(target_objects)} sockets={total_sockets} "
        f"modifies={total_changed} linked={total_linked}"
    )


@persistent
def live_preview_frame_handler(scene):
    """Handler léger : une mise à jour à chaque changement de frame."""
    global LIVE_PREVIEW_LAST_FRAME

    if scene is None or not getattr(scene, "studio_palette_live_preview", False):
        return

    if LIVE_PREVIEW_BAKING:
        return

    # Même frame = inutile de recalculer.
    frame = scene.frame_current
    if frame == LIVE_PREVIEW_LAST_FRAME:
        return

    _run_live_preview(scene)
    LIVE_PREVIEW_LAST_FRAME = frame



def enable_live_preview(scene):
    global LIVE_PREVIEW_HANDLER_REGISTERED, LIVE_PREVIEW_LAST_FRAME
    LIVE_PREVIEW_LAST_FRAME = None
    try:
        handlers = bpy.app.handlers.frame_change_post
        if live_preview_frame_handler not in handlers:
            handlers.append(live_preview_frame_handler)
        LIVE_PREVIEW_HANDLER_REGISTERED = True
    except Exception:
        LIVE_PREVIEW_HANDLER_REGISTERED = False
    _run_live_preview(scene)



def disable_live_preview(scene=None):
    global LIVE_PREVIEW_HANDLER_REGISTERED, LIVE_PREVIEW_LAST_FRAME
    try:
        handlers = bpy.app.handlers.frame_change_post
        while live_preview_frame_handler in handlers:
            handlers.remove(live_preview_frame_handler)
    except Exception:
        pass
    LIVE_PREVIEW_HANDLER_REGISTERED = False
    LIVE_PREVIEW_LAST_FRAME = None
    _clear_preview_override(scene)



def _run_live_preview(scene):
    global LIVE_PREVIEW_UPDATING

    if LIVE_PREVIEW_UPDATING:
        return

    LIVE_PREVIEW_UPDATING = True
    try:
        update_preview_colors(scene)

        wm = getattr(bpy.context, "window_manager", None)
        if wm:
            for window in wm.windows:
                screen = window.screen
                if not screen:
                    continue
                for area in screen.areas:
                    if area.type == 'VIEW_3D':
                        area.tag_redraw()
    except Exception as e:
        print(f"[Sparkshow Studio] Live Preview error: {e}")
    finally:
        LIVE_PREVIEW_UPDATING = False


# ============================================================
# OUTLINES
# ============================================================

def toggle_selection_outlines(
    self,
    context
):

    for window in (
        context.window_manager.windows
    ):

        screen = window.screen

        if not screen:
            continue

        for area in screen.areas:

            if area.type != 'VIEW_3D':
                continue

            for space in area.spaces:

                if (
                    space.type ==
                    'VIEW_3D'
                ):

                    space.overlay.show_outline_selected = (
                        self.studio_palette_show_outlines
                    )


# ============================================================
# UI LISTS
# ============================================================

class STUDIO_PALETTE_UL_color_list(
    bpy.types.UIList
):

    def draw_item(
        self,
        context,
        layout,
        data,
        item,
        icon,
        active_data,
        active_propname
    ):

        row = layout.row(
            align=True
        )

        row.prop(
            item,
            "color",
            text="",
            emboss=True
        )

        row.prop(
            item,
            "color",
            index=3,
            text="W",
            emboss=True
        )

        row.prop(
            item,
            "name",
            text="",
            emboss=False
        )


class STUDIO_PALETTE_UL_gradient_list(
    bpy.types.UIList
):

    def draw_item(
        self,
        context,
        layout,
        data,
        item,
        icon,
        active_data,
        active_propname
    ):

        row = layout.row(
            align=True
        )

        scene = data if hasattr(data, "studio_palette_gradient_items") else None
        width_factor = float(
            getattr(
                scene,
                "studio_palette_gradient_preview_width",
                1.0
            )
        ) if scene is not None else 1.0
        preview_size = float(
            getattr(
                scene,
                "studio_palette_gradient_preview_size",
                2.0
            )
        ) if scene is not None else 2.0

        preview_width = int(
            128.0 * max(0.5, min(3.0, width_factor))
        )
        preview_height = 20

        icon_key = ensure_gradient_preview(
            item,
            preview_width=preview_width,
            preview_height=preview_height
        )
        pcoll = get_preview_collection()

        if icon_key and icon_key in pcoll:
            row.template_icon(
                pcoll[icon_key].icon_id,
                scale=max(0.5, min(6.0, preview_size))
            )
        else:
            row.label(text="", icon='COLOR')

        row.prop(
            item,
            "name",
            text="",
            emboss=False
        )


# ============================================================
# OPERATORS
# ============================================================

class STUDIO_PALETTE_OT_init_nodes(
    bpy.types.Operator
):

    bl_idname = (
        "sparkshow_studio.palette_init_nodes"
    )

    bl_label = (
        "Initialiser Ramp"
    )

    def execute(
        self,
        context
    ):

        ensure_ramp_node()

        self.report(
            {'INFO'},
            "Color Ramp initialisé."
        )

        return {'FINISHED'}


class STUDIO_PALETTE_OT_set_active_frame(
    bpy.types.Operator
):

    bl_idname = (
        "sparkshow_studio.palette_set_active_frame"
    )

    bl_label = "Frame active"

    def execute(
        self,
        context
    ):

        scene = context.scene

        if (
            scene.studio_palette_mode
            ==
            'SOLID'
        ):

            scene.studio_palette_solid_start_frame = (
                scene.frame_current
            )

        else:

            scene.studio_palette_grad_start_frame = (
                scene.frame_current
            )

        return {'FINISHED'}


class STUDIO_PALETTE_OT_add_color(
    bpy.types.Operator
):

    bl_idname = (
        "sparkshow_studio.palette_add_color"
    )

    bl_label = (
        "Ajouter couleur"
    )

    def execute(
        self,
        context
    ):

        scene = context.scene

        item = (
            scene.studio_palette_color_items.add()
        )

        item.name = (
            f"Couleur "
            f"{len(scene.studio_palette_color_items)}"
        )

        scene.studio_palette_color_index = (
            len(
                scene.studio_palette_color_items
            ) - 1
        )

        return {'FINISHED'}


class STUDIO_PALETTE_OT_add_gradient(
    bpy.types.Operator
):

    bl_idname = (
        "sparkshow_studio.palette_add_gradient"
    )

    bl_label = (
        "Ajouter dégradé"
    )

    def execute(
        self,
        context
    ):

        scene = context.scene

        item = (
            scene.studio_palette_gradient_items.add()
        )

        item.name = (
            f"Dégradé "
            f"{len(scene.studio_palette_gradient_items)}"
        )

        node = ensure_ramp_node()

        sync_ramp_to_preset(
            node,
            item
        )

        scene.studio_palette_gradient_index = (
            len(
                scene.studio_palette_gradient_items
            ) - 1
        )

        return {'FINISHED'}


class STUDIO_PALETTE_OT_update_gradient(
    bpy.types.Operator
):

    bl_idname = (
        "sparkshow_studio.palette_update_gradient"
    )

    bl_label = (
        "Mettre à jour"
    )

    def execute(
        self,
        context
    ):

        scene = context.scene

        index = (
            scene.studio_palette_gradient_index
        )

        if (
            0 <= index <
            len(
                scene.studio_palette_gradient_items
            )
        ):

            node = ensure_ramp_node()

            sync_ramp_to_preset(
                node,
                scene.studio_palette_gradient_items[
                    index
                ]
            )

        return {'FINISHED'}


class STUDIO_PALETTE_OT_remove_gradient(
    bpy.types.Operator
):

    bl_idname = (
        "sparkshow_studio.palette_remove_gradient"
    )

    bl_label = "Supprimer"

    def execute(
        self,
        context
    ):

        scene = context.scene

        index = (
            scene.studio_palette_gradient_index
        )

        items = (
            scene.studio_palette_gradient_items
        )

        if (
            0 <= index <
            len(items)
        ):

            items.remove(
                index
            )

            scene.studio_palette_gradient_index = (
                max(
                    0,
                    min(
                        index - 1,
                        len(items) - 1
                    )
                )
            )

        return {'FINISHED'}


# ============================================================
# CLEAR ANIMATION
# ============================================================


def clear_drone_animation(obj):
    """Remove only RGBW color animation, preserving movement/Fire/RTL."""
    if obj is None:
        return False
    removed = False
    if _is_shared_object_color_backend(obj):
        try:
            action = obj.animation_data.action if obj.animation_data else None
            if action:
                for fc in list(action.fcurves):
                    if fc.data_path == "color":
                        action.fcurves.remove(fc)
                        removed = True
        except Exception:
            pass
        return removed
    for socket in get_sockets_for_drone(obj):
        try:
            node_tree = socket.id_data
            action = node_tree.animation_data.action if node_tree.animation_data else None
            if action is None:
                continue
            path = socket.path_from_id("default_value")
            for fc in list(action.fcurves):
                if fc.data_path == path:
                    action.fcurves.remove(fc)
                    removed = True
        except Exception:
            pass
    return removed



# ============================================================
# INTERPOLATION
# ============================================================


def apply_interpolation_to_drone(obj, start_frame, end_frame, interpolation):
    mode = 'CONSTANT' if interpolation == 'CONSTANT' else ('BEZIER' if interpolation == 'BEZIER' else 'LINEAR')
    if _is_shared_object_color_backend(obj):
        try:
            action = obj.animation_data.action if obj.animation_data else None
            if not action:
                return
            fcurves = [fc for fc in action.fcurves if fc.data_path == "color"]
        except Exception:
            return
    else:
        fcurves = []
        for socket in get_sockets_for_drone(obj):
            fcurves.extend(_socket_fcurves(socket))
    for fcurve in fcurves:
        for key in fcurve.keyframe_points:
            frame = float(key.co.x)
            if start_frame - 0.01 <= frame <= end_frame + 0.01:
                key.interpolation = mode
                if mode == 'BEZIER':
                    key.handle_left_type = 'AUTO'
                    key.handle_right_type = 'AUTO'


# ============================================================
# FAST BAKE HELPERS
# ============================================================


def _ensure_action(owner, action_name):
    """Return an Action for an animatable Blender ID datablock."""
    try:
        if owner.animation_data is None:
            owner.animation_data_create()
        action = owner.animation_data.action
        if action is None:
            action = bpy.data.actions.new(action_name)
            owner.animation_data.action = action
        return action
    except Exception:
        return None


def _find_or_create_fcurve(action, data_path, array_index):
    """Find one F-curve without repeatedly scanning the Action when possible."""
    if action is None:
        return None
    for fc in action.fcurves:
        if fc.data_path == data_path and fc.array_index == array_index:
            return fc
    try:
        return action.fcurves.new(data_path=data_path, index=array_index)
    except Exception:
        return None


def _remove_fcurve_keys_in_range(fcurve, start_frame, end_frame):
    """Remove only existing keys in the bake interval, preserving keys outside it."""
    if fcurve is None:
        return
    try:
        points = fcurve.keyframe_points
        for index in range(len(points) - 1, -1, -1):
            frame = float(points[index].co.x)
            if start_frame - 0.001 <= frame <= end_frame + 0.001:
                points.remove(points[index])
    except Exception:
        pass


def _prepare_color_fcurves(obj, start_frame, end_frame, cache=None):
    """Prepare reusable RGBW F-curves for a bake.

    The old implementation called socket.keyframe_insert()/object.keyframe_insert()
    for every drone on every frame. This helper creates the four channels once and
    lets the baker fill keyframe points in memory, then updates each F-curve once.
    """
    if obj is None:
        return []

    if cache is None:
        cache = {}

    writers = []

    if _is_shared_object_color_backend(obj):
        owner = obj
        action = _ensure_action(owner, f"{obj.name} Lighting")
        if action is None:
            return []
        curves = []
        for index in range(4):
            fc = _find_or_create_fcurve(action, "color", index)
            if fc is not None:
                _remove_fcurve_keys_in_range(fc, start_frame, end_frame)
                curves.append(fc)
        if len(curves) == 4:
            writers.append(curves)
        return writers

    seen = set()
    for socket in get_sockets_for_drone(obj):
        try:
            owner = socket.id_data
            action = _ensure_action(owner, f"{owner.name} Lighting")
            if action is None:
                continue
            path = socket.path_from_id("default_value")
            key = (owner.as_pointer(), path)
            if key in seen:
                continue
            seen.add(key)
            curves = []
            for index in range(4):
                fc = _find_or_create_fcurve(action, path, index)
                if fc is not None:
                    _remove_fcurve_keys_in_range(fc, start_frame, end_frame)
                    curves.append(fc)
            if len(curves) == 4:
                writers.append(curves)
        except Exception:
            continue

    return writers


def _batch_add_color_key(writers, frame, color, key_type='JITTER'):
    """Append one RGBW key to all prepared writers."""
    values = tuple(float(clamp(v)) for v in color[:4])
    for curves in writers:
        for index, fc in enumerate(curves):
            try:
                points = fc.keyframe_points
                insert_index = len(points)
                points.add(1)
                point = points[insert_index]
                point.co = (float(frame), values[index])
                point.type = key_type
            except Exception:
                pass


def _finalize_color_fcurves(writers):
    """Update all prepared curves exactly once after a bake."""
    seen = set()
    for curves in writers:
        for fc in curves:
            try:
                pointer = fc.as_pointer()
            except Exception:
                pointer = id(fc)
            if pointer in seen:
                continue
            seen.add(pointer)
            try:
                fc.keyframe_points.sort()
                fc.keyframe_points.deduplicate()
                fc.update()
            except Exception:
                pass


def _prepare_all_bake_writers(selected_objects, start_frame, end_frame):
    writers = {}
    for obj in selected_objects:
        writers[get_drone_name(obj)] = _prepare_color_fcurves(
            obj, start_frame, end_frame
        )
    return writers


# ============================================================
# BAKE 2 KEYS
# ============================================================


def _compute_bake_window_color(
    obj,
    scene,
    spatial_factor,
    frame,
    target_objects,
    window_start,
    window_end
):
    """Evaluate the lighting effect against a per-drone temporal window."""
    if scene.studio_palette_mode == 'SOLID':
        return _compute_effect_color_base(
            obj,
            scene,
            spatial_factor,
            frame,
            target_objects,
            effect_start_frame=window_start,
            effect_duration=max(1, window_end - window_start + 1),
        )

    color = _compute_effect_color_base(
        obj,
        scene,
        spatial_factor,
        frame,
        target_objects,
        effect_start_frame=window_start,
        effect_duration=max(1, window_end - window_start + 1),
    )

    return _apply_gradient_effect_fade(
        color,
        scene,
        frame,
        window_start,
        window_end,
    )


def _get_active_gradient_marker_positions(scene):
    """Return sorted intermediate marker positions from the active gradient."""
    try:
        index = int(scene.studio_palette_gradient_index)
        items = scene.studio_palette_gradient_items
        if 0 <= index < len(items):
            stops = sorted(
                list(items[index].stops),
                key=lambda stop: float(stop.position),
            )
            if len(stops) > 2:
                return [
                    clamp(float(stop.position))
                    for stop in stops[1:-1]
                ]
    except Exception:
        pass

    # Fallback to the live ColorRamp used by the effect engine.
    try:
        node = get_ramp_node()
        if node and hasattr(node, 'color_ramp'):
            elements = sorted(
                list(node.color_ramp.elements),
                key=lambda element: float(element.position),
            )
            if len(elements) > 2:
                return [
                    clamp(float(element.position))
                    for element in elements[1:-1]
                ]
    except Exception:
        pass

    return []


def _marker_event_progresses(spatial_factor, marker_positions, cycles):
    """Return normalized progress values for marker crossings over all cycles."""
    total_cycles = max(0.0, float(cycles))
    if total_cycles <= 0.0 or not marker_positions:
        return []

    events = []
    # For travelling gradients (WAVE/ROTARY), the ramp phase is:
    #     phase = spatial_factor + progress * cycles
    # A marker is crossed whenever this phase reaches marker + integer_cycle.
    for marker in marker_positions:
        base = (float(marker) - float(spatial_factor)) % 1.0
        k = 0
        while True:
            phase = base + k
            if phase > total_cycles + 1e-9:
                break
            progress = phase / total_cycles
            if 0.0 < progress < 1.0:
                events.append((progress, marker))
            k += 1
            if k > 10000:
                break

    events.sort(key=lambda item: item[0])
    return events


def _cycle_boundary_progresses(cycles):
    """Return normalized progress at each integer cycle boundary (excluding 0/1)."""
    total_cycles = max(1.0, float(cycles))
    boundaries = []
    cycle_index = 1
    while cycle_index < total_cycles - 1e-9:
        boundaries.append(cycle_index / total_cycles)
        cycle_index += 1
    return boundaries


def _get_gradient_stop_positions(scene):
    """Return all normalized stop positions of the active gradient, endpoints included."""
    try:
        index = int(scene.studio_palette_gradient_index)
        items = scene.studio_palette_gradient_items
        if 0 <= index < len(items):
            stops = sorted(list(items[index].stops), key=lambda stop: float(stop.position))
            if len(stops) >= 2:
                return [clamp(float(stop.position)) for stop in stops]
    except Exception:
        pass

    try:
        node = get_ramp_node()
        if node and hasattr(node, 'color_ramp'):
            elements = sorted(list(node.color_ramp.elements), key=lambda e: float(e.position))
            if len(elements) >= 2:
                return [clamp(float(e.position)) for e in elements]
    except Exception:
        pass

    return [0.0, 1.0]


def _inverse_smoothstep(y, iterations=32):
    """Numerically invert smoothstep(x) on [0, 1]."""
    target = clamp(float(y))
    lo = 0.0
    hi = 1.0
    for _ in range(max(8, int(iterations))):
        mid = (lo + hi) * 0.5
        value = mid * mid * (3.0 - 2.0 * mid)
        if value < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) * 0.5


def _progresses_for_periodic_crossings(
    phase_offset,
    frequency,
    theta_values,
):
    """Return normalized progress values for periodic phase crossings."""
    frequency = max(1e-9, float(frequency))
    phase_offset = float(phase_offset)
    start_theta = phase_offset
    end_theta = phase_offset + (2.0 * math.pi * frequency)
    k_min = int(math.floor((start_theta - 2.0 * math.pi) / (2.0 * math.pi)))
    k_max = int(math.ceil((end_theta + 2.0 * math.pi) / (2.0 * math.pi)))

    progresses = []
    for theta_base in theta_values:
        for k in range(k_min, k_max + 1):
            theta = float(theta_base) + (2.0 * math.pi * k)
            progress = (theta - phase_offset) / (2.0 * math.pi * frequency)
            if 0.0 < progress < 1.0:
                progresses.append(progress)
    return progresses


def _two_key_effect_key_progresses(
    effect,
    spatial_factor,
    cycles,
    speed,
    stop_positions,
    pulse_min_intensity=0.20,
):
    """Generate compact key positions that follow the actual preview effect.

    The previous implementation treated every temporal effect as though its
    phase moved linearly through the gradient. That is not true for Pulsation
    (sinusoidal) or Scanner/KITT (triangle-wave), which caused baked colors to
    disagree with the preview. This function creates only the important
    crossings/extrema while keeping the bake compact.
    """
    cycles = max(1.0, float(cycles))
    speed = max(0.01, float(speed))
    markers = list(stop_positions[1:-1]) if len(stop_positions) > 2 else []
    events = [(0, 'start', 0.0), (0, 'end', 1.0)]

    if effect in {'WAVE', 'ROTARY'}:
        # Preview phase = spatial_factor + progress * cycles.
        for progress, marker in _marker_event_progresses(
            spatial_factor,
            markers,
            cycles,
        ):
            events.append((int(math.floor(progress * cycles + 1e-9)), 'marker', progress))

        for boundary in _cycle_boundary_progresses(cycles):
            events.append((int(math.floor(boundary * cycles + 1e-9)), 'boundary', boundary))

        return events

    if effect == 'PULSE':
        # Preview phase = progress * cycles * speed * 2pi + spatial_factor*pi.
        frequency = cycles * speed
        phase = float(spatial_factor) * math.pi
        min_intensity = clamp(float(pulse_min_intensity))

        # Add actual pulse extrema so even a two-color gradient can reproduce
        # repeated pulsations instead of becoming a single long interpolation.
        extrema = _progresses_for_periodic_crossings(
            phase,
            frequency,
            (
                math.pi / 2.0,
                3.0 * math.pi / 2.0,
            ),
        )
        for progress in extrema:
            events.append((int(math.floor(progress * frequency + 1e-9)), 'extrema', progress))

        # Intermediate gradient markers are crossed on both the rising and
        # falling half of each pulse. Convert the marker through the same
        # smoothstep + intensity floor used by the preview before solving.
        if min_intensity < 1.0 and markers:
            for marker in markers:
                marker = clamp(float(marker))
                normalized = clamp(
                    (marker - min_intensity) /
                    max(1e-9, 1.0 - min_intensity)
                )
                x = _inverse_smoothstep(normalized)
                sine_value = clamp(2.0 * x - 1.0, -1.0, 1.0)
                angle = math.asin(sine_value)
                theta_values = (
                    angle,
                    math.pi - angle,
                )
                for progress in _progresses_for_periodic_crossings(
                    phase,
                    frequency,
                    theta_values,
                ):
                    events.append((int(math.floor(progress * frequency + 1e-9)), 'marker', progress))

        # Explicit period boundaries make the number of requested cycles clear
        # in the timeline, while extrema/marker keys provide the color motion.
        whole = int(math.floor(frequency + 1e-9))
        for cycle_index in range(1, whole + 1):
            progress = cycle_index / frequency
            if 0.0 < progress < 1.0:
                events.append((cycle_index, 'boundary', progress))

        return events

    if effect in {'SCANNER', 'KITT'}:
        # Triangle wave: 0 -> 1 -> 0 for each temporal cycle.
        for cycle_index in range(int(math.floor(cycles)) + 1):
            base = 2.0 * cycle_index
            for marker in markers:
                m = clamp(float(marker))
                for u in (base + m, base + 2.0 - m):
                    progress = u / cycles
                    if 0.0 < progress < 1.0:
                        events.append((cycle_index, 'marker', progress))

        return events

    # Static/spatial-only or effects whose temporal law is not represented by
    # compact marker crossings keep just their endpoints. This preserves the
    # original compactness rather than inventing misleading keys.
    return events


def _two_key_cycle_key_progresses(cycles, stop_positions):
    """Backward-compatible wrapper for callers outside the 2-key baker."""
    return _two_key_effect_key_progresses(
        'WAVE',
        0.0,
        cycles,
        1.0,
        stop_positions,
    )

def bake_two_keyframes(
    context,
    selected_objects,
    start_frame,
    end_frame
):
    """Compact Lighting bake with exact cycle timing and bounded keyframes.

    The bake uses the requested effect duration for every drone, with a
    spatial temporal stagger. Each drone gets its own shifted local window,
    but the shift is clamped to Blender's render range so no keyframe can
    escape the visible/rendered interval.

    Key count per complete cycle:
      - 2-stop gradient: start + end = 2 keys;
      - N-stop gradient: start + N-2 intermediate markers + end = N keys.
    Additional cycles repeat that same key pattern. At a cycle boundary, the
    previous cycle's end is written one frame before the next cycle's start so
    Blender does not deduplicate the two colors into a single key.
    """
    scene = context.scene
    if not selected_objects:
        return

    scene.frame_set(start_frame)
    spatial_cache = compute_spatial_factors(scene, selected_objects)
    factors = [
        get_spatial_factor(
            obj,
            spatial_cache,
            scene.studio_palette_grad_invert_direction,
            scene.studio_palette_grad_axis,
        )
        for obj in selected_objects
    ]

    for obj in selected_objects:
        _ensure_object_color_material(obj)

    # Writers must cover the complete bounded staggered interval, not merely
    # the original bake interval, otherwise later-shifted keys are written into
    # incomplete/foreign ranges.
    stop_positions = _get_gradient_stop_positions(scene)
    cycles = max(1.0, float(getattr(scene, 'studio_palette_grad_anim_cycles', 1.0)))
    speed = max(0.01, float(getattr(scene, 'studio_palette_grad_anim_speed', 1.0)))
    effect = getattr(scene, 'studio_palette_grad_anim_type', 'STATIC')
    pulse_min = max(
        0.0,
        min(1.0, float(getattr(
            scene, 'studio_palette_grad_pulse_min_intensity', 0.20
        )))
    )
    total_span = max(1, int(end_frame - start_frame))

    # Re-enable the spatial temporal stagger, but keep every drone entirely
    # inside Blender's render range. Each drone keeps the same effect duration;
    # only its start/end window is shifted according to the spatial factor.
    # The requested stagger is expressed as a multiple of the bake duration,
    # then clamped to the actual free space after the bake interval.
    try:
        render_start = int(scene.frame_start)
        render_end = int(scene.frame_end)
    except Exception:
        render_start = start_frame
        render_end = end_frame

    render_lo = max(render_start, start_frame)
    render_hi = max(render_lo, render_end)
    requested_shift = int(round(
        total_span * max(0.0, float(getattr(
            scene, 'studio_palette_grad_two_key_offset', 1.0
        )))
    ))
    free_shift = max(0, render_hi - end_frame)
    max_shift = min(requested_shift, free_shift)
    max_bake_end = end_frame + max_shift
    writers = _prepare_all_bake_writers(
        selected_objects,
        start_frame,
        max_bake_end,
    )

    for obj, factor in zip(selected_objects, factors):
        local_shift = int(round(clamp(float(factor)) * max_shift))
        local_start = start_frame + local_shift
        local_end = end_frame + local_shift
        writer = writers.get(get_drone_name(obj), [])
        if not writer:
            continue

        used_frames = set()
        events = _two_key_effect_key_progresses(
            effect,
            factor,
            cycles,
            speed,
            stop_positions,
            pulse_min_intensity=pulse_min,
        )

        ordered = []
        for cycle_index, kind, progress in events:
            raw_frame = local_start + clamp(float(progress)) * total_span
            frame = int(round(raw_frame))

            # Represent the wrap between two cycles explicitly. If the previous
            # cycle ended at the same rounded frame as the next cycle start,
            # move the previous-cycle end back by one frame.
            final_cycle_index = max((event[0] for event in events), default=0)
            if kind == 'end' and cycle_index < final_cycle_index:
                boundary = int(round(raw_frame))
                frame = boundary - 1
            elif kind == 'start' and cycle_index > 0:
                frame = int(round(raw_frame))

            frame = max(local_start, min(local_end, frame))
            if frame in used_frames:
                continue
            used_frames.add(frame)
            ordered.append((frame, kind, progress))

        # Preserve each drone's own shifted endpoints.
        if local_start not in used_frames:
            ordered.append((local_start, 'start', 0.0))
            used_frames.add(local_start)
        if local_end not in used_frames:
            ordered.append((local_end, 'end', 1.0))
            used_frames.add(local_end)

        ordered.sort(key=lambda item: item[0])

        for frame, _kind, _progress in ordered:
            color = _compute_bake_window_color(
                obj,
                scene,
                factor,
                frame,
                selected_objects,
                local_start,
                local_end,
            )
            _batch_add_color_key(writer, frame, color)

        apply_interpolation_to_drone(
            obj,
            local_start,
            local_end,
            scene.studio_palette_grad_interp_type,
        )

    _finalize_color_fcurves(
        [w for ws in writers.values() for w in ws]
    )


# ============================================================
# BAKE FRAME BY FRAME
# ============================================================


def bake_frame_by_frame(
    context,
    selected_objects,
    start_frame,
    end_frame,
    adaptive=False
):
    """High-performance bake using cached factors and batched F-curve writes."""
    scene = context.scene
    if not selected_objects:
        return

    spatial_cache = compute_spatial_factors(scene, selected_objects)
    factors = [
        get_spatial_factor(
            obj,
            spatial_cache,
            scene.studio_palette_grad_invert_direction,
            scene.studio_palette_grad_axis,
        )
        for obj in selected_objects
    ]

    names = [get_drone_name(obj) for obj in selected_objects]
    total = len(selected_objects)

    for obj in selected_objects:
        _ensure_object_color_material(obj)

    writers = _prepare_all_bake_writers(
        selected_objects,
        start_frame,
        end_frame,
    )

    threshold = float(scene.studio_palette_bake_threshold)
    previous_colors = [None] * total

    total_frames = end_frame - start_frame + 1
    progress_step = max(1, total_frames // 20)

    # IMPORTANT: do not call scene.frame_set() for every frame. The spatial factors
    # are already cached and the effect engine is explicitly evaluated at `frame`.
    for frame_index, frame in enumerate(range(start_frame, end_frame + 1)):
        for index, (obj, factor, name) in enumerate(
            zip(selected_objects, factors, names)
        ):
            color = compute_effect_color(
                obj,
                scene,
                factor,
                frame,
                selected_objects,
            )

            should_keyframe = True
            previous = previous_colors[index]

            if adaptive and previous is not None:
                should_keyframe = (
                    color_distance(color, previous) >= threshold
                )
                if frame == end_frame:
                    should_keyframe = True

            if should_keyframe:
                _batch_add_color_key(
                    writers.get(name, []),
                    frame,
                    color,
                )
                previous_colors[index] = color.copy()

        if frame_index % progress_step == 0 or frame == end_frame:
            context.window_manager.progress_update(
                frame_index / max(1, total_frames - 1)
            )

    _finalize_color_fcurves(
        [w for ws in writers.values() for w in ws]
    )

    context.window_manager.progress_end()

# ============================================================
# BAKE OPERATOR
# ============================================================

class STUDIO_PALETTE_OT_bake_keyframes(
    bpy.types.Operator
):

    bl_idname = (
        "sparkshow_studio.palette_bake_keyframes"
    )

    bl_label = (
        "Appliquer animation"
    )

    bl_options = {
        'REGISTER',
        'UNDO'
    }

    def execute(
        self,
        context
    ):
        global LIVE_PREVIEW_BAKING

        scene = context.scene
        previous_baking_state = LIVE_PREVIEW_BAKING
        LIVE_PREVIEW_BAKING = True

        selected_objects = (
            get_drone_cache(
                scene
            )
        )

        if not selected_objects:

            self.report(
                {'WARNING'},
                (
                    "Aucun drone détecté. "
                    "Sélectionne un ou plusieurs "
                    "objets Drone."
                )
            )

            LIVE_PREVIEW_BAKING = previous_baking_state
            return {'CANCELLED'}

        # ====================================================
        # MODE UNI
        # ====================================================

        if (
            scene.studio_palette_mode
            ==
            'SOLID'
        ):

            start = (
                scene.frame_current
                if
                scene.studio_palette_solid_use_active_frame
                else
                scene.studio_palette_solid_start_frame
            )

            duration = max(
                1,
                scene.studio_palette_solid_duration
            )

            end = (
                start +
                duration -
                1
            )

            color = (
                get_solid_color(
                    scene
                )
            )

            for obj in selected_objects:

                scene.frame_set(
                    start
                )

                set_drone_color(
                    obj,
                    color
                )

                keyframe_drone_color(
                    obj,
                    start
                )

                scene.frame_set(
                    end
                )

                set_drone_color(
                    obj,
                    color
                )

                keyframe_drone_color(
                    obj,
                    end
                )

                apply_interpolation_to_drone(
                    obj,
                    start,
                    end,
                    scene.studio_palette_solid_interp_type
                )

            scene.frame_set(
                start
            )

            self.report(
                {'INFO'},
                (
                    f"{len(selected_objects)} "
                    f"drones : transition "
                    f"{start} → {end}"
                )
            )

            LIVE_PREVIEW_BAKING = previous_baking_state
            return {'FINISHED'}

        # ====================================================
        # GRADIENT
        # ====================================================

        start = (
            scene.frame_current
            if
            scene.studio_palette_grad_use_active_frame
            else
            scene.studio_palette_grad_start_frame
        )

        duration = max(
            1,
            scene.studio_palette_grad_duration
        )

        end = (
            start +
            duration -
            1
        )

        bake_mode = (
            scene.studio_palette_bake_mode
        )

        # ----------------------------------------------------
        # 2 KEYFRAMES
        # ----------------------------------------------------
        # Strict compact mode: always create only the two temporal endpoints
        # for every drone. Even animated effects and fades are reduced to their
        # start/end states so the result stays lightweight and editable.

        try:

            if bake_mode == 'TWO_KEYS':

                bake_two_keyframes(
                    context,
                    selected_objects,
                    start,
                    end
                )

            elif bake_mode == 'FRAME':

                context.window_manager.progress_begin(
                    0.0,
                    1.0
                )

                bake_frame_by_frame(
                    context,
                    selected_objects,
                    start,
                    end,
                    adaptive=False
                )

            else:

                context.window_manager.progress_begin(
                    0.0,
                    1.0
                )

                bake_frame_by_frame(
                    context,
                    selected_objects,
                    start,
                    end,
                    adaptive=True
                )

        except Exception as e:

            try:

                context.window_manager.progress_end()

            except Exception:
                pass

            self.report(
                {'ERROR'},
                f"Erreur Bake : {e}"
            )

            LIVE_PREVIEW_BAKING = previous_baking_state
            return {'CANCELLED'}

        scene.frame_set(
            start
        )

        self.report(
            {'INFO'},
            (
                f"Animation créée sur "
                f"{len(selected_objects)} drones : "
                f"{start} → {end}"
            )
        )

        return {'FINISHED'}


# ============================================================
# CLEAR ANIMATION
# ============================================================

class STUDIO_PALETTE_OT_clear_animation(
    bpy.types.Operator
):

    bl_idname = (
        "sparkshow_studio.palette_clear_animation"
    )

    bl_label = (
        "Effacer animation couleur"
    )

    bl_options = {
        'REGISTER',
        'UNDO'
    }

    def execute(
        self,
        context
    ):

        selected = (
            get_drone_cache(
                context.scene
            )
        )

        count = 0

        for obj in selected:

            if clear_drone_animation(
                obj
            ):

                count += 1

        self.report(
            {'INFO'},
            (
                f"Animations supprimées : "
                f"{count}"
            )
        )

        return {'FINISHED'}


# ============================================================
# REFRESH CACHE
# ============================================================

class STUDIO_PALETTE_OT_refresh_cache(
    bpy.types.Operator
):

    bl_idname = (
        "sparkshow_studio.palette_refresh_cache"
    )

    bl_label = (
        "Actualiser drones"
    )

    def execute(
        self,
        context
    ):

        invalidate_cache()

        build_drone_cache(
            context.scene
        )

        count = len(
            DRONE_CACHE[
                "objects"
            ]
        )

        emissions = (
            DRONE_CACHE[
                "detected_emission_objects"
            ]
        )

        self.report(
            {'INFO'},
            (
                f"{count} drones détectés "
                f"/ {emissions} émissions RGBW"
            )
        )

        return {'FINISHED'}


# ============================================================
# SELECT DETECTED DRONES
# ============================================================

class STUDIO_PALETTE_OT_select_drones(
    bpy.types.Operator
):

    bl_idname = (
        "sparkshow_studio.palette_select_drones"
    )

    bl_label = (
        "Sélectionner les drones"
    )

    def execute(
        self,
        context
    ):

        scene = context.scene

        drones = get_drone_cache(
            scene
        )

        if not drones:

            self.report(
                {'WARNING'},
                "Aucun drone détecté."
            )

            return {'CANCELLED'}

        bpy.ops.object.select_all(
            action='DESELECT'
        )

        count = 0

        for obj in drones:

            try:

                obj.select_set(
                    True
                )

                count += 1

            except Exception:
                pass

        if drones:

            try:

                context.view_layer.objects.active = (
                    drones[0]
                )

            except Exception:
                pass

        self.report(
            {'INFO'},
            f"{count} drones sélectionnés."
        )

        return {'FINISHED'}


# ============================================================
# DIAGNOSTIC
# ============================================================

class STUDIO_PALETTE_OT_diagnostic(
    bpy.types.Operator
):

    bl_idname = (
        "sparkshow_studio.palette_diagnostic"
    )

    bl_label = (
        "Diagnostic"
    )

    def execute(
        self,
        context
    ):

        scene = context.scene

        drones = get_drone_cache(
            scene
        )

        print("")
        print("=" * 70)
        print(
            "DRONE LIGHT SHOW PALETTE V5"
        )
        print("=" * 70)

        print(
            "Mode détection :",
            scene.studio_palette_drone_detection_mode
        )

        print(
            "Objets sélectionnés :",
            len(
                bpy.context.selected_objects
            )
        )

        print(
            "Meshes inspectés :",
            DRONE_CACHE[
                "detected_mesh_objects"
            ]
        )

        print(
            "Objets / composants avec émission :",
            DRONE_CACHE[
                "detected_emission_objects"
            ]
        )

        print(
            "Drones détectés :",
            len(drones)
        )

        print("-" * 70)

        for diagnostic in (
            DRONE_CACHE[
                "diagnostics"
            ]
        ):

            print(
                f"DRONE : "
                f"{diagnostic['drone']}"
            )

            print(
                f"  ROOT : "
                f"{diagnostic['root']}"
            )

            print(
                f"  LED/SOCKETS : "
                f"{diagnostic['led_count']}"
            )

            print(
                f"  OBJETS EMISSION : "
                f"{', '.join(diagnostic['emission_objects'])}"
            )

            print("-" * 70)

        print("=" * 70)
        print("")

        self.report(
            {'INFO'},
            (
                f"Diagnostic : "
                f"{len(drones)} drones / "
                f"{DRONE_CACHE['detected_emission_objects']} "
                f"émissions"
            )
        )

        return {'FINISHED'}


# ============================================================
# PANEL
# ============================================================

class STUDIO_PALETTE_PT_main_panel(
    bpy.types.Panel
):

    bl_label = (
        "Lighting"
    )

    bl_idname = (
        "STUDIO_PALETTE_PT_main_panel"
    )

    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'sparkshow'

    def draw(
        self,
        context
    ):

        layout = self.layout

        scene = context.scene

        # IMPORTANT :
        # Reconstruit automatiquement le cache lorsque
        # la sélection change.

        drones = get_drone_cache(
            scene
        )

        # ====================================================
        # DETECTION
        # ====================================================

        detection = layout.box()

        detection.label(
            text="Détection des drones",
            icon='OUTLINER_OB_ARMATURE'
        )

        detection.prop(
            scene,
            "studio_palette_drone_detection_mode",
            text="Mode"
        )

        if (
            scene.studio_palette_drone_detection_mode
            ==
            'SELECTED'
        ):

            detection.label(
                text=(
                    "Sélectionne le(s) "
                    "objet(s) Drone"
                ),
                icon='INFO'
            )

            detection.label(
                text=(
                    "Recherche RGBW dans "
                    "toute la hiérarchie"
                ),
                icon='VIEWZOOM'
            )

        if (
            scene.studio_palette_drone_detection_mode
            ==
            'COLLECTION'
        ):

            detection.prop_search(
                scene,
                "studio_palette_drone_collection_name",
                bpy.data,
                "collections",
                text="Collection"
            )

        row = detection.row(
            align=True
        )

        row.operator(
            "sparkshow_studio.palette_refresh_cache",
            icon='FILE_REFRESH',
            text="Actualiser"
        )

        row.operator(
            "sparkshow_studio.palette_select_drones",
            icon='RESTRICT_SELECT_OFF',
            text="Sélectionner"
        )

        detection.operator(
            "sparkshow_studio.palette_diagnostic",
            icon='CONSOLE',
            text="Diagnostic"
        )

        # ----------------------------------------------------
        # COMPTEUR
        # ----------------------------------------------------

        count_row = detection.row()

        count_row.scale_y = 1.4

        count_row.label(
            text=(
                f"Drones détectés : "
                f"{len(drones)}"
            ),
            icon='DRIVER'
        )

        detection.label(
            text=(
                f"Émissions RGBW trouvées : "
                f"{DRONE_CACHE['detected_emission_objects']}"
            ),
            icon='LIGHT'
        )

        # ----------------------------------------------------
        # DÉTAIL SÉLECTION
        # ----------------------------------------------------

        if (
            scene.studio_palette_drone_detection_mode
            ==
            'SELECTED'
            and
            len(
                bpy.context.selected_objects
            ) > 0
        ):

            selected_names = [
                obj.name
                for obj in
                bpy.context.selected_objects
            ]

            detection.label(
                text=(
                    "Sélection : "
                    +
                    ", ".join(
                        selected_names[:3]
                    )
                ),
                icon='RESTRICT_SELECT_OFF'
            )

            if len(
                selected_names
            ) > 3:

                detection.label(
                    text=(
                        f"+ "
                        f"{len(selected_names) - 3} "
                        f"autres..."
                    )
                )

        # ----------------------------------------------------
        # AVERTISSEMENT SI ZERO
        # ----------------------------------------------------

        if not drones:

            warning = detection.row()

            warning.alert = True

            if (
                scene.studio_palette_drone_detection_mode
                ==
                'SELECTED'
            ):

                warning.label(
                    text=(
                        "Aucun drone détecté "
                        "dans la sélection"
                    ),
                    icon='ERROR'
                )

            else:

                warning.label(
                    text=(
                        "Aucun drone détecté"
                    ),
                    icon='ERROR'
                )

        # ====================================================
        # MODE
        # ====================================================

        preview = layout.box()
        preview.label(text="Prévisualisation Lighting", icon='HIDE_OFF')
        preview.prop(scene, "studio_palette_live_preview", text="Preview")
        preview.prop(scene, "studio_palette_show_outlines", text="Contours")
        preview.label(text="Un seul Preview pour UNI et DÉGRADÉ", icon='INFO')

        intensity = preview.row(align=True)
        intensity.prop(
            get_lightshow(scene),
            "emission_strength",
            text="Intensité simulation",
            slider=True,
        )
        intensity.label(text="(viewport / rendu Blender uniquement)", icon='RENDER_RESULT')

        layout.prop(
            scene,
            "studio_palette_mode",
            expand=True
        )

        # ====================================================
        # GRADIENT
        # ====================================================

        if (
            scene.studio_palette_mode
            ==
            'GRADIENT'
        ):

            box = layout.box()

            box.label(
                text="Catalogue de dégradés",
                icon='COLOR'
            )

            box.template_list(
                "STUDIO_PALETTE_UL_gradient_list",
                "",
                scene,
                "studio_palette_gradient_items",
                scene,
                "studio_palette_gradient_index",
                rows=6
            )

            preview_settings = box.row(align=True)
            preview_settings.prop(
                scene,
                "studio_palette_gradient_preview_size",
                text="Taille"
            )
            preview_settings.prop(
                scene,
                "studio_palette_gradient_preview_width",
                text="Largeur"
            )

            row = box.row(
                align=True
            )

            row.operator(
                "sparkshow_studio.palette_add_gradient",
                icon='ADD',
                text="Ajouter"
            )

            row.operator(
                "sparkshow_studio.palette_update_gradient",
                icon='FILE_TICK',
                text="Maj"
            )

            row.operator(
                "sparkshow_studio.palette_remove_gradient",
                icon='REMOVE',
                text=""
            )

            node = get_ramp_node()

            if node:

                box.template_color_ramp(
                    node,
                    "color_ramp",
                    expand=True
                )

            else:

                box.operator(
                    "sparkshow_studio.palette_init_nodes",
                    icon='NODE'
                )

            box.prop(
                scene,
                "studio_palette_grad_white",
                text="Blanc W"
            )

            # =================================================
            # SPATIAL
            # =================================================

            spatial = layout.box()

            spatial.label(
                text="Spatialisation",
                icon='ORIENTATION_GLOBAL'
            )

            spatial.prop(
                scene,
                "studio_palette_grad_axis",
                text="Mode"
            )

            if (
                scene.studio_palette_grad_axis
                in {
                    'OBJECT',
                    'CURVE',
                    'RADIAL',
                    'ANGULAR'
                }
            ):

                spatial.prop(
                    scene,
                    "studio_palette_grad_target",
                    text="Cible"
                )

            spatial.prop(
                scene,
                "studio_palette_grad_invert_direction",
                text="Inverser"
            )

            # =================================================
            # EFFECT
            # =================================================

            effect = layout.box()

            effect.label(
                text="Effet",
                icon='FORCE_TURBULENCE'
            )

            effect.prop(
                scene,
                "studio_palette_grad_anim_type",
                text=""
            )

            effect.prop(
                scene,
                "studio_palette_grad_duration",
                text="Durée"
            )

            effect.prop(
                scene,
                "studio_palette_grad_fade_in",
                text="Fondu entrée"
            )

            effect.prop(
                scene,
                "studio_palette_grad_fade_out",
                text="Fondu sortie"
            )

            if (
                scene.studio_palette_grad_fade_in > 0
                or scene.studio_palette_grad_fade_out > 0
                or scene.studio_palette_grad_anim_type == 'LINE_DRAW'
            ):

                effect.prop(
                    scene,
                    "studio_palette_grad_fade_curve",
                    text="Courbe fade"
                )

            if scene.studio_palette_grad_anim_type in {
                'CYCLE',
                'WAVE',
                'ROTARY',
                'SCANNER',
                'KITT',
                'METEOR',
                'PULSE',
                'HEARTBEAT'
            }:

                effect.prop(
                    scene,
                    "studio_palette_grad_anim_cycles",
                    text="Cycles"
                )

            if scene.studio_palette_grad_anim_type in {
                'STARS',
                'PULSE',
                'HEARTBEAT',
                'STROBE'
            }:

                effect.prop(
                    scene,
                    "studio_palette_grad_anim_speed",
                    text="Vitesse"
                )

            if scene.studio_palette_grad_anim_type == 'PULSE':

                effect.prop(
                    scene,
                    "studio_palette_grad_pulse_min_intensity",
                    text="Intensité min."
                )

            if scene.studio_palette_grad_anim_type in {
                'SCANNER',
                'KITT'
            }:

                effect.prop(
                    scene,
                    "studio_palette_grad_scan_width",
                    text="Largeur"
                )

            if (
                scene.studio_palette_grad_anim_type
                ==
                'METEOR'
            ):

                effect.prop(
                    scene,
                    "studio_palette_grad_tail_length",
                    text="Traînée"
                )

            if (
                scene.studio_palette_grad_anim_type
                ==
                'LINE_DRAW'
            ):

                effect.prop(
                    scene,
                    "studio_palette_grad_anim_delay",
                    text="Intervalle"
                )

                effect.prop(
                    scene,
                    "studio_palette_grad_fade_count",
                    text="Fade drones"
                )

                effect.prop(
                    scene,
                    "studio_palette_grad_fade_time",
                    text="Temps fade"
                )

            # =================================================
            # BAKE
            # =================================================

            bake = layout.box()

            bake.label(
                text="Bake / Animation",
                icon='KEY_HLT'
            )

            bake.prop(
                scene,
                "studio_palette_bake_mode",
                text="Mode"
            )

            if scene.studio_palette_mode == 'GRADIENT':
                bake.prop(
                    scene,
                    "studio_palette_grad_interp_type",
                    text="Interpolation"
                )

            bake.prop(
                scene,
                "studio_palette_grad_use_active_frame",
                text="Frame active"
            )

            if not scene.studio_palette_grad_use_active_frame:

                row = bake.row(
                    align=True
                )

                row.prop(
                    scene,
                    "studio_palette_grad_start_frame",
                    text="Début"
                )

                row.operator(
                    "sparkshow_studio.palette_set_active_frame",
                    text="",
                    icon='TIME'
                )

            fps = get_scene_fps(
                scene
            )

            duration_seconds = (
                scene.studio_palette_grad_duration /
                fps
                if fps > 0
                else 0
            )

            bake.label(
                text=(
                    f"{duration_seconds:.2f} s "
                    f"({fps:.1f} FPS)"
                ),
                icon='INFO'
            )

            if (
                scene.studio_palette_bake_mode
                ==
                'ADAPTIVE'
            ):

                bake.prop(
                    scene,
                    "studio_palette_bake_threshold",
                    text="Seuil"
                )

            row = bake.row()

            row.scale_y = 1.5

            row.operator(
                "sparkshow_studio.palette_bake_keyframes",
                text="APPLIQUER / BAKE",
                icon='REC'
            )

            bake.operator(
                "sparkshow_studio.palette_clear_animation",
                text="Effacer animation",
                icon='X'
            )

        # ====================================================
        # SOLID
        # ====================================================

        else:

            box = layout.box()

            box.label(
                text="Couleurs unies",
                icon='COLOR'
            )

            box.template_list(
                "STUDIO_PALETTE_UL_color_list",
                "",
                scene,
                "studio_palette_color_items",
                scene,
                "studio_palette_color_index",
                rows=4
            )

            box.operator(
                "sparkshow_studio.palette_add_color",
                icon='ADD'
            )

            box.prop(
                scene,
                "studio_palette_solid_duration",
                text="Durée"
            )

            box.prop(
                scene,
                "studio_palette_solid_use_active_frame",
                text="Frame active"
            )

            box.prop(
                scene,
                "studio_palette_solid_interp_type",
                text="Interpolation"
            )

            row = box.row()

            row.scale_y = 1.5

            row.operator(
                "sparkshow_studio.palette_bake_keyframes",
                text="APPLIQUER COULEUR",
                icon='REC'
            )

        # ====================================================
        # INFO
        # ====================================================

        info = layout.box()

        info.label(
            text=(
                f"🛸 Drones détectés : "
                f"{len(drones)}"
            )
        )

        info.label(
            text=(
                f"💡 Émissions détectées : "
                f"{DRONE_CACHE['detected_emission_objects']}"
            )
        )


# ============================================================
# CLASSES
# ============================================================

classes = (

    STUDIO_GradientStopItem,
    STUDIO_GradientPresetItem,
    STUDIO_ColorItem,

    STUDIO_PALETTE_UL_color_list,
    STUDIO_PALETTE_UL_gradient_list,

    STUDIO_PALETTE_OT_init_nodes,
    STUDIO_PALETTE_OT_set_active_frame,

    STUDIO_PALETTE_OT_add_color,
    STUDIO_PALETTE_OT_add_gradient,
    STUDIO_PALETTE_OT_update_gradient,
    STUDIO_PALETTE_OT_remove_gradient,

    STUDIO_PALETTE_OT_refresh_cache,
    STUDIO_PALETTE_OT_select_drones,
    STUDIO_PALETTE_OT_diagnostic,

    STUDIO_PALETTE_OT_clear_animation,
    STUDIO_PALETTE_OT_bake_keyframes,

    STUDIO_PALETTE_PT_main_panel,
)


# ============================================================
# PROPERTIES
# ============================================================

def register_properties():

    # ========================================================
    # DETECTION
    # ========================================================

    bpy.types.Scene.studio_palette_drone_detection_mode = (
        bpy.props.EnumProperty(
            name="Détection",
            items=[
                (
                    'SHOW',
                    "Tous les drones",
                    "Cible tous les drones Sparkshow du show"
                ),
                (
                    'SELECTED',
                    "Sélection",
                    "Limite le preview aux drones sélectionnés"
                ),
                (
                    'COLLECTION',
                    "Collection",
                    "Limite le preview aux drones d'une collection"
                ),
                (
                    'AUTO',
                    "Automatique",
                    "Alias de compatibilité : tous les drones Sparkshow"
                ),
            ],
            default='SHOW',
            update=_live_preview_property_update
        )
    )

    bpy.types.Scene.studio_palette_drone_collection_name = (
        bpy.props.StringProperty(
            name="Collection drones",
            default="",
            update=_live_preview_property_update
        )
    )

    # ========================================================
    # COLORS
    # ========================================================

    bpy.types.Scene.studio_palette_color_items = (
        bpy.props.CollectionProperty(
            type=STUDIO_ColorItem
        )
    )

    bpy.types.Scene.studio_palette_color_index = (
        bpy.props.IntProperty(
            name="Index Couleur",
            default=0
        )
    )

    # ========================================================
    # GRADIENTS
    # ========================================================

    bpy.types.Scene.studio_palette_gradient_items = (
        bpy.props.CollectionProperty(
            type=STUDIO_GradientPresetItem
        )
    )

    bpy.types.Scene.studio_palette_gradient_index = (
        bpy.props.IntProperty(
            name="Index Dégradé",
            default=0,
            update=update_active_gradient
        )
    )

    bpy.types.Scene.studio_palette_gradient_preview_width = (
        bpy.props.FloatProperty(
            name="Largeur aperçu",
            description="Étire horizontalement les miniatures du catalogue de dégradés",
            default=1.0,
            min=0.5,
            max=3.0,
            update=update_gradient_preview_width
        )
    )

    bpy.types.Scene.studio_palette_gradient_preview_size = (
        bpy.props.FloatProperty(
            name="Taille aperçu",
            description="Taille d'affichage des miniatures du catalogue de dégradés",
            default=2.0,
            min=0.5,
            max=6.0,
            update=update_gradient_preview_size
        )
    )

    # ========================================================
    # MODE
    # ========================================================

    bpy.types.Scene.studio_palette_mode = (
        bpy.props.EnumProperty(
            name="Mode",
            items=[
                (
                    'SOLID',
                    "Uni",
                    "Couleur unique"
                ),
                (
                    'GRADIENT',
                    "Dégradé",
                    "Dégradé animé"
                )
            ],
            default='GRADIENT',
            update=_palette_mode_update
        )
    )

    # ========================================================
    # SPATIAL
    # ========================================================

    bpy.types.Scene.studio_palette_grad_axis = (
        bpy.props.EnumProperty(
            name="Spatialisation",
            items=[
                ('X', "+X", ""),
                ('-X', "-X", ""),
                ('Y', "+Y", ""),
                ('-Y', "-Y", ""),
                ('Z', "+Z", ""),
                ('-Z', "-Z", ""),
                (
                    'OBJECT',
                    "Objet",
                    "Direction basée sur un objet"
                ),
                (
                    'CURVE',
                    "Courbe",
                    "Progression le long d'une courbe"
                ),
                (
                    'RADIAL',
                    "Radial",
                    "Distance depuis un centre"
                ),
                (
                    'ANGULAR',
                    "Angulaire",
                    "Angle autour d'un centre"
                )
            ],
            default='X',
            update=_live_preview_property_update
        )
    )

    bpy.types.Scene.studio_palette_grad_target = (
        bpy.props.PointerProperty(
            name="Cible",
            type=bpy.types.Object,
            update=_live_preview_property_update
        )
    )

    bpy.types.Scene.studio_palette_grad_invert_direction = (
        bpy.props.BoolProperty(
            name="Inverser",
            default=False,
            update=_live_preview_property_update
        )
    )

    # ========================================================
    # RGBW
    # ========================================================

    bpy.types.Scene.studio_palette_grad_white = (
        bpy.props.FloatProperty(
            name="Blanc W",
            default=0.0,
            min=0.0,
            max=1.0,
            update=_live_preview_property_update
        )
    )

    # ========================================================
    # EFFECTS
    # ========================================================

    bpy.types.Scene.studio_palette_grad_anim_type = (
        bpy.props.EnumProperty(
            name="Effet",
            items=[
                ('STATIC', "Fixe", ""),
                (
                    'LINE_DRAW',
                    "Trait",
                    "Allumage progressif"
                ),
                (
                    'CYCLE',
                    "Cycle",
                    "Répétition spatiale du dégradé"
                ),
                (
                    'WAVE',
                    "Wave",
                    "Défilement"
                ),
                (
                    'ROTARY',
                    "Rotation",
                    "Rotation autour de l'espace"
                ),
                ('SCANNER', "Scanner", ""),
                ('KITT', "K.I.T.T.", ""),
                ('METEOR', "Météore", ""),
                ('STARS', "Étoiles", ""),
                ('PULSE', "Pulsation", ""),
                ('HEARTBEAT', "Battement", ""),
                ('STROBE', "Stroboscope", "")
            ],
            default='LINE_DRAW',
            update=_live_preview_property_update
        )
    )

    bpy.types.Scene.studio_palette_grad_anim_cycles = (
        bpy.props.FloatProperty(
            name="Cycles",
            default=1.0,
            min=0.1,
            max=10000.0,
            update=_live_preview_property_update
        )
    )

    bpy.types.Scene.studio_palette_grad_anim_speed = (
        bpy.props.FloatProperty(
            name="Vitesse",
            default=1.0,
            min=0.01,
            max=100.0,
            update=_live_preview_property_update
        )
    )

    bpy.types.Scene.studio_palette_grad_pulse_min_intensity = (
        bpy.props.FloatProperty(
            name="Intensité min.",
            description="Luminosité minimale de la pulsation. 0 = peut devenir noir; 1 = aucune variation de luminosité.",
            default=0.20,
            min=0.0,
            max=1.0,
            subtype='FACTOR',
            update=_live_preview_property_update
        )
    )

    # ========================================================
    # EFFECT FADES
    # ========================================================

    bpy.types.Scene.studio_palette_grad_fade_in = (
        bpy.props.IntProperty(
            name="Fondu entrée",
            description="Nombre de frames pour appliquer progressivement l'effet de dégradé.",
            default=0,
            min=0,
            max=10000,
            update=_live_preview_property_update
        )
    )

    bpy.types.Scene.studio_palette_grad_fade_out = (
        bpy.props.IntProperty(
            name="Fondu sortie",
            description="Nombre de frames pour retirer progressivement l'effet de dégradé en fin d'application.",
            default=0,
            min=0,
            max=10000,
            update=_live_preview_property_update
        )
    )

    bpy.types.Scene.studio_palette_grad_anim_delay = (
        bpy.props.FloatProperty(
            name="Intervalle",
            default=2.0,
            min=0.1,
            max=500.0,
            update=_live_preview_property_update
        )
    )

    bpy.types.Scene.studio_palette_grad_fade_count = (
        bpy.props.IntProperty(
            name="Drones Fade",
            default=3,
            min=0,
            max=10000,
            update=_live_preview_property_update
        )
    )

    bpy.types.Scene.studio_palette_grad_fade_time = (
        bpy.props.FloatProperty(
            name="Temps Fade",
            default=5.0,
            min=0.1,
            max=500.0,
            update=_live_preview_property_update
        )
    )

    bpy.types.Scene.studio_palette_grad_fade_curve = (
        bpy.props.EnumProperty(
            name="Courbe Fade",
            items=[
                ('LINEAR', "Linéaire", ""),
                ('BEZIER', "Smooth", "")
            ],
            default='BEZIER',
            update=_live_preview_property_update
        )
    )

    bpy.types.Scene.studio_palette_grad_scan_width = (
        bpy.props.FloatProperty(
            name="Largeur Scanner",
            default=0.15,
            min=0.001,
            max=1.0,
            update=_live_preview_property_update
        )
    )

    bpy.types.Scene.studio_palette_grad_tail_length = (
        bpy.props.FloatProperty(
            name="Longueur Météore",
            default=0.30,
            min=0.001,
            max=1.0,
            update=_live_preview_property_update
        )
    )

    # ========================================================
    # TIMELINE
    # ========================================================

    bpy.types.Scene.studio_palette_grad_start_frame = (
        bpy.props.IntProperty(
            name="Frame début",
            default=1,
            update=_live_preview_property_update
        )
    )

    bpy.types.Scene.studio_palette_grad_duration = (
        bpy.props.IntProperty(
            name="Durée",
            default=60,
            min=1,
            update=_live_preview_property_update
        )
    )

    bpy.types.Scene.studio_palette_grad_interp_type = (
        bpy.props.EnumProperty(
            name="Interpolation",
            items=[
                ('CONSTANT', "Constante", ""),
                ('LINEAR', "Linéaire", ""),
                ('BEZIER', "Bézier", "")
            ],
            default='LINEAR',
            update=_live_preview_property_update
        )
    )

    bpy.types.Scene.studio_palette_grad_use_active_frame = (
        bpy.props.BoolProperty(
            name="Frame active",
            default=True
        )
    )

    bpy.types.Scene.studio_palette_grad_two_key_offset = (
        bpy.props.FloatProperty(
            name="Décalage 2 Keyframes",
            description=(
                "Étendue du décalage temporel selon la position spatiale "
                "du drone. 1.0 = une durée complète du dégradé."
            ),
            default=1.0,
            min=0.0,
            max=3.0,
        )
    )

    # ========================================================
    # BAKE
    # ========================================================

    bpy.types.Scene.studio_palette_bake_mode = (
        bpy.props.EnumProperty(
            name="Mode Bake",
            items=[
                (
                    'TWO_KEYS',
                    "2 Keyframes",
                    "Seulement début et fin"
                ),
                (
                    'FRAME',
                    "Frame par frame",
                    "Une clé par frame"
                ),
                (
                    'ADAPTIVE',
                    "Adaptatif",
                    "Ajoute une clé uniquement si nécessaire"
                )
            ],
            default='FRAME'
        )
    )

    bpy.types.Scene.studio_palette_bake_threshold = (
        bpy.props.FloatProperty(
            name="Seuil",
            description=(
                "Variation minimale "
                "pour créer une clé"
            ),
            default=0.01,
            min=0.00001,
            max=1.0
        )
    )

    # ========================================================
    # SOLID
    # ========================================================

    bpy.types.Scene.studio_palette_solid_start_frame = (
        bpy.props.IntProperty(
            name="Frame début",
            default=1
        )
    )

    bpy.types.Scene.studio_palette_solid_duration = (
        bpy.props.IntProperty(
            name="Durée",
            default=1,
            min=1
        )
    )

    bpy.types.Scene.studio_palette_solid_interp_type = (
        bpy.props.EnumProperty(
            name="Interpolation",
            items=[
                ('CONSTANT', "Constante", ""),
                ('LINEAR', "Linéaire", ""),
                ('BEZIER', "Bézier", "")
            ],
            default='LINEAR'
        )
    )

    bpy.types.Scene.studio_palette_solid_use_active_frame = (
        bpy.props.BoolProperty(
            name="Frame active",
            default=True
        )
    )

    # ========================================================
    # LIVE
    # ========================================================

    bpy.types.Scene.studio_palette_live_preview = (
        bpy.props.BoolProperty(
            name="Live Preview",
            description="Prévisualise les couleurs à chaque changement de frame",
            default=True,
            update=_update_live_preview_property
        )
    )

    bpy.types.Scene.studio_palette_show_outlines = (
        bpy.props.BoolProperty(
            name="Contours",
            default=True,
            update=toggle_selection_outlines
        )
    )


# ============================================================
# UNREGISTER
# ============================================================

def unregister_properties():

    # ========================================================
    # HANDLERS
    # ========================================================

    disable_live_preview()

    global GRADIENT_PREVIEW_REBUILD_TIMER
    try:
        if GRADIENT_PREVIEW_REBUILD_TIMER:
            bpy.app.timers.unregister(_deferred_gradient_catalog_rebuild)
    except Exception:
        pass
    GRADIENT_PREVIEW_REBUILD_TIMER = False

    try:
        while gradient_catalog_load_post in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.remove(gradient_catalog_load_post)
    except Exception:
        pass

    # ========================================================
    # PREVIEWS
    # ========================================================

    global preview_collections

    for pcoll in (
        preview_collections.values()
    ):

        try:

            bpy.utils.previews.remove(
                pcoll
            )

        except Exception:
            pass

    preview_collections.clear()

    cleanup_preview_images()


    # ========================================================
    # PROPERTIES
    # ========================================================

    properties = [

        "studio_palette_drone_detection_mode",
        "studio_palette_drone_collection_name",

        "studio_palette_color_items",
        "studio_palette_color_index",

        "studio_palette_gradient_items",
        "studio_palette_gradient_index",
        "studio_palette_gradient_preview_width",
        "studio_palette_gradient_preview_size",

        "studio_palette_mode",

        "studio_palette_grad_axis",
        "studio_palette_grad_target",
        "studio_palette_grad_invert_direction",

        "studio_palette_grad_white",

        "studio_palette_grad_anim_type",
        "studio_palette_grad_anim_cycles",
        "studio_palette_grad_anim_speed",

        "studio_palette_grad_fade_in",
        "studio_palette_grad_fade_out",

        "studio_palette_grad_anim_delay",
        "studio_palette_grad_fade_count",
        "studio_palette_grad_fade_time",
        "studio_palette_grad_fade_curve",

        "studio_palette_grad_scan_width",
        "studio_palette_grad_tail_length",

        "studio_palette_grad_start_frame",
        "studio_palette_grad_duration",
        "studio_palette_grad_two_key_offset",
        "studio_palette_grad_interp_type",
        "studio_palette_grad_use_active_frame",

        "studio_palette_bake_mode",
        "studio_palette_bake_threshold",

        "studio_palette_solid_start_frame",
        "studio_palette_solid_duration",
        "studio_palette_solid_interp_type",
        "studio_palette_solid_use_active_frame",

        "studio_palette_live_preview",
        "studio_palette_show_outlines",
    ]

    for prop in properties:

        if hasattr(
            bpy.types.Scene,
            prop
        ):

            try:

                delattr(
                    bpy.types.Scene,
                    prop
                )

            except Exception:
                pass


@persistent
def gradient_catalog_load_post(_dummy):
    schedule_gradient_catalog_rebuild(0.25)


# ============================================================
# REGISTER
# ============================================================

def register():

    for cls in classes:

        try:

            bpy.utils.register_class(
                cls
            )

        except ValueError:
            pass

    register_properties()

    # ========================================================
    # HANDLERS
    # ========================================================

    invalidate_cache()
    _PREVIEW_SAVED_COLORS.clear()

    try:
        if gradient_catalog_load_post not in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.append(gradient_catalog_load_post)
    except Exception:
        pass

    scene = bpy.context.scene
    if scene is not None and getattr(scene, "studio_palette_live_preview", False):
        enable_live_preview(scene)


def unregister():

    unregister_properties()

    for cls in reversed(classes):

        try:

            bpy.utils.unregister_class(
                cls
            )

        except RuntimeError:
            pass


# ============================================================
# RELOAD SAFE
# ============================================================

if __name__ == "__main__":

    try:

        unregister()

    except Exception:
        pass

    register()