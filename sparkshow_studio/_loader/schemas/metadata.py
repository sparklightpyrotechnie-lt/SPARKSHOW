"""Metadata of the show."""

from pydantic import BaseModel

from sparkshow_studio._loader import __version__


class Metadata(BaseModel):
    """Metadata of the show."""

    loader_version: str = __version__
    """The version of the loader that created the show."""
    sparkshow_creator_version: str | None = None
    """The version of the Sparkshow Creator that created the show (if applicable)."""
    blender_version: str | None = None
    """The version of Blender that created the show (if applicable)."""
