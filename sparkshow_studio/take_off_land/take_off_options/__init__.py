from . import auto_take_off, direct_take_off, manual_take_off, properties, take_off_base


def register() -> None:
    properties.register()
    take_off_base.register()
    manual_take_off.register()
    auto_take_off.register()
    direct_take_off.register()


def unregister() -> None:
    direct_take_off.unregister()
    auto_take_off.unregister()
    manual_take_off.unregister()
    take_off_base.unregister()
    properties.unregister()
