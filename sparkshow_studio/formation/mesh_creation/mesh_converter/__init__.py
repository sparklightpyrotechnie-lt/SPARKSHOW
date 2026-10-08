from . import mesh_converter


def register() -> None:
    mesh_converter.register()


def unregister() -> None:
    mesh_converter.unregister()
