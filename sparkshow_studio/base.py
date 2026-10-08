from typing import Any

import bpy

from .tools.collection_tools import are_drones_initialized


class BasePanel(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "sparkshow"
    bl_parent_id = "LIGHTSHOW_PT_main_panel"
    bl_options = {"DEFAULT_CLOSED"}


class BasePanelHideIfNoDrone(BasePanel):
    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return are_drones_initialized(context.scene.collection)


class BaseOperator(bpy.types.Operator):
    def report_print(self, message_type: set[str], message: str | Any) -> None:  # noqa: ANN401
        """Report and print into the console."""
        self.report(message_type, message)  # pyright: ignore
        print(f"{message_type}: {message}")
