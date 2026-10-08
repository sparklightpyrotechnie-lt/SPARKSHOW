import bpy


def update_takeoff_type(self: "TakeoffProperties", context: bpy.types.Context) -> None:  # noqa: ARG001
    """Update the takeoff type."""
    if self.takeoff_type == "GCS":
        self.takeoff_height = 1.0
        self.takeoff_duration = 3.0
    elif self.takeoff_type == "DCC":
        self.takeoff_height = 1.5
        self.takeoff_duration = 4.0
    else:
        msg = f"Unknown takeoff type: {self.takeoff_type}"
        raise RuntimeError(msg)


class TakeoffProperties(bpy.types.PropertyGroup):
    takeoff_height: bpy.props.FloatProperty(  # pyright: ignore
        name="Takeoff Height",
        description="Height to take off to in meters.",
        default=1.0,
        min=1.0,
        max=20.0,
        precision=2,
        unit="LENGTH",
    )
    takeoff_duration: bpy.props.FloatProperty(  # pyright: ignore
        name="Takeoff Duration",
        description="Duration of the takeoff in seconds.",
        default=3.0,
        min=2.0,
        precision=2,
    )
    transition_duration: bpy.props.FloatProperty(  # pyright: ignore
        name="Transition Duration",
        description="Duration of the transition in seconds.",
        default=7.0,
        min=0.0,
        precision=2,
    )
    takeoff_type: bpy.props.EnumProperty(  # pyright: ignore
        name="Takeoff Type",
        description="Type of takeoff.",
        items=[
            ("GCS", "GCS", "Takeoff for GCS"),
            ("DCC", "DCC", "Takeoff for DCC"),
        ],
        default="GCS",
        update=update_takeoff_type,
    )
    take_off_options_classic: bpy.props.EnumProperty(
        name="Takeoff Options",
        description="Takeoff option to perform",
        items=[
            ("NONE", "--", "No takeoff option selected"),
            ("MANUAL TAKE OFF", "Manual", "Take off manually with specified altitude"),
            ("AUTO TAKE OFF", "Auto Grids", "Take off automatically to separated grids"),
            (
                "DIRECT TAKE OFF",
                "Direct to Formation",
                "Take off directly to the specified drone formation",
            ),
        ],
        default="NONE",
    )
    take_off_options_all_in_one: bpy.props.EnumProperty(
        name="Takeoff Options",
        description="Takeoff option to perform",
        items=[
            ("NONE", "--", "No takeoff option selected"),
            ("AUTO TAKE OFF", "Auto Grids", "Take off automatically to separated grids"),
            (
                "DIRECT TAKE OFF",
                "Direct to Formation",
                "Take off directly to the specified drone formation",
            ),
        ],
        default="NONE",
    )


classes = [TakeoffProperties]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.takeoff_props = bpy.props.PointerProperty(type=TakeoffProperties)  # type: ignore


def unregister() -> None:
    for cls in classes:
        bpy.utils.unregister_class(cls)

    if hasattr(bpy.types.Scene, "takeoff_props"):
        del bpy.types.Scene.takeoff_props  # type: ignore
