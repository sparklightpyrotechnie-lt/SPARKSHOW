from . import import_export_vviz


def register() -> None:
    import_export_vviz.register()


def unregister() -> None:
    import_export_vviz.unregister()
