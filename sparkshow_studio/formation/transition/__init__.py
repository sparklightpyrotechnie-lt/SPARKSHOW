from . import transition


def register() -> None:
    transition.register()


def unregister() -> None:
    transition.unregister()
