import bpy

from ..tools.collection_tools import is_drone


# Custom delete operator to bypass deletion for MESH objects
class OBJECT_OT_delete_override(bpy.types.Operator):
    """Delete objects, but ignore MESH objects."""

    bl_idname = "object.delete_override"
    bl_label = "Delete Selected Objects (Ignore Drones)"

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        # Ensure the operator can only be called in Object Mode
        return context.mode == "OBJECT"

    def execute(self, context: bpy.types.Context) -> set[str]:
        for obj in context.selected_objects:
            if is_drone(obj):
                obj.select_set(False)
        bpy.ops.object.delete()
        return {"FINISHED"}


def remove_default_delete_keymap() -> None:
    # Access the active keyconfig (modifiable keymap)
    keyconfig = bpy.context.window_manager.keyconfigs.active

    if keyconfig is None:
        return
    # Access the keymap for Object Mode
    keymap = keyconfig.keymaps.get("Object Mode")

    if keymap:
        # Loop through keymap items and find the Delete keybinding
        for keymap_item in keymap.keymap_items:
            if keymap_item.idname == "object.delete" and keymap_item.type == "DEL":
                keymap.keymap_items.remove(keymap_item)
                break

        for keymap_item in keymap.keymap_items:
            if keymap_item.idname == "object.delete" and keymap_item.type == "X":
                keymap.keymap_items.remove(keymap_item)
                break


def add_custom_delete_keymap() -> None:
    # Access the active keyconfig (modifiable keymap)
    keyconfig = bpy.context.window_manager.keyconfigs.active

    if keyconfig is None:
        return

    keymap = keyconfig.keymaps.get("Object Mode")

    if keymap:
        # Add a new keybinding for the custom delete operator
        keymap.keymap_items.new("object.delete_override", "DEL", "PRESS")
        keymap.keymap_items.new("object.delete_override", "X", "PRESS")


def restore_default_delete_keymap() -> None:
    # Access the active keyconfig (modifiable keymap)
    keyconfig = bpy.context.window_manager.keyconfigs.active

    if keyconfig is None:
        return

    # Access the keymap for Object Mode
    keymap = keyconfig.keymaps.get("Object Mode")

    if keymap:
        # Re-add the original Delete keybinding
        keymap.keymap_items.new("object.delete", "DEL", "PRESS")
        keymap.keymap_items.new("object.delete", "X", "PRESS")


def register() -> None:
    bpy.utils.register_class(OBJECT_OT_delete_override)

    # Remove default delete keymap and add custom one
    remove_default_delete_keymap()
    add_custom_delete_keymap()


def unregister() -> None:
    bpy.utils.unregister_class(OBJECT_OT_delete_override)
    restore_default_delete_keymap()
