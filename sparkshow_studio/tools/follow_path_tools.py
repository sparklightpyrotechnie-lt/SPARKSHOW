from typing import cast

import bpy

from ..setup import FPS
from .collection_tools import ANCHOR_SIZE, add_collection


def add_anchor(
    parent: bpy.types.Object,
    collection: bpy.types.Collection,
) -> bpy.types.Object:
    name = f"{parent.name}Anchor"
    anchor = bpy.data.objects.new(name, None)
    collection.objects.link(anchor)
    anchor.empty_display_size = ANCHOR_SIZE
    return anchor


def add_anchors_with_follow_path(  # noqa: PLR0913
    scene: bpy.types.Scene,
    curve_object: bpy.types.Object,
    start_frame: int,
    duration: float,
    time_delta: float,
    nb_anchors: int,
) -> list[bpy.types.Object]:
    anchors_collection = add_collection(f"{curve_object.name}_Anchors", scene.collection)

    anchors = [add_anchor(curve_object, anchors_collection) for _ in range(nb_anchors)]
    duration_frame = round(duration * FPS)
    time_delta_frame = round(time_delta * FPS)
    total_duration_frame = duration_frame + time_delta_frame * (nb_anchors - 1)

    curve = cast(bpy.types.Curve, curve_object.data)
    curve.path_duration = duration_frame
    curve.use_path = True
    curve.use_path_clamp = False
    curve.use_path_follow = True
    curve.eval_time = 0
    curve.keyframe_insert(data_path="eval_time", frame=start_frame)
    curve.eval_time = total_duration_frame
    curve.keyframe_insert(data_path="eval_time", frame=start_frame + total_duration_frame)

    for index, anchor in enumerate(anchors):
        constraint = cast(bpy.types.FollowPathConstraint, anchor.constraints.new("FOLLOW_PATH"))
        constraint.target = curve_object
        constraint.offset = index * time_delta_frame

    return anchors
