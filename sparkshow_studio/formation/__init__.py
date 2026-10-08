from . import formation, mesh_creation, transition


def register() -> None:
    formation.register()
    mesh_creation.register()
    transition.register()


def unregister() -> None:
    transition.unregister()
    mesh_creation.unregister()
    formation.unregister()
