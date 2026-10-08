from . import other_checks


def register() -> None:
    other_checks.register()


def unregister() -> None:
    other_checks.unregister()
