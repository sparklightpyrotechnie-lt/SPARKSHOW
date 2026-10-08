# pyright: basic

import bpy

from ....base import BaseOperator
from ....setup import get_lightshow
from ....tools.picture_tools import convert_image_canny, generate_mesh, get_image_path, load_picture
from ....tools.tutorial_links_tools import draw_tutorial_button, link
from ..mesh_base import MeshBasePanel


class LIGHTSHOW_PT_Picture(MeshBasePanel):
    bl_label = "Picture"
    bl_idname = "LIGHTSHOW_PT_picture"
    bl_parent_id = "LIGHTSHOW_PT_mesh_base"
    bl_options = {"HIDE_HEADER"}

    def draw(self, context):  # noqa: ANN001, ANN201
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        scene = context.scene
        lightshow = get_lightshow(scene)

        draw_tutorial_button(
            layout,
            context,
            main_button_fn=lambda col: col.operator("lightshow.mesh_picture"),
            section=link.formation.mesh.mesh_picture,
            option="",
        )

        if lightshow.selected_mesh != "None":
            row = layout.row()
            row.prop(lightshow, "selected_mesh")
            if not lightshow.selected_mesh.endswith("_converted"):
                row.operator("lightshow.canny_convert")
            if "MESH_" + lightshow.selected_mesh in bpy.data.objects:
                nb_vertices = len(bpy.data.objects["MESH_" + lightshow.selected_mesh].data.vertices)  # pyright: ignore
                layout.label(
                    text=f"Nb vertices {nb_vertices}",
                )
            layout.prop(lightshow, "mesh_image_mode")
            layout.prop(lightshow, "nb_vertices")
            match lightshow.mesh_image_mode:
                case "Fast":
                    pass
                case "Balanced":
                    layout.prop(lightshow, "adjustment")
                case _:
                    msg = "Invalid mode: {lightshow.mesh_image_mode}"
                    raise ValueError(msg)
            layout.operator("lightshow.create_mesh_from_picture")


class LIGHTSHOW_OT_Picture(BaseOperator):
    bl_label = "Load picture"
    bl_description = "Load a picture to place the drones on it with the specified parameters (jpg, jpeg, png or svg)"
    bl_idname = "lightshow.mesh_picture"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")  # pyright: ignore

    def execute(self, context):  # noqa: ANN001, ANN201
        scene = context.scene
        lightshow = get_lightshow(scene)

        message = load_picture(self.filepath, lightshow, context)
        if message:
            if message.startswith("WARNING"):
                self.report_print({"WARNING"}, message[8:])
            else:
                self.report_print({"ERROR"}, message)
            return {"CANCELLED"}

        return {"FINISHED"}

    def invoke(self, context, event):  # noqa: ANN001, ANN201, ARG002
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class LIGHTSHOW_OT_canny_convert(BaseOperator):
    bl_label = "Convert"
    bl_description = "Convert the picture using edge detection method. Result is saved in a new file in your image directory."
    bl_idname = "lightshow.canny_convert"

    def execute(self, context):  # noqa: ANN001, ANN201
        scene = context.scene
        lightshow = get_lightshow(scene)

        image_path = get_image_path(lightshow)
        extension = image_path.split(".")[-1]
        output_path = image_path.replace("." + extension, "_converted.png")
        convert_image_canny(image_path, output_path)

        self.report({"INFO"}, "Result saved in " + output_path)

        return {"FINISHED"}


class LIGHTSHOW_OT_create_mesh_from_picture(BaseOperator):
    bl_label = "Create mesh"
    bl_description = "Create the mesh from the picture"
    bl_idname = "lightshow.create_mesh_from_picture"

    def execute(self, context):  # noqa: ANN001, ANN201
        scene = context.scene
        lightshow = get_lightshow(scene)

        if lightshow.selected_mesh == "None":
            self.report_print(
                {"ERROR"},
                "No mesh selected",
            )
            return {"CANCELLED"}

        message = generate_mesh(lightshow, context)
        if message.startswith("ERROR"):
            self.report_print({"ERROR"}, message[6:])

        return {"FINISHED"}


classes = [
    LIGHTSHOW_PT_Picture,
    LIGHTSHOW_OT_Picture,
    LIGHTSHOW_OT_canny_convert,
    LIGHTSHOW_OT_create_mesh_from_picture,
]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
