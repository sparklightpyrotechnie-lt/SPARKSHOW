from . import land_base, manual_land, properties, rtl


def register() -> None:
    properties.register()
    land_base.register()
    manual_land.register()
    rtl.register()


def unregister() -> None:
    rtl.unregister()
    manual_land.unregister()
    land_base.unregister()
    properties.unregister()
