from . import check_properties, takeoff_land_properties


def register() -> None:
    check_properties.register()
    takeoff_land_properties.register()


def unregister() -> None:
    check_properties.unregister()
    takeoff_land_properties.unregister()
