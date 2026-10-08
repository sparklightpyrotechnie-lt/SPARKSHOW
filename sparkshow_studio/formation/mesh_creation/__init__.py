from . import follow_path, mesh_base, mesh_converter, mesh_picture, mesh_text, properties


def register() -> None:
    properties.register()
    mesh_base.register()
    follow_path.register()
    mesh_picture.register()
    mesh_text.register()
    mesh_converter.register()


def unregister() -> None:
    follow_path.unregister()
    mesh_picture.unregister()
    mesh_text.unregister()
    mesh_converter.unregister()
    mesh_base.unregister()
    properties.unregister()
