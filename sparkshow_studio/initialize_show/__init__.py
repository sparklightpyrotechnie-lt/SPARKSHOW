from . import compass, init_show


def register() -> None:
    init_show.register()
    compass.register()


def unregister() -> None:
    compass.unregister()
    init_show.unregister()
