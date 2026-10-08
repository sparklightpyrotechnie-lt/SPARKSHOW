from pathlib import Path
from typing import Literal, overload

import bpy

ASSETS_PATH = Path(__file__).parent / "assets.blend"


@overload
def get_asset(asset_type: Literal["node_groups"], name: str) -> "bpy.types.NodeTree": ...


@overload
def get_asset(asset_type: Literal["materials"], name: str) -> "bpy.types.Material": ...


def get_asset(asset_type: Literal["node_groups"], name: str) -> "bpy.types.NodeTree":  # pyright: ignore
    """Return the selected asset from the assets.blend file."""
    asset = getattr(bpy.data, asset_type).get(name)
    if asset is not None:
        return asset
    with bpy.data.libraries.load(str(ASSETS_PATH)) as (data_from, data_to):
        setattr(data_to, asset_type, [name])
    return getattr(bpy.data, asset_type)[name]
