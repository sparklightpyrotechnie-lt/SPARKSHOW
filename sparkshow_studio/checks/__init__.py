from . import check, motion_checks, other_checks, properties, proximity_checks


def register() -> None:
    properties.register()
    check.register()
    proximity_checks.register()
    motion_checks.register()
    other_checks.register()


def unregister() -> None:
    check.unregister()
    proximity_checks.unregister()
    motion_checks.unregister()
    other_checks.unregister()
    properties.unregister()
