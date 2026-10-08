from collections.abc import Callable, Generator
from contextlib import suppress
from typing import Optional, cast, overload

import bpy

ANCHOR_SIZE = 0.3


def add_collection(
    new_collection_name: str,
    parent_collection: "bpy.types.Collection",
    color_tag: str = "COLOR_05",
) -> "bpy.types.Collection":
    if new_collection_name in [collection.name for collection in bpy.data.collections]:
        new_collection = bpy.data.collections[new_collection_name]
    else:
        new_collection = bpy.data.collections.new(new_collection_name)
        with suppress(AttributeError):
            new_collection.color_tag = color_tag
    if new_collection not in list(parent_collection.children):
        parent_collection.children.link(new_collection)
    return new_collection


def is_drone(obj: "bpy.types.Object") -> bool:
    return obj.name.startswith("Drone ") and obj.type == "MESH"


def is_import_drone(obj: "bpy.types.Object") -> bool:
    return obj.name.startswith("Import Drone ") and obj.type == "MESH" and obj.visible_get()


def is_anchor(obj: "bpy.types.Object") -> bool:
    return obj.type == "EMPTY" and obj.empty_display_type == "PLAIN_AXES"


def is_import_anchor(obj: "bpy.types.Object") -> bool:
    return is_anchor(obj) and obj.name.endswith("Anchor")


def is_mesh(obj: "bpy.types.Object") -> bool:
    return obj.type == "MESH" and not is_drone(obj)


def is_effector(obj: "bpy.types.Object") -> bool:
    return obj.type == "MESH" and any(
        effector_type in obj.name for effector_type in ["FIXED", "RANDOM", "FADED"]
    )


def add_anchor(
    parent: "bpy.types.Object",
    collection: "bpy.types.Collection",
    *,
    parent_vertex_index: int | None = None,
) -> "bpy.types.Object":
    if parent_vertex_index is None:
        name = f"{parent.name}Anchor"
    else:
        name = f"{parent.name}Anchor {parent_vertex_index:03}"
    anchor = bpy.data.objects.new(name, None)
    collection.objects.link(anchor)
    anchor.empty_display_size = ANCHOR_SIZE
    anchor.parent = parent
    if parent_vertex_index is not None:
        anchor.parent_type = "VERTEX"
        anchor.parent_vertices = [parent_vertex_index] * 3
    return anchor


def add_arrow(scene: "bpy.types.Scene", name: str, size: float) -> "bpy.types.Object":
    arrow = bpy.data.objects.new(name, None)
    scene.collection.objects.link(arrow)
    arrow.empty_display_type = "SINGLE_ARROW"
    arrow.empty_display_size = size
    return arrow


def add_cube(name: str, collection: "bpy.types.Collection") -> "bpy.types.Object":
    cube = bpy.data.objects.new(name, None)
    collection.objects.link(cube)
    cube.empty_display_type = "CUBE"
    return cube


def get_family_drones(family: "bpy.types.Collection") -> list["bpy.types.Object"]:
    """Return the drone objects of the family."""
    return [drone for drone in family.objects if is_drone(drone)]


def get_family_drones_by_index(
    scene_collection: "bpy.types.Collection",
    family_index: int,
) -> list["bpy.types.Object"]:
    """Return the drone objects of the family."""
    for collection in walk_collection(scene_collection):
        if collection.name == f"Family {family_index:03}":
            return get_family_drones(collection)
    return []


def get_families(scene_collection: "bpy.types.Collection") -> list[list["bpy.types.Object"]]:
    """Return the family collections."""
    families_collection = scene_collection.children.get("Families")
    if families_collection is not None:
        return [
            get_family_drones(family)
            for family in families_collection.children
            if family.name.startswith("Family ")
        ]
    return []


def get_import_collection(
    scene_collection: "bpy.types.Collection",
) -> Optional["bpy.types.Collection"]:
    return scene_collection.children.get("Import")


def get_drones(scene_collection: "bpy.types.Collection") -> list["bpy.types.Object"]:
    return [drone for family in get_families(scene_collection) for drone in family]


def get_visible_drones(scene_collection: "bpy.types.Collection") -> list["bpy.types.Object"]:
    return [drone for drone in get_drones(scene_collection) if drone.visible_get()]


def get_selected_drones(context: "bpy.types.Context") -> list["bpy.types.Object"]:
    """Return the selected drone objects."""
    return [drone for drone in context.selected_objects if is_drone(drone)]


def get_import_drones(scene_collection: "bpy.types.Collection") -> list["bpy.types.Object"]:
    import_collection = get_import_collection(scene_collection)
    if import_collection is None:
        return []
    return [drone for drone in import_collection.objects if is_import_drone(drone)]


def get_nb_import_drones(scene_collection: "bpy.types.Collection") -> int:
    import_collection = get_import_collection(scene_collection)
    if import_collection is None:
        return 0
    return sum(1 for drone in import_collection.objects if is_import_drone(drone))


def get_linkable_drone(drone: "bpy.types.Object") -> Optional["bpy.types.Object"]:
    if not drone.constraints:
        return None
    last_constraint = drone.constraints[-1]
    if last_constraint.type != "COPY_LOCATION":
        return None
    last_constraint = cast("bpy.types.CopyLocationConstraint", last_constraint)
    if last_constraint.target is None or not is_import_anchor(last_constraint.target):
        return None
    if last_constraint.target.parent is None or not is_import_drone(last_constraint.target.parent):
        return None
    return last_constraint.target.parent


def get_linkable_drones_couples(
    scene_collection: "bpy.types.Collection",
) -> list[tuple["bpy.types.Object", "bpy.types.Object"]]:
    return [
        (drone, linkable_drone)
        for drone in get_drones(scene_collection)
        if (linkable_drone := get_linkable_drone(drone)) is not None
    ]


@overload
def get_selected_drones_or_all(
    context: "bpy.types.Context",
) -> list["bpy.types.Object"]: ...


@overload
def get_selected_drones_or_all(
    context: "bpy.types.Context",
    *,
    key: Callable[["bpy.types.Object"], bool],
) -> tuple[list["bpy.types.Object"], list["bpy.types.Object"]]: ...


def get_selected_drones_or_all(
    context: "bpy.types.Context",
    *,
    key: Callable[["bpy.types.Object"], bool] | None = None,
) -> list["bpy.types.Object"] | tuple[list["bpy.types.Object"], list["bpy.types.Object"]]:
    drones = get_selected_drones(context)
    use_all = drones == []
    if drones == []:
        drones = get_drones(context.scene.collection)

    if key is None:
        return drones

    if use_all:
        return [drone for drone in drones if key(drone)], []

    selected_drones: list[bpy.types.Object] = []
    filtered_drones: list[bpy.types.Object] = []

    for drone in drones:
        if key(drone):
            selected_drones.append(drone)
        else:
            filtered_drones.append(drone)

    return selected_drones, filtered_drones


def get_drone_y_index(blender_drone: "bpy.types.Object", nb_x: int) -> int:
    family_index = get_family_index(blender_drone)
    return family_index // nb_x


def get_drone_x_index(blender_drone: "bpy.types.Object", nb_x: int) -> int:
    family_index = get_family_index(blender_drone)
    return family_index % nb_x


def get_family_index(blender_drone: "bpy.types.Object") -> int:
    return int(blender_drone.name[-7:-4])


def get_drone_index_in_family(blender_drone: "bpy.types.Object") -> int:
    return int(blender_drone.name[-3:])


def get_nb_drones_per_family(scene_collection: "bpy.types.Collection") -> int:
    return max(len(family) for family in get_families(scene_collection))


def get_drone_index_from_blender_drone(
    blender_drone: "bpy.types.Object",
    scene_collection: "bpy.types.Collection",
) -> int:
    return get_drone_index_in_family(blender_drone) + (
        get_family_index(blender_drone) * get_nb_drones_per_family(scene_collection)
    )


def get_blender_drone_from_drone_index(
    drone_index: int,
    scene_collection: "bpy.types.Collection",
) -> "bpy.types.Object":
    drone_index_in_family = drone_index % get_nb_drones_per_family(scene_collection)
    family_index = drone_index // get_nb_drones_per_family(scene_collection)
    return bpy.data.objects[f"Drone {family_index:03}.{drone_index_in_family:03}"]


def select_drones_from_indices(
    drone_indices: set[int],
    scene: "bpy.types.Scene",
) -> list["bpy.types.Object"]:
    """Select the drones from their indices.

    Returns the list of selected drones.
    """
    drones_to_select = [
        get_blender_drone_from_drone_index(drone_index, scene.collection)
        for drone_index in drone_indices
    ]

    for drone in get_drones(scene.collection):
        drone.select_set(False)
    for drone in drones_to_select:
        drone.select_set(True)

    return drones_to_select


def get_selected_anchors(context: "bpy.types.Context") -> list["bpy.types.Object"]:
    """Return the selected anchor objects."""
    return [obj for obj in context.selected_objects if is_anchor(obj)]


def get_drones_last_anchor(drones: list["bpy.types.Object"]) -> list["bpy.types.Object"]:
    return [
        constraint.target
        for drone in drones
        if (
            constraint := next(
                (
                    cast("bpy.types.CopyLocationConstraint", constraint)
                    for constraint in reversed(drone.constraints)
                    if constraint.type == "COPY_LOCATION"
                ),
                None,
            )
        )
        is not None
        and constraint.target is not None
    ]


def get_selected_mesh(context: "bpy.types.Context") -> list["bpy.types.Object"]:
    """Return the selected anchor objects."""
    return [obj for obj in context.selected_objects if is_mesh(obj)]


def get_selected_others(context: "bpy.types.Context") -> list["bpy.types.Object"]:
    """Return the selected objects that are not drones."""
    return [other for other in context.selected_objects if not is_drone(other)]


def walk_collection(
    collection: "bpy.types.Collection",
) -> Generator["bpy.types.Collection", None, None]:
    """Walk through the collection recursively."""
    yield collection
    for collection_children in collection.children:
        yield from walk_collection(collection_children)


def are_drones_initialized(scene_collection: "bpy.types.Collection") -> bool:
    return (family_collections := scene_collection.children.get("Families")) is not None and any(
        is_drone(obj) for obj in family_collections.all_objects
    )


def get_collection_by_object(
    parent_collection: "bpy.types.Collection",
    obj: "bpy.types.Object",
) -> Optional["bpy.types.Collection"]:
    for collection in walk_collection(parent_collection):
        if obj in list(collection.objects):
            return collection
    return None


def get_collection_by_object_name(
    parent_collection: "bpy.types.Collection",
    obj_name: str,
) -> Optional["bpy.types.Collection"]:
    for collection in walk_collection(parent_collection):
        if obj_name in [collection_obj.name for collection_obj in collection.objects]:
            return collection
    return None


def get_collection_by_name(
    parent_collection: "bpy.types.Collection",
    collection_name: str,
) -> Optional["bpy.types.Collection"]:
    for collection in walk_collection(parent_collection):
        if collection.name == collection_name:
            return collection
    return None


def is_collection_empty(collection: "bpy.types.Collection") -> bool:
    """Return True if the collection has no objects recursively."""
    return all(len(collection.objects) == 0 for collection in walk_collection(collection))
