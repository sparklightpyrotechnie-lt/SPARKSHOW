from __future__ import annotations

import bpy
from bpy.app.handlers import persistent

_HANDLER_NAME = "sparkshow_studio_frame_runtime"
_RENDER_PRE_HANDLER = "sparkshow_studio_render_pre"
_RENDER_POST_HANDLER = "sparkshow_studio_render_post"
_RENDER_CANCEL_HANDLER = "sparkshow_studio_render_cancel"
_RENDER_COMPLETE_HANDLER = "sparkshow_studio_render_complete"

_RENDER_ACTIVE = False
_RENDER_STATE = {}
_RESTORE_SCHEDULED = False


def _is_rendering() -> bool:
    if _RENDER_ACTIVE:
        return True
    try:
        return bool(bpy.app.is_job_running("RENDER"))
    except (AttributeError, TypeError, RuntimeError):
        return False


@persistent
def _frame_handler(scene: bpy.types.Scene) -> None:
    # Preview systems are viewport/editing systems. They must not mutate mesh,
    # curve, material or object data while Blender is rendering an animation.
    if _is_rendering() or scene is None:
        return

    try:
        from .fire.preview import _update_all
        _update_all(scene)
    except Exception as exc:
        print(f"[Sparkshow Studio] Pyro runtime error: {exc}")
    try:
        from .lighting.palette import update_preview_colors
        if getattr(scene, "studio_palette_live_preview", False):
            update_preview_colors(scene)
    except Exception as exc:
        print(f"[Sparkshow Studio] Lighting runtime error: {exc}")


_frame_handler.__name__ = _HANDLER_NAME


def _remove_handler_by_name(collection, name: str) -> None:
    for handler in list(collection):
        if getattr(handler, "__name__", "") == name:
            try:
                collection.remove(handler)
            except (ValueError, RuntimeError):
                pass


def _suspend_preview_handlers() -> None:
    """Suspend only Sparkshow's interactive frame handler during rendering.

    Do not delete/recreate Pyro objects here: destructive datablock changes from
    render callbacks are unnecessarily risky and can crash Blender with complex
    Curve/Geometry/Particle dependencies. Preview objects use hide_render=True,
    so they can safely remain in the scene.
    """
    _remove_handler_by_name(bpy.app.handlers.frame_change_post, _HANDLER_NAME)
    try:
        from .fire import preview_engines
        preview_engines.unregister_gpu_handler()
    except Exception as exc:
        print(f"[Sparkshow Studio] Preview GPU suspend warning: {exc}")


def _restore_preview_handlers() -> None:
    """Restore Sparkshow's interactive frame handler after rendering."""
    if all(getattr(h, "__name__", "") != _HANDLER_NAME for h in bpy.app.handlers.frame_change_post):
        bpy.app.handlers.frame_change_post.append(_frame_handler)
    try:
        from .fire import preview_engines
        preview_engines.register_gpu_handler()
    except Exception as exc:
        print(f"[Sparkshow Studio] Preview GPU restore warning: {exc}")


def _deferred_restore(scene: bpy.types.Scene | None) -> None:
    """Restore viewport-only systems outside the render callback."""
    global _RENDER_ACTIVE, _RENDER_STATE, _RESTORE_SCHEDULED
    state = dict(_RENDER_STATE)
    target_scene = state.get("scene") if state else scene
    try:
        if target_scene is not None:
            target_scene["sparkshow_studio_rendering"] = False
    except Exception:
        pass

    _RENDER_ACTIVE = False
    _RENDER_STATE = {}
    _RESTORE_SCHEDULED = False

    if target_scene is None:
        _restore_preview_handlers()
        return

    try:
        if state.get("palette_preview", False):
            from .lighting import palette
            palette.enable_live_preview(target_scene)
    except Exception as exc:
        print(f"[Sparkshow Studio] Lighting preview restore warning: {exc}")

    _restore_preview_handlers()
    try:
        for area in bpy.context.screen.areas if bpy.context.screen else ():
            if area.type == "VIEW_3D":
                area.tag_redraw()
    except Exception:
        pass


def _schedule_restore(scene: bpy.types.Scene | None) -> None:
    """Schedule restoration after Blender has fully exited the render callback."""
    global _RESTORE_SCHEDULED
    if _RESTORE_SCHEDULED:
        return
    _RESTORE_SCHEDULED = True

    def _callback():
        _deferred_restore(scene)
        return None

    try:
        bpy.app.timers.register(_callback, first_interval=0.1)
    except (AttributeError, RuntimeError):
        _deferred_restore(scene)


def _render_pre(scene: bpy.types.Scene) -> None:
    global _RENDER_ACTIVE, _RENDER_STATE
    _RENDER_ACTIVE = True
    try:
        from .setup import get_lightshow
        lightshow = get_lightshow(scene)
    except Exception:
        lightshow = None
    _RENDER_STATE = {
        "scene": scene,
        "pyro_preview": bool(getattr(lightshow, "fire_preview_enabled", False)),
        "palette_preview": bool(getattr(scene, "studio_palette_live_preview", False)),
    }
    try:
        scene["sparkshow_studio_rendering"] = True
    except Exception:
        pass

    # Restore keyed Lighting values before rendering starts.
    if _RENDER_STATE["palette_preview"]:
        try:
            from .lighting import palette
            palette.disable_live_preview(scene)
        except Exception as exc:
            print(f"[Sparkshow Studio] Render lighting cleanup warning: {exc}")

    # IMPORTANT: keep Pyro preview datablocks in place. They are hidden from
    # rendering; we only suspend the interactive update handler and GPU draw
    # handler. This makes rendering independent of viewport preview engines,
    # including the Curve renderer.
    _suspend_preview_handlers()


def _restore_after_render(scene: bpy.types.Scene | None) -> None:
    if not (_RENDER_ACTIVE or _RENDER_STATE):
        return
    _schedule_restore(scene)


@persistent
def _render_pre_handler(scene: bpy.types.Scene) -> None:
    _render_pre(scene)


@persistent
def _render_post_handler(scene: bpy.types.Scene) -> None:
    _restore_after_render(scene)


@persistent
def _render_cancel_handler(scene: bpy.types.Scene) -> None:
    _restore_after_render(scene)


@persistent
def _render_complete_handler(scene: bpy.types.Scene) -> None:
    if _RENDER_ACTIVE or _RENDER_STATE:
        _restore_after_render(scene)


_render_pre_handler.__name__ = _RENDER_PRE_HANDLER
_render_post_handler.__name__ = _RENDER_POST_HANDLER
_render_cancel_handler.__name__ = _RENDER_CANCEL_HANDLER
_render_complete_handler.__name__ = _RENDER_COMPLETE_HANDLER


def register() -> None:
    unregister()
    bpy.app.handlers.frame_change_post.append(_frame_handler)
    bpy.app.handlers.render_pre.append(_render_pre_handler)
    bpy.app.handlers.render_post.append(_render_post_handler)
    bpy.app.handlers.render_cancel.append(_render_cancel_handler)
    bpy.app.handlers.render_complete.append(_render_complete_handler)


def unregister() -> None:
    global _RENDER_ACTIVE, _RENDER_STATE, _RESTORE_SCHEDULED
    _remove_handler_by_name(bpy.app.handlers.frame_change_post, _HANDLER_NAME)
    _remove_handler_by_name(bpy.app.handlers.render_pre, _RENDER_PRE_HANDLER)
    _remove_handler_by_name(bpy.app.handlers.render_post, _RENDER_POST_HANDLER)
    _remove_handler_by_name(bpy.app.handlers.render_cancel, _RENDER_CANCEL_HANDLER)
    _remove_handler_by_name(bpy.app.handlers.render_complete, _RENDER_COMPLETE_HANDLER)
    _RENDER_ACTIVE = False
    _RENDER_STATE = {}
    _RESTORE_SCHEDULED = False
    try:
        scene = bpy.context.scene
        if scene is not None:
            scene["sparkshow_studio_rendering"] = False
    except Exception:
        pass
