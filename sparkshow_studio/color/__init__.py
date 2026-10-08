from . import color, color_effect, magic_color, properties, set_color, settings


def register() -> None:
    properties.register()
    color.register()
    set_color.register()
    magic_color.register()
    color_effect.register()
    settings.register()


def unregister() -> None:
    color.unregister()
    set_color.unregister()
    magic_color.unregister()
    color_effect.unregister()
    properties.unregister()
    settings.unregister()
