from . import proximity_checks


def register() -> None:
    proximity_checks.register()


def unregister() -> None:
    proximity_checks.unregister()
