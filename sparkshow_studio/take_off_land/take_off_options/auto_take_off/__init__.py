from . import auto_take_off


def register() -> None:
    auto_take_off.register()


def unregister() -> None:
    auto_take_off.unregister()
