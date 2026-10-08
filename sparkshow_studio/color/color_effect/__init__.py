from . import color_effect_base, effects_panel_creator, properties


def register() -> None:
    properties.register()
    color_effect_base.register()
    effects_panel_creator.register()


def unregister() -> None:
    effects_panel_creator.unregister()
    color_effect_base.unregister()
    properties.unregister()
