import bpy

MESH_TYPE_ITEMS = [
    ("NONE", "--", "No mesh type selected"),
    ("PICTURE", "Picture", "Create a mesh from a picture"),
    ("TEXT", "Text", "Create a mesh from text"),
    ("MESH CONVERTER", "Mesh Converter", "Convert existing objects to mesh"),
    ("FOLLOW PATH", "Follow Path", "Create a mesh that follows a path"),
]


class MeshProperties(bpy.types.PropertyGroup):
    mesh_types: bpy.props.EnumProperty(
        name="Mesh Type",
        description="Type of mesh to create",
        items=MESH_TYPE_ITEMS,
        default="NONE",
    )


classes = (MeshProperties,)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)  # type: ignore
    bpy.types.Scene.mesh_properties = bpy.props.PointerProperty(type=MeshProperties)  # type: ignore


def unregister() -> None:
    del bpy.types.Scene.mesh_properties  # pyright: ignore
    for cls in classes:
        bpy.utils.unregister_class(cls)  # type: ignore
