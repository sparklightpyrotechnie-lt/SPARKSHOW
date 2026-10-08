import bpy

EXPORT_TYPES_ITEMS = [
    ("EXPORT SHOW", "Show", "Export the current show to a file"),
    ("EXPORT RANGE", "Range", "Export a range of the show to a file"),
    ("EXPORT VVIZ", "VVIZ", "Export the current show to a VVIZ file"),
]

IMPORT_TYPES_ITEMS = [
    ("IMPORT RANGE", "Range", "Import a range from a file"),
    ("IMPORT VVIZ", "VVIZ", "Import a VVIZ file"),
]


class ImportExportProperties(bpy.types.PropertyGroup):
    export_types: bpy.props.EnumProperty(
        name="Export Items",
        description="Group of export operations",
        items=EXPORT_TYPES_ITEMS,
        default="EXPORT SHOW",
    )

    import_types: bpy.props.EnumProperty(
        name="Import Items",
        description="Group of import operations",
        items=IMPORT_TYPES_ITEMS,
        default="IMPORT RANGE",
    )

    import_export_mode: bpy.props.EnumProperty(  # pyright: ignore
        name=" ",
        description="Export and import modes",
        items=[
            ("EXPORT", "Export", "Export the show to a file", "", 0),
            ("IMPORT", "Import", "Import the show from a file", "", 1),
        ],
        default="EXPORT",
    )


classes = (ImportExportProperties,)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)  # type: ignore
    bpy.types.Scene.import_export_properties = bpy.props.PointerProperty(
        type=ImportExportProperties
    )  # type: ignore


def unregister() -> None:
    del bpy.types.Scene.import_export_properties  # pyright: ignore
    for cls in classes:
        bpy.utils.unregister_class(cls)  # type: ignore
