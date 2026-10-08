import math
import platform
import random
import time
import warnings
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, cast

import bpy
import cv2
import numpy as np
import tqdm
from scipy.optimize import fsolve
from svgpathtools import CubicBezier, Line, QuadraticBezier, svg2paths

from .collection_tools import add_collection, get_collection_by_object_name
from .picture_subtools.mesh_params import mesh_params
from .picture_subtools.svg_tools import (
    add_offset_to_segments,
    add_vertices_to_mesh,
    center_vertices,
    extract_edge_vertices_from_svg,
    extract_vertices_from_svg,
    get_svg_bounds,
    image_to_svg,
    reduce_vertices_randomly,
    remove_close_vertices,
    remove_edge_paths_with_metadata,
    scale_vertices,
    turn_vertices_upside_down,
)
from .picture_subtools.text_tools import create_svg_with_text

warnings.filterwarnings("ignore")

if TYPE_CHECKING:
    from ..setup import Lightshow


def adapt_filename(name: str) -> str:
    slash = "\\" if platform.system() == "Windows" else "/"
    file_last_word = name.split(slash)[-1]
    return file_last_word.split(".")[0]


def convert_image_canny(image_path: str, output_path: str, t1: int = 50, t2: int = 150) -> None:
    # Step 1: Load the image
    img = cv2.imread(image_path)

    # Step 2: Convert to grayscale for edge detection
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Step 3: Use Canny Edge Detection to find edges
    img = cv2.Canny(gray, threshold1=t1, threshold2=t2, L2gradient=False)

    cv2.imwrite(output_path, img)


def standard_mode(
    paths: list, metadata: list[dict], nb_max: int, default_size: int, original_bounds: tuple
) -> list:
    vertices = extract_vertices_from_svg(paths, metadata)

    vertices_edge = extract_edge_vertices_from_svg(paths, metadata, num_samples=50)
    vertices.extend(vertices_edge)

    vertices = reduce_vertices_randomly(vertices, 5000)

    vertices = scale_vertices(vertices, original_bounds, default_size)

    return remove_close_vertices(vertices, nb_max)


def circle_segment_intersection(
    center: tuple[float, float],
    radius: float,
    segment: tuple[tuple[float, float], tuple[float, float]],
) -> list[tuple[float, float]]:
    """Find intersection points of a circle and a line segment."""
    cx, cy = center
    (x1, y1), (x2, y2) = segment

    # Compute quadratic coefficients
    dx, dy = x2 - x1, y2 - y1
    a = dx**2 + dy**2
    b = 2 * (dx * (x1 - cx) + dy * (y1 - cy))
    c = (x1 - cx) ** 2 + (y1 - cy) ** 2 - radius**2

    # Solve the quadratic equation
    discriminant = b**2 - 4 * a * c
    if discriminant < 0:
        return []  # No intersection

    if a == 0:
        return []

    # Calculate t values
    sqrt_discriminant = math.sqrt(discriminant)
    t1 = (-b + sqrt_discriminant) / (2 * a)
    t2 = (-b - sqrt_discriminant) / (2 * a)

    # Find intersection points within the segment (0 <= t <= 1)
    intersections = []
    for t in (t1, t2):
        if 0 <= t <= 1:
            ix = x1 + t * dx
            iy = y1 + t * dy
            intersections.append((ix, iy))

    return intersections


def bounding_box_check(  # noqa: PLR0913
    p0: complex, p1: complex, p2: complex, p3: complex, center: tuple[float, float], radius: float
) -> bool:
    cx, cy = center
    min_x = min(p0.real, p1.real, p2.real, p3.real)
    max_x = max(p0.real, p1.real, p2.real, p3.real)
    min_y = min(p0.imag, p1.imag, p2.imag, p3.imag)
    max_y = max(p0.imag, p1.imag, p2.imag, p3.imag)

    # Closest point on the AABB to the circle center
    closest_x = max(min_x, min(cx, max_x))
    closest_y = max(min_y, min(cy, max_y))

    # Distance from circle center to closest point on AABB
    distance = (cx - closest_x) ** 2 + (cy - closest_y) ** 2

    return distance <= radius**2


def cubic_bezier_circle_intersection(  # noqa: PLR0913
    p0: complex,
    p1: complex,
    p2: complex,
    p3: complex,
    center: tuple[float, float],
    radius: float,
    sample: int,
) -> list[tuple[complex, complex]]:
    """Find intersection points of a cubic Bézier curve and a circle."""
    # Extract circle parameters
    cx, cy = center

    # Check for intersection with the circle
    if not bounding_box_check(p0, p1, p2, p3, center, radius):
        return []

    # Define cubic Bézier parameterized functions
    def bezier(t: float, p0: complex, p1: complex, p2: complex, p3: complex) -> complex:
        return (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t**2 * p2 + t**3 * p3

    def x(t: float) -> complex:
        return bezier(t, p0.real, p1.real, p2.real, p3.real)

    def y(t: float) -> complex:
        return bezier(t, p0.imag, p1.imag, p2.imag, p3.imag)

    # Define the function to solve
    def f(t: float) -> complex:
        return (x(t) - cx) ** 2 + (y(t) - cy) ** 2 - radius**2

    # Generate initial guesses for t in [0, 1]
    t_guesses = np.linspace(0, 1, sample)

    # Use numerical root-finding to solve for t
    t_values = []
    for t_guess in t_guesses:
        t_solution = cast(list[float], fsolve(f, t_guess, xtol=1e-10))

        if 0 <= t_solution[0] <= 1 and not any(
            np.isclose(t_solution[0], t, atol=1e-5) for t in t_values
        ):
            t_values.append(t_solution[0])

    # Calculate intersection points
    return [(x(t), y(t)) for t in t_values]


def add_point_from_unused_segment(
    used_segments_idx: set, segments: list, output_points: list, points_queue: list, radius: float
) -> None:
    if len(used_segments_idx) < len(segments):
        for idx, segment in enumerate(segments):
            if idx not in used_segments_idx:
                new_point = (segment[0].real, segment[0].imag)
                used_segments_idx.add(idx)
                if all(math.dist(new_point, p) >= radius * 0.95 for p in output_points):
                    points_queue.append(new_point)
                    return


def get_optimized_vertices(
    segments: list, radius: float = 1, max_points: int = 200, sample: int = 2
) -> list[tuple[float, float, float]]:
    random_segment = random.choice(segments)  # noqa: S311

    output_points = []
    points_queue = [(random_segment[0].real, random_segment[0].imag)]
    used_segments_idx = {0}

    with tqdm.tqdm(total=max_points, desc="Computing points") as pbar:
        while points_queue and len(output_points) < max_points:
            point = points_queue.pop(0)
            output_points.append(point)
            pbar.update(1)

            for segment_idx, segment in enumerate(segments):
                intersections = cubic_bezier_circle_intersection(
                    segment.start,
                    segment.control1,
                    segment.control2,
                    segment.end,
                    point,
                    radius,
                    sample,
                )

                for intersection in intersections:
                    if intersection in points_queue:
                        continue
                    if intersection in output_points:
                        continue
                    if all(
                        math.dist(intersection, p) >= radius * 0.95 for p in output_points
                    ) and all(math.dist(intersection, p) >= radius * 0.95 for p in points_queue):
                        points_queue.append(intersection)
                        used_segments_idx.add(segment_idx)

            if not points_queue:
                add_point_from_unused_segment(
                    used_segments_idx, segments, output_points, points_queue, radius
                )

    return [(x, y, 0) for x, y in output_points]


def distance_based_mode(  # noqa: PLR0913
    paths: list,
    metadata: list[dict],
    nb_max: int,
    default_size: int,
    original_bounds: tuple[tuple[float, float], float, float],
    adjustment: float = 1.0,
    sample: int = 2,
) -> list:
    total_length = sum(segment.length() for path in paths for segment in path)
    radius = total_length / nb_max / adjustment

    segments = add_offset_to_segments(paths, metadata)
    vertices = get_optimized_vertices(segments, radius=radius, max_points=nb_max, sample=sample)

    return scale_vertices(vertices, original_bounds, default_size)


def convert_paths_to_cubic_bezier(paths: list, metadata: list) -> tuple[list, list]:
    new_paths = []
    for path, meta in zip(paths, metadata, strict=False):
        if all(isinstance(segment, CubicBezier) for segment in path):
            new_paths.append(path)
        else:
            new_path = []
            new_metadata = []
            for segment in path:
                if isinstance(segment, CubicBezier):
                    new_path.append(segment)
                elif isinstance(segment, Line):
                    new_path.append(
                        CubicBezier(segment.start, segment.start, segment.end, segment.end)
                    )
                elif isinstance(segment, QuadraticBezier):
                    new_path.append(
                        CubicBezier(
                            segment.start,
                            (2 / 3) * segment.control + (1 / 3) * segment.start,
                            (2 / 3) * segment.control + (1 / 3) * segment.end,
                            segment.end,
                        )
                    )
                else:  # Line case
                    msg = f"Unknown segment type {segment}"
                    raise TypeError(msg)
                new_metadata.append(meta)
            new_paths.append(new_path)
    return new_paths, metadata


def convert_image_to_vertices(  # noqa: PLR0913
    image_path: Path,
    nb_max: int,
    default_size: int = 30,
    adjustment: float = 1.0,
    mode: str = "Balanced",
    text_mode: bool = False,
) -> list:
    start_time = time.time()

    image_ext = image_path.suffix.lstrip(".")
    if image_ext != "svg":
        svg_path = str(image_path).replace("." + image_ext, "dtklsc.svg")
        try:
            image_to_svg(str(image_path), svg_path)
        except (FileNotFoundError, ValueError) as e:
            warnings.warn(  # noqa: B028
                f"Error while converting image to vertices: {e}"
            )
            return []
    else:
        svg_path = str(image_path)

    paths, metadata = svg2paths(svg_path)

    if not paths:
        warnings.warn(  # noqa: B028
            "No paths found in the SVG file."
        )
        return []

    paths, metadata = convert_paths_to_cubic_bezier(paths, metadata)

    paths, metadata = remove_edge_paths_with_metadata(paths, metadata)

    if image_ext != "svg":
        with suppress(PermissionError):
            Path(svg_path).unlink()
        image = bpy.data.images.load(str(image_path))
        width, height = image.size
        bounds = ((width // 2, height // 2), width, height)
    elif text_mode:
        with suppress(PermissionError):
            Path(svg_path).unlink()
        bounds = get_svg_bounds(paths)
    else:
        bounds = get_svg_bounds(paths)

    if not paths:
        warnings.warn(  # noqa: B028
            "No paths found in the SVG file."
        )
        return []

    match mode:
        case "Fast":
            vertices = standard_mode(paths, metadata, nb_max, default_size, bounds)
        case "Balanced":
            sample = 5 if text_mode else 2
            vertices = distance_based_mode(
                paths, metadata, nb_max, default_size, bounds, adjustment=adjustment, sample=sample
            )
        case _:
            msg = f"Invalid mode: {mode}"
            raise ValueError(msg)

    if image_ext == "svg":
        vertices = center_vertices(vertices)

    print(f"Total computation time: {time.time() - start_time:.2f} seconds")

    return vertices


def display_image_on_plane(
    image_path: str, plane_name: str = "IMG", default_size: int = 30
) -> "bpy.types.Object":
    # Load the image into Blender
    image = bpy.data.images.load(image_path)

    # Create a new material
    material = bpy.data.materials.new(name=f"{plane_name}_Material")
    material.use_nodes = True
    bsdf = material.node_tree.nodes["Principled BSDF"]

    # Add an image texture node
    tex_image = material.node_tree.nodes.new("ShaderNodeTexImage")
    tex_image.image = image
    material.node_tree.links.new(bsdf.inputs["Base Color"], tex_image.outputs["Color"])

    # Create a plane and assign the material
    bpy.ops.mesh.primitive_plane_add(size=default_size, location=(0, 0, 0))
    plane = bpy.context.object
    plane.name = plane_name
    plane.data.materials.append(material)
    bpy.context.scene.collection.objects.unlink(plane)

    # Adjust the plane's dimensions to match the image's aspect ratio
    width, height = image.size
    plane.scale = (width / max(width, height), height / max(width, height), 1)
    plane.location.z = -0.2

    return plane


def load_picture(filepath: str, lightshow: "Lightshow", context: "bpy.types.Context") -> str:
    extension = filepath.split(".")[-1]
    if extension.lower() not in ["png", "jpg", "jpeg", "svg"]:
        return f"Unsupported file format: {extension}, please use a .png, .jpg, .jpeg or .svg file"

    lightshow.nb_vertices = lightshow.nb_drones

    mesh_name = adapt_filename(filepath)
    collection_w_obj = get_collection_by_object_name(context.scene.collection, mesh_name)
    if collection_w_obj is not None:
        return f"This mesh picture is already loaded: {mesh_name}"

    if extension != "svg":
        svg_path = filepath.replace("." + extension, "dtklsc.svg")
        try:
            image_to_svg(filepath, svg_path)
        except (FileNotFoundError, ValueError) as e:
            return f"ERROR: Problem while converting image to vertices: {e}"

        plane_obj = display_image_on_plane(filepath, plane_name=f"IMG_{mesh_name}")

        if plane_obj is None:
            return "ERROR: Wrong import"

        update_picture_info(lightshow, None)
        set_mesh(context, plane_obj, mesh_name, filepath)

        with suppress(PermissionError):
            Path(svg_path).unlink()
    else:
        update_picture_info(lightshow, None)
        set_mesh(
            context,
            bpy.data.objects.new(name=mesh_name + "_empty", object_data=None),
            mesh_name,
            filepath,
        )

    if extension != "svg" and min(cv2.imread(filepath).shape[:2]) < 500:
        return "WARNING The image is in low quality and may not produce good results."

    return ""


def get_picture_meshes(
    scene: "bpy.types.Scene",  # noqa: ARG001
    context: "bpy.types.Context",  # noqa: ARG001
) -> list[tuple[str, str, str]]:
    picture_collection = bpy.data.collections.get("Picture")
    if picture_collection:
        output = [(col.name, col.name, "") for col in picture_collection.children]
        output.reverse()

        if output:
            return output
    return [("None", "None", "None")]


def update_picture_info(lightshow: "Lightshow", context: "bpy.types.Context") -> None:  # noqa: ARG001
    mesh_params.update(lightshow.selected_mesh, lightshow)


def get_image_path(lightshow: "Lightshow") -> str:
    return mesh_params.get_img_path(lightshow.selected_mesh)


def generate_mesh(lightshow: "Lightshow", context: "bpy.types.Context") -> str:
    mesh_params.save_previous_values(lightshow.selected_mesh, lightshow)
    img_file = Path(mesh_params.get_img_path(lightshow.selected_mesh))

    if not img_file:
        return "ERROR Couldn't reload the image, try to delete the mesh and reload the image"
    vertices = convert_image_to_vertices(
        img_file,
        lightshow.nb_vertices,
        mode=lightshow.mesh_image_mode,
        adjustment=lightshow.adjustment,
    )
    update_mesh(lightshow, context, vertices)
    return ""


def generate_mesh_from_text(lightshow: "Lightshow", context: "bpy.types.Context") -> str:
    working_dir = bpy.path.abspath("//")
    text_svg_path = Path(working_dir) / "text_dtklsc.svg"

    lightshow.text_font = bpy.path.abspath(lightshow.text_font)

    error_message = create_svg_with_text(
        text=lightshow.used_characters,
        font_path=lightshow.text_font,
        output_file=str(text_svg_path),
    )
    if error_message:
        return error_message

    vertices = convert_image_to_vertices(
        text_svg_path,
        lightshow.nb_drones_text,
        mode=lightshow.mesh_text_mode,
        adjustment=lightshow.adjustment,
        text_mode=True,
    )

    vertices = turn_vertices_upside_down(vertices)

    update_mesh(
        lightshow,
        context,
        vertices,
        collection_name="MESH_TEXT",
        mesh_name="MESH_" + lightshow.used_characters.strip().replace(" ", "_"),
        collection_type="",
    )
    return ""


def set_mesh(
    context: "bpy.types.Context",
    object_mesh: "bpy.types.Object",
    collection_name: str,
    img_path: str = "",
    mesh_type: str = "Picture",
) -> None:
    # add new mesh
    if mesh_type:
        picture_collection = add_collection(mesh_type, context.scene.collection)
        mesh_collection = add_collection(collection_name, picture_collection)
    else:
        mesh_collection = add_collection(collection_name, context.scene.collection)
    mesh_collection.objects.link(object_mesh)

    if img_path:
        mesh_params.set_path(collection_name, img_path)


def remove_anchors(collection_name: str, mesh_obj: bpy.types.Object) -> None:
    """
    Remove all 'anchor' objects that are children of the given mesh object.

    If the argument is a mesh data block, it finds its corresponding object.
    """
    if mesh_obj is None:
        return

    collection = bpy.data.collections.get(collection_name)
    if collection is None:
        return

    # Loop over child objects of the mesh object
    for child in list(mesh_obj.children):
        if "anchor" in child.name.lower():
            if child.name in collection.objects:
                collection.objects.unlink(child)
            bpy.data.objects.remove(child, do_unlink=True)


def update_mesh(  # noqa: PLR0913
    lightshow: "Lightshow",
    context: "bpy.types.Context",
    vertices: list[tuple[float, float, float]],
    collection_name: str = "",
    mesh_name: str = "",
    collection_type: str = "Picture",
) -> None:
    collection_name = collection_name if collection_name else lightshow.selected_mesh
    mesh = None
    mesh_name = mesh_name if mesh_name else "MESH_" + collection_name

    # getting the mesh
    collection = bpy.data.collections.get(collection_name)

    if collection is None:
        mesh = add_vertices_to_mesh(vertices, mesh_name)
        set_mesh(context, mesh, collection_name, mesh_type=collection_type)
        return

    mesh_obj = None
    for obj in collection.objects:
        if obj.name == mesh_name:
            mesh = obj.data
            mesh_obj = obj
            break

    if mesh is not None:
        # remove previous mesh
        remove_anchors(collection_name, mesh_obj)
        mesh.clear_geometry()
        mesh.from_pydata(vertices, [], [])
        mesh.update()
    else:
        mesh = add_vertices_to_mesh(vertices, mesh_name)
        set_mesh(context, mesh, collection_name, mesh_type=collection_type)
