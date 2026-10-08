from pathlib import Path

import bpy


def add_compass_handlers() -> None:
    compass_collection = bpy.data.collections.get("compass.svg")

    if compass_collection:
        if len(compass_collection.objects) == 0:
            bpy.data.collections.remove(compass_collection)
        else:
            return

    script_dir = Path(__file__).parent
    compass_svg = script_dir / "compass.svg"

    if not compass_svg.is_file():
        msg = f"Compass SVG file not found at: {compass_svg}"
        raise FileNotFoundError(msg)

    bpy.ops.import_curve.svg(filepath=str(compass_svg))

    new_collection = bpy.data.collections.get("compass.svg")

    system_col = bpy.data.collections.get("System")
    system_col.children.link(new_collection)
    if new_collection is not None:
        bpy.context.scene.collection.children.unlink(new_collection)

    if new_collection is None:
        msg = "The 'compass.svg' was not found after importing the SVG."
        raise RuntimeError(msg)

    for obj in new_collection.objects:
        obj.select_set(True)

    bpy.context.view_layer.objects.active = new_collection.objects[0]

    bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
    obj.name = "Compass"
    obj.scale = (10, 10, 10)
    obj.location = (-0.47, -0.01, -0.15)

    mat = bpy.data.materials.new(name="color_compass")

    mat.diffuse_color = (0.294, 0.494, 0.810, 0.1)  # RGB color
    mat.use_backface_culling = False
    obj.data.materials.clear()
    obj.data.materials.append(mat)

    return


class LIGHTSHOW_OT_add_compass(bpy.types.Operator):
    bl_label = "🧭 Add Compass"
    bl_description = "Add a compass to the scene"
    bl_idname = "lightshow.add_compass"

    def execute(self, context: bpy.types.Context) -> set[str]:  # noqa: ARG002
        add_compass_handlers()
        return {"FINISHED"}


classes = [LIGHTSHOW_OT_add_compass]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in classes:
        bpy.utils.unregister_class(cls)
