from . import motion_checks


def register() -> None:
    motion_checks.register()


def unregister() -> None:
    motion_checks.unregister()
