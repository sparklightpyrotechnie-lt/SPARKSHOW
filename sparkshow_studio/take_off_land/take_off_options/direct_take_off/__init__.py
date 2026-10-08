from . import direct_take_off, properties


def register() -> None:
    properties.register()
    direct_take_off.register()


def unregister() -> None:
    direct_take_off.unregister()
    properties.unregister()
