from typing import TYPE_CHECKING, Optional, cast

if TYPE_CHECKING:
    import bpy

    from ..setup import Lightshow


def update_mesh_converter_node(lightshow: "Lightshow", context: "bpy.types.Context") -> None:  # noqa: ARG001
    obj = lightshow.mesh_converter_object
    if obj is None:
        return
    if obj.modifiers.get("Geometry Nodes") is None:
        return

    converter_node = cast(Optional["bpy.types.NodesModifier"], obj.modifiers.get("Geometry Nodes"))
    assert converter_node is not None, "Mesh converter node not found"
    converter_node["Socket_0"] = lightshow.mesh_converter_object
    converter_node["Socket_4"] = lightshow.mesh_converter_distance
    converter_node["Socket_3"] = lightshow.mesh_converter_seed
    converter_node["Socket_6"] = lightshow.mesh_converter_static_object
    converter_node["Socket_7"] = lightshow.mesh_converter_is_rigged
    converter_node.show_viewport = True
