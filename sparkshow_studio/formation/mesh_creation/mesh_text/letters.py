# pyright: basic
import bpy

from ....base import BaseOperator
from ....setup import get_lightshow
from ....tools.picture_tools import generate_mesh_from_text
from ....tools.tutorial_links_tools import draw_tutorial_button, link
from ..mesh_base import MeshBasePanel


class LIGHTSHOW_PT_Text(MeshBasePanel):
    bl_label = "Mesh Text"
    bl_idname = "LIGHTSHOW_PT_text"
    bl_parent_id = "LIGHTSHOW_PT_mesh_base"
    bl_options = {"HIDE_HEADER"}

    def draw(self, context):  # noqa: ANN001, ANN201
        layout = self.layout
        scene = context.scene
        lightshow = get_lightshow(scene)

        draw_tutorial_button(
            layout,
            context,
            main_button_fn=lambda col: col.prop(lightshow, "used_characters"),
            section=link.formation.mesh.mesh_text,
            option="",
        )

        row = layout.row()
        row.prop(lightshow, "text_font", text="Font")

        row = layout.row()
        row.prop(lightshow, "nb_drones_text", text="Drones Count")

        mesh_name = "MESH_" + lightshow.used_characters.strip().replace(" ", "_")
        if mesh_name in bpy.data.objects:
            nb_vertices = len(bpy.data.objects[mesh_name].data.vertices)  # pyright: ignore
            layout.label(
                text=f"Nb vertices {nb_vertices}",
            )

        row = layout.row()
        row.prop(lightshow, "mesh_text_mode")

        match lightshow.mesh_text_mode:
            case "Fast":
                pass
            case "Balanced":
                layout.prop(lightshow, "adjustment")
            case _:
                msg = f"Invalid mode: {lightshow.mesh_text_mode}"
                raise ValueError(msg)

        row = layout.row()
        row.operator("lightshow.text_creation", text="Create Text")


class LIGHTSHOW_OT_text_creation(BaseOperator):
    bl_idname = "lightshow.text_creation"
    bl_label = "Create Text"
    bl_description = "Generate mesh text using the selected TTF or OTF font"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: bpy.types.Context) -> set:
        scene = context.scene
        lightshow = get_lightshow(scene)

        font_path = lightshow.text_font
        used_characters = lightshow.used_characters
        nb_drones = lightshow.nb_drones_text

        if not font_path:
            self.report({"ERROR"}, "Please select a font file.")
            return {"CANCELLED"}

        if not font_path.endswith((".ttf", ".otf", ".TTF", ".OTF")):
            self.report({"ERROR"}, "Please select a TTF or OTF font file.")
            return {"CANCELLED"}

        if not used_characters:
            self.report({"ERROR"}, "Please enter characters to generate.")
            return {"CANCELLED"}

        # Call your mesh_text generation logic here
        self.report({"INFO"}, f"Generating mesh text from {font_path} with {nb_drones} drones.")

        message = generate_mesh_from_text(lightshow, context)
        if message.startswith("ERROR"):
            self.report_print({"ERROR"}, message[6:])

        return {"FINISHED"}


classes = [
    LIGHTSHOW_PT_Text,
    LIGHTSHOW_OT_text_creation,
]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
