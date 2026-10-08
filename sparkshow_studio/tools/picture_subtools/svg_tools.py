# pyright: ignore

import random
import re
import time
from pathlib import Path

import bpy
import numpy as np
import vtracer
from PIL import Image
from scipy.spatial import cKDTree


def has_transparent_background(image_path: str) -> bool:
    image = Image.open(image_path).convert("RGBA")
    alpha = image.getchannel("A")

    return any(pixel < 255 for pixel in alpha.getdata())


def transparent_to_white(image_path: str, output_path: str) -> None:
    image = Image.open(image_path).convert("RGBA")
    white_background = Image.new("RGBA", image.size, (255, 255, 255, 255))

    # Paste image onto white background using the alpha channel as a mask
    white_background.paste(image, (0, 0), image)

    # Convert to RGB (removes transparency)
    white_background.convert("RGB").save(output_path)


def image_to_svg(image_path: str, output_path: str) -> None:
    image_path = Path(image_path)
    output_path = Path(output_path)

    if not image_path.exists():
        return

    if has_transparent_background(image_path):
        transparent_to_white(str(image_path), image_path.with_name(image_path.name + "_white.png"))
        image_path = image_path.with_name(image_path.name + "_white.png")

    vtracer.convert_image_to_svg_py(
        str(image_path),
        str(output_path),
        colormode="color",
        layer_difference=64,
        corner_threshold=60,
        max_iterations=10,
    )


def get_svg_bounds(paths: list) -> tuple[tuple[float, float], float, float]:
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")

    for path in paths:
        for segment in path:
            for point in [segment.start, segment.end]:
                min_x = min(min_x, point.real)
                max_x = max(max_x, point.real)
                min_y = min(min_y, point.imag)
                max_y = max(max_y, point.imag)

    width = max_x - min_x
    height = max_y - min_y
    return (min_x, min_y), width, height


def scale_vertices(
    vertices: list[tuple[float, float, float]],
    original_bounds: tuple[tuple[float, float], float, float],
    target_size: float,
) -> list[tuple[float, float, float]]:
    (min_x, min_y), orig_width, orig_height = original_bounds
    scale_x = target_size / orig_width
    scale_y = target_size / orig_height

    scale = min(scale_x, scale_y)

    scaled_vertices = []

    for x, y, z in vertices:
        # Translate to origin, scale, then translate back to target size
        scaled_x = (x - min_x) * scale
        scaled_y = (y - min_y) * scale
        scaled_vertices.append((scaled_x, -scaled_y, z))

    return scaled_vertices


def center_vertices(vertices: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
    if not vertices:
        print("[WARNING] No vertices found")
        return []

    # Find the bounding box of the vertices
    min_x = min(v[0] for v in vertices)
    min_y = min(v[1] for v in vertices)
    max_x = max(v[0] for v in vertices)
    max_y = max(v[1] for v in vertices)

    # Calculate the center of the bounding box
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2

    # Center the vertices around (0, 0) by subtracting the center offset
    return [(x - center_x, y - center_y, z) for x, y, z in vertices]


def turn_vertices_upside_down(
    vertices: list[tuple[float, float, float]],
) -> list[tuple[float, float, float]]:
    if not vertices:
        print("[WARNING] No vertices found")
        return []

    # Find the bounding box of the vertices
    min_y = min(v[1] for v in vertices)
    max_y = max(v[1] for v in vertices)

    # Calculate the center of the bounding box
    center_y = (min_y + max_y) / 2

    # Center the vertices around (0, 0) by subtracting the center offset
    return [(x, center_y - y, z) for x, y, z in vertices]


def remove_edge_vertices(
    vertices: list[tuple[float, float, float]], threshold: float = 0.975
) -> list[tuple[float, float, float]]:
    # Find the bounding box of the vertices
    min_x = min(v[0] for v in vertices)
    max_x = max(v[0] for v in vertices)
    min_y = min(v[1] for v in vertices)
    max_y = max(v[1] for v in vertices)

    # Define adjusted bounds with the threshold
    inner_min_x = min_x * threshold
    inner_max_x = max_x * threshold
    inner_min_y = min_y * threshold
    inner_max_y = max_y * threshold

    # Filter out vertices that lie within the threshold distance from the edges
    return [
        (x, y, z)
        for x, y, z in vertices
        if inner_min_x < x < inner_max_x and inner_min_y < y < inner_max_y
    ]


def remove_edge_paths_with_metadata(paths: list, metadata: list[dict]) -> tuple[list, list[dict]]:
    if not paths:
        return paths, metadata

    if len(paths[0]) != 4:
        return paths, metadata

    return paths[1:], metadata[1:]


def remove_close_vertices(
    vertices: list[tuple[float, float, float]],
    max_vertices: int,
    min_distance: float = 0.1,
    grid_size: float = 0.1,
) -> list[tuple[float, float, float]]:
    # Convert vertices to a NumPy array for KD-tree and other calculations
    vertices_array = np.array(vertices)

    max_time = time.time() + 5
    while len(vertices_array) > max_vertices and time.time() < max_time:
        # Build a KD-tree for fast nearest-neighbor lookup
        tree = cKDTree(vertices_array)

        # Find all pairs of vertices within the minimum distance
        pairs = tree.query_pairs(r=min_distance)

        if not pairs:
            # If no close pairs found, increase the minimum distance slightly
            min_distance *= 1.1
            continue

        # Create a grid-based approach to evenly space points
        # Divide the space into a grid (this can be customized for different dimensions)
        grid_cells = {}
        for i, vertex in enumerate(vertices_array):
            cell = tuple(np.floor(vertex[:2] / grid_size).astype(int))  # Use 2D grid for simplicity
            if cell not in grid_cells:
                grid_cells[cell] = []
            grid_cells[cell].append(i)

        # Remove points from densely packed cells (cells with more points than needed)
        indices_to_remove = set()
        for indices in grid_cells.values():
            if len(indices) > 1:
                # Remove the point in the densest region
                for idx in indices[1:]:
                    indices_to_remove.add(idx)

        # Filter out vertices that are too close (based on pairs and grid density)
        vertices_array = np.delete(vertices_array, list(indices_to_remove), axis=0)

        grid_size *= 1.1

    return vertices_array.tolist()


def remove_vertices_with_min_distance(
    vertices: list[tuple[float, float, float]],
    min_distance: float,
) -> list[tuple[float, float, float]]:
    if not vertices:
        return vertices

    filtered_vertices = vertices.copy()
    distance_sq = min_distance**2

    # Iterate until no close pairs are found
    has_close_pair = True
    while has_close_pair:
        has_close_pair = False
        # Check each pair of vertices
        for i, v1 in enumerate(filtered_vertices):
            for j, v2 in enumerate(filtered_vertices):
                if i != j:
                    # Compute squared distance between the two vertices
                    dx, dy, dz = v1[0] - v2[0], v1[1] - v2[1], v1[2] - v2[2]
                    dist_sq = dx**2 + dy**2 + dz**2

                    if dist_sq < distance_sq:
                        # Found a close pair; remove one vertex
                        filtered_vertices.pop(j)
                        has_close_pair = True
                        break  # Exit the inner loop after modifying the list
            if has_close_pair:
                break  # Exit the outer loop after modifying the list

    return filtered_vertices


def parse_translation(transform: str) -> tuple[float, float]:
    tx = 0.0
    ty = 0.0

    match = re.search(r"translate\(([-\d.]+),\s*([-\d.]+)\)", transform)
    if match:
        tx = float(match.group(1))
        ty = float(match.group(2))

    # Match the scale transformation
    scale_match = re.search(r"scale\(([-\d.]+),\s*([-\d.]+)\)", transform)
    if scale_match:
        scale_x = float(scale_match.group(1))
        scale_y = float(scale_match.group(2))
        tx /= scale_x
        ty /= scale_y

    return tx, ty


def extract_vertices_from_svg(paths: list, metadata: list) -> list[tuple[float, float, float]]:
    return [
        (segment.start.real + tx, segment.start.imag + ty, 0.0)
        for path, meta in zip(paths, metadata, strict=False)
        for tx, ty in [parse_translation(meta.get("transform", ""))]
        for segment in path
    ]


def sample_points_on_segment(
    segment,  # noqa: ANN001
    offset: tuple[float, float],
    num_samples: int = 10,
) -> list[tuple[float, float, float]]:
    t_values = np.linspace(0, 1, num_samples)
    tx, ty = offset

    return [(segment.point(t).real + tx, segment.point(t).imag + ty, 0) for t in t_values]


def extract_edge_vertices_from_svg(
    paths: list, metadata: list, num_samples: int = 10, avr_space: float = 0
) -> tuple[list[tuple[float, float, float]]]:
    edge_vertices = []

    # Preprocess transformations to avoid repeated parsing
    for path, meta in zip(paths, metadata, strict=False):
        transform = meta.get("transform", "")
        offset = parse_translation(transform)

        # Process each segment in the path
        for segment in path:
            if avr_space > 0:
                num_samples: int = int(segment.length() / avr_space / 2)

            # Sample points on the segment and apply transformation offset
            sampled_points = sample_points_on_segment(segment, offset, num_samples)

            # Extend the edge_vertices with the sampled points
            edge_vertices.extend(sampled_points)

    return edge_vertices


def reduce_vertices_randomly(
    vertices: list[tuple[float, float, float]], target_count: int
) -> list[tuple[float, float, float]]:
    if len(vertices) <= target_count:
        return vertices

    return random.sample(vertices, target_count)


def add_vertices_to_mesh(
    vertices: list[tuple[float, float, float]],
    mesh_name: str,
) -> "bpy.types.Object":
    new_mesh_type = bpy.data.meshes.new(mesh_name + "_pattern")
    obj = bpy.data.objects.new(mesh_name, new_mesh_type)

    new_mesh_type.from_pydata(vertices, [], [])
    new_mesh_type.update()

    return obj


def add_offset_to_segments(paths: list, metadata: list[dict]) -> list:
    for path, meta in zip(paths, metadata, strict=False):
        transform = meta.get("transform", "")
        tx, ty = parse_translation(transform)

        for segment in path:
            segment.start += complex(tx, ty)
            segment.end += complex(tx, ty)
            segment.control1 += complex(tx, ty)
            segment.control2 += complex(tx, ty)

    return [segment for path in paths for segment in path]
