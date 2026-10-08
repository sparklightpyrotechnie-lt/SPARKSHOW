# pyright: basic
from typing import TYPE_CHECKING, Optional, cast

import numpy as np
from mathutils import Matrix, Vector
from scipy.spatial.distance import cdist

from .collection_tools import is_anchor

if TYPE_CHECKING:
    import bpy
    from numpy.typing import NDArray


def positive_zero(point) -> Vector:  # noqa: ANN001
    for index in range(len(point)):
        if abs(point[index]) < 1e-3:
            point[index] = 0.0
    return point


def get_number_cross(point, direction, mesh):  # noqa: ANN001, ANN201
    is_crossing = True
    number_cross = -1
    new_point = point.copy()
    point = positive_zero(point)
    direction = positive_zero(direction)
    while is_crossing and number_cross < 100:
        result = mesh.ray_cast(
            new_point,
            direction,
            distance=1e16,
        )
        is_crossing = result[0]
        new_point = result[1] + direction
        number_cross += 1
    return number_cross


# crossing number algorithm or the even-odd rule algorithm
def is_drone_inside_mesh(mesh, drone):  # noqa: ANN001, ANN201
    mesh_matrix_world = mesh.matrix_world
    m_x = Matrix.Rotation(mesh_matrix_world.to_euler().x, 3, "X")
    m_y = Matrix.Rotation(mesh_matrix_world.to_euler().y, 3, "Y")
    m_z = Matrix.Rotation(mesh_matrix_world.to_euler().z, 3, "Z")

    m_x.invert()
    m_y.invert()
    m_z.invert()

    point = drone.matrix_world.to_translation()
    point = point - mesh_matrix_world.to_translation()
    point = m_x @ m_y @ m_z @ point
    mesh_scale = mesh_matrix_world.to_scale()
    if any(scale == 0 for scale in mesh_scale):
        return False
    point = Vector([1 / scale for scale in mesh_scale]) * point
    direction = Vector((0, 0, 0.001))
    number_cross = get_number_cross(point, direction, mesh)
    return number_cross % 2


def distance_from_mesh(mesh, drone):  # noqa: ANN001, ANN201
    mesh_matrix_world = mesh.matrix_world
    m_x = Matrix.Rotation(mesh_matrix_world.to_euler().x, 3, "X")
    m_y = Matrix.Rotation(mesh_matrix_world.to_euler().y, 3, "Y")
    m_z = Matrix.Rotation(mesh_matrix_world.to_euler().z, 3, "Z")

    m_x.invert()
    m_y.invert()
    m_z.invert()

    point = drone.matrix_world.to_translation()
    point = point - mesh_matrix_world.to_translation()
    point = m_x @ m_y @ m_z @ point
    mesh_scale = mesh_matrix_world.to_scale()
    if any(scale == 0 for scale in mesh_scale):
        return float("inf")
    point = Vector([1 / scale for scale in mesh_scale]) * point
    return np.linalg.norm(mesh.scale * (point - mesh.closest_point_on_mesh(point)[1]))


def get_anchors_vertex(obj: "bpy.types.Object") -> Optional["NDArray[np.float64]"]:
    """Return the coordinates of the anchors of the object."""
    if obj.data is None:
        return None
    if obj.type == "MESH":
        coordinates = [v.co for v in cast("bpy.types.Mesh", obj.data).vertices]
    elif obj.type == "CURVE":
        coordinates = [
            s.co
            for spline in cast("bpy.types.Curve", obj.data).splines
            for s in (spline.bezier_points if spline.type == "BEZIER" else spline.points)
        ]
    else:
        return None
    return np.array(
        [coordinates[anchor.parent_vertices[0]] for anchor in obj.children if is_anchor(anchor)],
    )


def get_anchors_min_distance(obj: "bpy.types.Object") -> float | None:
    """Return the minimum distance between anchors of the object.

    Return None if the object has no anchor or only one anchor,
    and thus no distance can be computed.
    """
    coordinates = get_anchors_vertex(obj)
    if coordinates is None or len(coordinates) <= 1:
        return None

    coordinates *= obj.scale  # pyright: ignore

    distances = cdist(coordinates, coordinates)
    np.fill_diagonal(distances, np.inf)
    return float(np.min(distances))
