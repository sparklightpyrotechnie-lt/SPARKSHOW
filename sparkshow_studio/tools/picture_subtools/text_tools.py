import svgwrite
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont


def create_svg_with_text(  # noqa: PLR0913
    text: str,
    font_path: str,
    output_file: str,
    font_size: int = 250,
    space_size: int = 250,
    x_offset: int = 100,
    y_offset: int = 250,
) -> str:
    error_message = ""
    # Load the font
    font = TTFont(font_path)
    glyph_set = font.getGlyphSet()

    # Scaling factor to match font size
    units_per_em = font["head"].unitsPerEm
    scale = font_size / units_per_em

    # Create SVG drawing (use 'full' profile for better compatibility)
    dwg = svgwrite.Drawing(output_file, profile="full")  # , size=("800px", "800px"))

    total_width = 0
    max_height = 0

    # Initial position
    x, y = x_offset, y_offset

    unconverted_chars = []
    # Extract glyphs and convert to SVG paths
    for char in text:
        # Handle spaces by advancing without drawing
        if char.isspace():
            x += space_size
            total_width += space_size * scale
            continue

        glyph_name = font.getBestCmap().get(ord(char))
        if not glyph_name:
            unconverted_chars.append(char)
            continue

        glyph = glyph_set[glyph_name]
        pen = SVGPathPen(glyph_set)
        glyph.draw(pen)
        path_data = pen.getCommands()

        # Skip empty paths
        if not path_data.strip():
            continue

        # Add path to SVG, flipping vertically by applying a negative scale on the y-axis
        path = dwg.path(
            d=path_data, fill="blue", transform=f"translate({x},{y}) scale({scale}, {-scale})"
        )
        dwg.add(path)

        # Advance to next character
        x += glyph.width * scale

        total_width += glyph.width * scale
        max_height = max(max_height, font_size)  # Keep track of max height

    # Adjust the SVG canvas size based on the total width and height
    dwg["width"] = total_width + 2 * x_offset + 500  # Add offsets for padding
    dwg["height"] = max_height + y_offset  # Add offsets for padding

    # Save the SVG file
    try:
        dwg.save()
    except PermissionError:
        return "ERROR Could not transform mesh text, try using Blender as admin."

    if unconverted_chars:
        error_message = (
            f"ERROR The following characters could not be converted: {unconverted_chars}"
        )
    return error_message
