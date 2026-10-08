import importlib
import os
import sys
from contextlib import suppress

from .install import execute_installation

bl_info = {
    "name": "Sparkshow Studio",
    "author": "Sparkshow Studio team",
    "version": (5, 2, 77),
    "blender": (4, 1, 0),
    "location": "View3D > Sidebar > sparkshow",
    "description": "Drone light shows design and sequencing tool.",
    "warning": "",
    "tracker_url": "",
    "support": "COMMUNITY",
    "category": "Lightshow",
}


MODULES_NAMES = [
    f"{__name__}.{module_name}"
    for module_name in (
        "preferences",
        "setup",
        "migration",
        "main_panel",
        "ui_sections",
        "initialize_show",
        "properties",
        "take_off_land",
        "formation",
        "color",
        "fire",
        "checks",
        "import_export",
        "live_color",
        "bindings",
        "lighting",
        "studio_panel",
        "runtime",
    )
]


def register() -> None:
    for module_name in MODULES_NAMES:
        with suppress(AttributeError, KeyError):
            sys.modules[module_name].register()


def unregister() -> None:
    for module_name in MODULES_NAMES:
        with suppress(AttributeError, KeyError):
            sys.modules[module_name].unregister()


DEV = os.environ.get("BLENDER_DEV_MODE", "false") == "true"

execute_installation(force=DEV)

for module_name in MODULES_NAMES:
    with suppress(AttributeError, KeyError):
        try:
            importlib.reload(sys.modules[module_name])
        except KeyError:
            importlib.import_module(
                module_name,
            )

if __name__ == "__main__":
    register()
