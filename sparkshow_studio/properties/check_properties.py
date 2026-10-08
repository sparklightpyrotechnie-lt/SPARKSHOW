import bpy


class CheckProperties(bpy.types.PropertyGroup):
    __annotations__ = {
        "display_drone_movements": bpy.props.BoolProperty(
            name="Display drone movements",
            description="Display drone speed, acceleration, and distance",
            default=False,
        ),
        "sort_by": bpy.props.EnumProperty(
            name="Sort By",
            description="Sort by",
            items=[
                ("name", "Name", "Sort by name"),
                ("speed_xy", "Speed_XY", "Sort by speed"),
                ("speed_z", "Speed_Z", "Sort by speed"),
                ("acceleration", "Acceleration", "Sort by acceleration"),
                ("distance", "Distance", "Sort by distance"),
            ],
            default="name",
        ),
        "nb_errors": bpy.props.IntProperty(
            name="Number of errors",
            description="Number of speed and accel errors in the export",
            default=0,
        ),
    }


def register() -> None:
    bpy.utils.register_class(CheckProperties)
    bpy.types.Scene.check_props = bpy.props.PointerProperty(type=CheckProperties)  # type: ignore


def unregister() -> None:
    bpy.utils.unregister_class(CheckProperties)
    del bpy.types.Scene.check_props  # type: ignore
