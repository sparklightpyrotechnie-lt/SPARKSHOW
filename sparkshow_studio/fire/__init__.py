from . import fire, preview, pyro_bake


def register() -> None:
    fire.register()
    preview.register()
    pyro_bake.register()


def unregister() -> None:
    pyro_bake.unregister()
    preview.unregister()
    fire.unregister()
