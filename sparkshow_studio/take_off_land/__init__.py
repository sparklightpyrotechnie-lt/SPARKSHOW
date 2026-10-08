from . import land_options, take_off_land_base, take_off_options


def register() -> None:
    take_off_land_base.register()
    take_off_options.register()
    land_options.register()


def unregister() -> None:
    land_options.unregister()
    take_off_options.unregister()
    take_off_land_base.unregister()
