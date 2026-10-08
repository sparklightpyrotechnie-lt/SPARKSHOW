from . import safe_delete


def register() -> None:
    safe_delete.register()


def unregister() -> None:
    safe_delete.unregister()
