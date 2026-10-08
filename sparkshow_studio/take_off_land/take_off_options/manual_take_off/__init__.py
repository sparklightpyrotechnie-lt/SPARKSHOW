from . import manual_take_off


def register() -> None:
    manual_take_off.register()


def unregister() -> None:
    manual_take_off.unregister()
