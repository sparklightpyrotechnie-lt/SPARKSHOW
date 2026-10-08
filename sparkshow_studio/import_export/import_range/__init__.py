from . import import_range


def register() -> None:
    import_range.register()


def unregister() -> None:
    import_range.unregister()
