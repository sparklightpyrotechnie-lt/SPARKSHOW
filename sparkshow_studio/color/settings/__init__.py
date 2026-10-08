from . import properties, settings


def register() -> None:
    properties.register()
    settings.register()


def unregister() -> None:
    settings.unregister()
    properties.unregister()
