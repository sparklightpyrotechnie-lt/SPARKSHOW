import bpy

LAND_TYPE_ITEMS_ALL_IN_ONE = [
    ("NONE", "--", "No land type selected"),
    ("RTL", "RTL", "Return the drones to their launch position automatically"),
]

LAND_TYPE_ITEMS_STANDARD = [
    *LAND_TYPE_ITEMS_ALL_IN_ONE,
    ("MANUAL LAND", "Manual", "Land the drones manually, giving a straightforward landing command"),
]


class LandProperties(bpy.types.PropertyGroup):
    land_types_standard: bpy.props.EnumProperty(
        name="Land Type",
        description="Type of landing to perform",
        items=LAND_TYPE_ITEMS_STANDARD,
        default="NONE",
    )

    land_types_all_in_one: bpy.props.EnumProperty(
        name="Land Type All In One",
        description="Type of landing to perform when using the all-in-one platform",
        items=LAND_TYPE_ITEMS_ALL_IN_ONE,
        default="NONE",
    )


classes = (LandProperties,)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)  # type: ignore
    bpy.types.Scene.land_properties = bpy.props.PointerProperty(type=LandProperties)  # type: ignore


def unregister() -> None:
    del bpy.types.Scene.land_properties  # pyright: ignore
    for cls in classes:
        bpy.utils.unregister_class(cls)  # type: ignore
