from . import properties, rtl


def register() -> None:
    properties.register()
    rtl.register()


def unregister() -> None:
    rtl.unregister()
    properties.unregister()
